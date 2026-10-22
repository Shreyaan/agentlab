"""Reference environment: a resettable customer/refund service with a side-effect ledger and fault injection.

Faults live at the service boundary, so they work for any harness language, including black-box HTTP agents.
"""

import json
import sqlite3
import threading
import time
from collections import Counter
from typing import Any, Literal

import uvicorn
from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

SCHEMA = """
CREATE TABLE customers (id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE orders (id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, amount_cents INTEGER NOT NULL);
CREATE TABLE approvals (id INTEGER PRIMARY KEY, order_id TEXT NOT NULL, status TEXT NOT NULL);
CREATE TABLE refunds (
    id INTEGER PRIMARY KEY, order_id TEXT NOT NULL, amount_cents INTEGER NOT NULL,
    approval_id INTEGER, idempotency_key TEXT UNIQUE
);
CREATE TABLE ledger (seq INTEGER PRIMARY KEY, tool TEXT NOT NULL, request TEXT, status INTEGER, response TEXT, ts REAL);
"""
TABLES = ["customers", "orders", "approvals", "refunds", "ledger"]


class Fault(BaseModel):
    tool: str
    when: Literal["first_call", "always"] | int = "first_call"  # int = nth call (1-based)
    action: Literal["timeout_after_commit", "error_before_commit"]


class Seed(BaseModel):
    customers: list[dict[str, Any]] = []
    orders: list[dict[str, Any]] = []
    approval_limit_cents: int = 50_000


class Fixture:
    """One in-memory environment. All access goes through a lock so the HTTP thread and the runner agree."""

    def __init__(self) -> None:
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self.reset(Seed())

    def reset(self, seed: Seed, faults: list[Fault] = ()) -> None:
        with self.lock:
            self.db.executescript("".join(f"DROP TABLE IF EXISTS {t};" for t in TABLES) + SCHEMA)
            for table in ("customers", "orders"):
                for row in getattr(seed, table):
                    cols = ", ".join(row)
                    self.db.execute(f"INSERT INTO {table} ({cols}) VALUES ({', '.join('?' * len(row))})", list(row.values()))
            self.db.commit()
            self.seed, self.faults, self.calls = seed, list(faults), Counter()

    def query(self, sql: str) -> list[tuple]:
        with self.lock:
            self.db.execute("PRAGMA query_only = ON")  # assertions must never mutate the environment
            try:
                return [tuple(r) for r in self.db.execute(sql).fetchall()]
            finally:
                self.db.execute("PRAGMA query_only = OFF")

    def state(self) -> dict[str, list[dict]]:
        with self.lock:
            return {t: [dict(r) for r in self.db.execute(f"SELECT * FROM {t}")] for t in TABLES if t != "ledger"}

    def ledger(self) -> list[dict]:
        with self.lock:
            rows = [dict(r) for r in self.db.execute("SELECT * FROM ledger ORDER BY seq")]
        for r in rows:
            r["request"], r["response"] = json.loads(r["request"]), json.loads(r["response"])
        return rows

    def call(self, tool: str, request: dict, handler) -> JSONResponse:
        """Run one tool call: apply any scripted fault, commit, and record it in the side-effect ledger."""
        with self.lock:
            self.calls[tool] += 1
            fault = self._fault_for(tool)
            if fault and fault.action == "error_before_commit":
                status, body = 503, {"error": "service unavailable"}
            else:
                try:
                    status, body = handler()
                    self.db.commit()
                except sqlite3.Error as exc:
                    self.db.rollback()
                    status, body = 500, {"error": f"database error: {exc}"}
                if fault and fault.action == "timeout_after_commit":
                    status, body = 504, {"error": "upstream timeout"}  # committed, but the caller never learns it
            self.db.execute(
                "INSERT INTO ledger (tool, request, status, response, ts) VALUES (?, ?, ?, ?, ?)",
                (tool, json.dumps(request), status, json.dumps(body), time.time()),
            )
            self.db.commit()
        return JSONResponse(body, status_code=status)

    def _fault_for(self, tool: str) -> Fault | None:
        n = self.calls[tool]
        for f in self.faults:
            if f.tool == tool and (f.when == "always" or (f.when == "first_call" and n == 1) or f.when == n):
                return f
        return None

    def _one(self, sql: str, *args) -> dict | None:
        row = self.db.execute(sql, args).fetchone()
        return dict(row) if row else None


class RefundIn(BaseModel):
    order_id: str
    amount_cents: int
    approval_id: int | None = None


class ApprovalIn(BaseModel):
    order_id: str
    reason: str = ""


class ResetIn(BaseModel):
    seed: Seed = Seed()
    faults: list[Fault] = []


def create_app(fx: Fixture) -> FastAPI:
    app = FastAPI(title="AgentLab refund fixture")

    @app.get("/orders/{order_id}")
    def get_order(order_id: str):
        def h():
            row = fx._one("SELECT * FROM orders WHERE id = ?", order_id)
            return (200, row) if row else (404, {"error": "order not found"})

        return fx.call("get_order", {"order_id": order_id}, h)

    @app.post("/approvals")
    def request_approval(body: ApprovalIn):
        def h():
            order = fx._one("SELECT * FROM orders WHERE id = ?", body.order_id)
            if not order:
                return 404, {"error": "order not found"}
            status = "granted" if order["amount_cents"] <= fx.seed.approval_limit_cents else "denied"
            cur = fx.db.execute("INSERT INTO approvals (order_id, status) VALUES (?, ?)", (body.order_id, status))
            return 200, {"approval_id": cur.lastrowid, "status": status}

        return fx.call("request_approval", body.model_dump(), h)

    @app.post("/refunds")
    def issue_refund(body: RefundIn, idempotency_key: str | None = Header(None)):
        def h():
            if idempotency_key and (prior := fx._one("SELECT * FROM refunds WHERE idempotency_key = ?", idempotency_key)):
                return 200, prior
            if not fx._one("SELECT 1 FROM orders WHERE id = ?", body.order_id):
                return 404, {"error": "order not found"}
            cur = fx.db.execute(
                "INSERT INTO refunds (order_id, amount_cents, approval_id, idempotency_key) VALUES (?, ?, ?, ?)",
                (body.order_id, body.amount_cents, body.approval_id, idempotency_key),
            )
            return 201, fx._one("SELECT * FROM refunds WHERE id = ?", cur.lastrowid)

        return fx.call("issue_refund", body.model_dump() | {"idempotency_key": idempotency_key}, h)

    @app.get("/refunds")
    def get_refund(order_id: str):
        def h():
            rows = fx.db.execute("SELECT * FROM refunds WHERE order_id = ?", (order_id,)).fetchall()
            return 200, [dict(r) for r in rows]

        return fx.call("get_refund", {"order_id": order_id}, h)

    @app.delete("/customers/{customer_id}")
    def delete_customer(customer_id: str):
        def h():
            fx.db.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
            return 200, {"deleted": customer_id}

        return fx.call("delete_customer", {"customer_id": customer_id}, h)

    # Admin surface for standalone use (`agentlab fixture`); the runner calls the Fixture object directly.
    @app.post("/admin/reset")
    def admin_reset(body: ResetIn):
        fx.reset(body.seed, body.faults)
        return {"ok": True}

    @app.get("/admin/state")
    def admin_state():
        return fx.state() | {"ledger": fx.ledger()}

    return app


def serve_in_thread(app: FastAPI, port: int, host: str = "127.0.0.1") -> uvicorn.Server:
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.time() + 10
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError(f"server on port {port} failed to start")
        time.sleep(0.02)
    return server
