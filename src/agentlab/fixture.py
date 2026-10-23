"""Reference environment: a customer/refund service backed by Postgres, one isolated schema per environment id.

Faults live at the service boundary, so they work for any harness language, including black-box HTTP agents.
Every tool call is recorded in a side-effect ledger; replaying the committed prefix of a ledger restores the exact
state at any point of a run, which is how checkpoint forks get a matching environment.
"""

import re
import threading
import time
from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from typing import Annotated, ClassVar, LiteralString, cast

import psycopg
import uvicorn
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from psycopg import Cursor, sql
from psycopg.rows import DictRow
from psycopg.types.json import Jsonb
from pydantic import BaseModel, JsonValue

from agentlab.db import Pool
from agentlab.protocol import JsonObject, ToolFault
from agentlab.records import LedgerEntry, Row, State

DDL = """
CREATE TABLE customers (id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE orders (id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, amount_cents INTEGER NOT NULL);
CREATE TABLE approvals (id SERIAL PRIMARY KEY, order_id TEXT NOT NULL, status TEXT NOT NULL);
CREATE TABLE refunds (
    id SERIAL PRIMARY KEY, order_id TEXT NOT NULL, amount_cents INTEGER NOT NULL,
    approval_id INTEGER, idempotency_key TEXT UNIQUE
);
CREATE TABLE ledger (
    seq BIGSERIAL PRIMARY KEY, tool TEXT NOT NULL, request JSONB NOT NULL, status INTEGER NOT NULL,
    response JSONB NOT NULL, committed BOOLEAN NOT NULL, ts DOUBLE PRECISION NOT NULL
);
"""
BUSINESS_TABLES = ("customers", "orders", "approvals", "refunds")
SEED_COLUMNS = {"customers": ("id", "name"), "orders": ("id", "customer_id", "amount_cents")}
ENV_ID = re.compile(r"^[a-z0-9_]{1,48}$")
SHARED_ENV = "shared"  # for black-box agents configured with one static fixture URL
ASSERTION_TIMEOUT = "5s"

type ToolResult = tuple[int, JsonValue]
type Cur = Cursor[DictRow]


class Seed(BaseModel):
    customers: list[Row] = []
    orders: list[Row] = []
    approval_limit_cents: int = 50_000


def _one(cur: Cur, query: LiteralString, *args: JsonValue) -> Row | None:
    cur.execute(query, args)
    row = cur.fetchone()
    return dict(row) if row else None


class ToolCall(BaseModel, ABC):
    """A validated tool request. `run` performs it inside the caller's transaction."""

    tool: ClassVar[str]

    @abstractmethod
    def run(self, cur: Cur, seed: Seed) -> ToolResult: ...


class GetOrder(ToolCall):
    tool: ClassVar[str] = "get_order"
    order_id: str

    def run(self, cur: Cur, seed: Seed) -> ToolResult:
        row = _one(cur, "SELECT * FROM orders WHERE id = %s", self.order_id)
        return (200, row) if row else (404, {"error": "order not found"})


class RequestApproval(ToolCall):
    tool: ClassVar[str] = "request_approval"
    order_id: str
    reason: str = ""

    def run(self, cur: Cur, seed: Seed) -> ToolResult:
        order = _one(cur, "SELECT amount_cents FROM orders WHERE id = %s", self.order_id)
        if not order:
            return 404, {"error": "order not found"}
        amount = order["amount_cents"]
        status = "granted" if isinstance(amount, int) and amount <= seed.approval_limit_cents else "denied"
        row = _one(cur, "INSERT INTO approvals (order_id, status) VALUES (%s, %s) RETURNING id", self.order_id, status)
        return 200, {"approval_id": row["id"] if row else None, "status": status}


class IssueRefund(ToolCall):
    tool: ClassVar[str] = "issue_refund"
    order_id: str
    amount_cents: int
    approval_id: int | None = None
    idempotency_key: str | None = None

    def run(self, cur: Cur, seed: Seed) -> ToolResult:
        if self.idempotency_key and (
            prior := _one(cur, "SELECT * FROM refunds WHERE idempotency_key = %s", self.idempotency_key)
        ):
            return 200, prior
        if not _one(cur, "SELECT 1 FROM orders WHERE id = %s", self.order_id):
            return 404, {"error": "order not found"}
        row = _one(
            cur,
            "INSERT INTO refunds (order_id, amount_cents, approval_id, idempotency_key) VALUES (%s, %s, %s, %s) "
            "RETURNING *",
            self.order_id,
            self.amount_cents,
            self.approval_id,
            self.idempotency_key,
        )
        return 201, row


class GetRefunds(ToolCall):
    tool: ClassVar[str] = "get_refunds"
    order_id: str

    def run(self, cur: Cur, seed: Seed) -> ToolResult:
        cur.execute("SELECT * FROM refunds WHERE order_id = %s ORDER BY id", (self.order_id,))
        return 200, [dict(r) for r in cur.fetchall()]


class DeleteCustomer(ToolCall):
    tool: ClassVar[str] = "delete_customer"
    customer_id: str

    def run(self, cur: Cur, seed: Seed) -> ToolResult:
        cur.execute("DELETE FROM customers WHERE id = %s", (self.customer_id,))
        return 200, {"deleted": self.customer_id}


TOOL_CALLS: dict[str, type[ToolCall]] = {
    c.tool: c for c in (GetOrder, RequestApproval, IssueRefund, GetRefunds, DeleteCustomer)
}


class Fixture:
    """One isolated environment: its own Postgres schema. Calls are serialized so the ledger order is exact."""

    def __init__(self, db: Pool, env_id: str, seed: Seed, faults: Sequence[ToolFault] = ()) -> None:
        if not ENV_ID.match(env_id):
            raise ValueError(f"invalid environment id {env_id!r}")
        self.db, self.env_id, self.seed = db, env_id, seed
        self.schema = sql.Identifier(f"env_{env_id}")
        # Author SQL (assertions, test queries) runs as this role: it can read this environment's schema and nothing
        # else, so a query cannot reach stored results (schema agentlab) or other trials' environments.
        self.reader = sql.Identifier(f"agentlab_r_{env_id}")
        self.faults, self.calls = list(faults), Counter[str]()
        self.lock = threading.Lock()
        with db.connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {s} CASCADE; CREATE SCHEMA {s}").format(s=self.schema))
            cur.execute(sql.SQL("SET LOCAL search_path TO {}").format(self.schema))
            cur.execute(DDL)
            for table, rows in (("customers", seed.customers), ("orders", seed.orders)):
                for row in rows:
                    cols = SEED_COLUMNS[table]
                    if unknown := set(row) - set(cols):
                        raise ValueError(f"unknown {table} column(s): {sorted(unknown)}")
                    query = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                        sql.Identifier(table),
                        sql.SQL(", ").join(map(sql.Identifier, row)),
                        sql.SQL(", ").join(sql.Placeholder() * len(row)),
                    )
                    cur.execute(query, list(row.values()))
            cur.execute(
                sql.SQL(
                    "DROP ROLE IF EXISTS {r}; CREATE ROLE {r} NOLOGIN; GRANT USAGE ON SCHEMA {s} TO {r}; "
                    "GRANT SELECT ON ALL TABLES IN SCHEMA {s} TO {r}; GRANT {r} TO CURRENT_USER"
                ).format(r=self.reader, s=self.schema)
            )

    @classmethod
    def restore(
        cls, db: Pool, env_id: str, seed: Seed, history: Sequence[LedgerEntry], faults: Sequence[ToolFault] = ()
    ) -> "Fixture":
        """Rebuild the state after `history` by re-applying its committed calls; fault counters continue from there."""
        fx = cls(db, env_id, seed, faults)
        with fx.lock, fx._tx() as cur:
            for entry in history:
                if entry.committed:
                    TOOL_CALLS[entry.tool].model_validate(entry.request).run(cur, seed)
                fx.calls[entry.tool] += 1
                fx._log(cur, entry.tool, entry.request, entry.status, entry.response, committed=entry.committed)
        return fx

    @contextmanager
    def _tx(self, *, read_only: bool = False) -> Generator[Cur]:
        with self.db.connection() as conn, conn.transaction(), conn.cursor() as cur:
            if read_only:
                cur.execute("SET TRANSACTION READ ONLY")  # assertions must never mutate the environment
                cur.execute(sql.SQL("SET LOCAL statement_timeout = {}").format(sql.Literal(ASSERTION_TIMEOUT)))
            cur.execute(sql.SQL("SET LOCAL search_path TO {}").format(self.schema))
            yield cur

    def call(self, call: ToolCall) -> ToolResult:
        """Run one tool call: apply any scripted fault, commit, and record it in the side-effect ledger."""
        with self.lock, self._tx() as cur:
            self.calls[call.tool] += 1
            fault = next((f for f in self.faults if f.fires_on(call.tool, self.calls[call.tool])), None)
            status: int
            body: JsonValue
            committed = False
            if fault and fault.action == "error_before_commit":
                status = 503
                body = {"error": "service unavailable"}
            else:
                try:
                    with cur.connection.transaction():  # savepoint: a failed call must not poison the ledger write
                        status, body = call.run(cur, self.seed)
                    committed = status < 400
                except psycopg.Error as exc:
                    status = 500
                    body = {"error": f"database error: {exc.diag.message_primary or exc}"}
                if fault:  # timeout_after_commit: committed, but the caller never learns it
                    status = 504
                    body = {"error": "upstream timeout"}
            self._log(cur, call.tool, call.model_dump(mode="json"), status, body, committed=committed)
        return status, body

    def _log(self, cur: Cur, tool: str, request: JsonObject, status: int, body: JsonValue, *, committed: bool) -> None:
        cur.execute(
            "INSERT INTO ledger (tool, request, status, response, committed, ts) VALUES (%s, %s, %s, %s, %s, %s)",
            (tool, Jsonb(request), status, Jsonb(body), committed, time.time()),
        )

    def query(self, query: str) -> list[tuple[JsonValue, ...]]:
        """Run author SQL read-only as this environment's reader role.

        Wrapping it as a subquery admits only a row-returning query (no RESET ROLE / SET / DDL), and a prepared
        statement makes the server reject multiple commands, so the role cannot be shed."""
        # Untrusted by design (it is the test author's assertion); contained by the reader role and the wrapper.
        author_sql = cast("LiteralString", query.strip().rstrip(";"))
        wrapped = sql.SQL("SELECT * FROM ({}) AS author_query").format(sql.SQL(author_sql))
        with self._tx(read_only=True) as cur:
            cur.execute(sql.SQL("SET LOCAL ROLE {}").format(self.reader))
            cur.execute(wrapped, prepare=True)
            return [tuple(r.values()) for r in cur.fetchall()]

    def state(self) -> State:
        with self._tx(read_only=True) as cur:
            out: State = {}
            for t in BUSINESS_TABLES:
                cur.execute(sql.SQL("SELECT * FROM {} ORDER BY 1").format(sql.Identifier(t)))
                out[t] = [dict(r) for r in cur.fetchall()]
            return out

    def ledger(self) -> list[LedgerEntry]:
        with self._tx(read_only=True) as cur:
            cur.execute("SELECT * FROM ledger ORDER BY seq")
            return [LedgerEntry.model_validate(r) for r in cur.fetchall()]

    def drop(self) -> None:
        with self.db.connection() as conn:
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(self.schema))
            conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(self.reader))


class FixturePool:
    """Live environments by id, so concurrent trials never share state."""

    def __init__(self, db: Pool) -> None:
        self.db = db
        self._envs: dict[str, Fixture] = {}
        self._lock = threading.Lock()

    def create(
        self, env_id: str, seed: Seed, faults: Sequence[ToolFault] = (), history: Sequence[LedgerEntry] = ()
    ) -> Fixture:
        fx = (
            Fixture.restore(self.db, env_id, seed, history, faults)
            if history
            else Fixture(self.db, env_id, seed, faults)
        )
        with self._lock:
            self._envs[env_id] = fx
        return fx

    def get(self, env_id: str) -> Fixture:
        with self._lock:
            return self._envs[env_id]

    def drop(self, env_id: str) -> None:
        with self._lock:
            fx = self._envs.pop(env_id, None)
        if fx:
            fx.drop()


class EnvState(BaseModel):
    tables: State
    ledger: list[LedgerEntry]


class ResetBody(BaseModel):
    seed: Seed = Seed()
    faults: list[ToolFault] = []


def create_app(pool: FixturePool, *, admin: bool = False) -> FastAPI:
    """Agent-facing tool routes. `admin=True` adds reset/state routes for standalone manual use only: agents under
    test share this server, so on the runner's server they could otherwise wipe evidence or read other environments."""
    app = FastAPI(title="AgentLab refund fixture")
    env = APIRouter(prefix="/env/{env_id}")

    def lookup(env_id: str) -> Fixture:
        try:
            return pool.get(env_id)
        except KeyError:
            raise HTTPException(404, f"unknown environment {env_id!r}") from None

    type Env = Annotated[Fixture, Depends(lookup)]

    def respond(fx: Fixture, call: ToolCall) -> JSONResponse:
        status, body = fx.call(call)
        return JSONResponse(body, status_code=status)

    @env.get("/orders/{order_id}")
    def get_order(fx: Env, order_id: str) -> JSONResponse:
        return respond(fx, GetOrder(order_id=order_id))

    @env.post("/approvals")
    def request_approval(fx: Env, body: RequestApproval) -> JSONResponse:
        return respond(fx, body)

    @env.post("/refunds")
    def issue_refund(
        fx: Env, body: IssueRefund, idempotency_key: Annotated[str | None, Header()] = None
    ) -> JSONResponse:
        return respond(fx, body.model_copy(update={"idempotency_key": idempotency_key or body.idempotency_key}))

    @env.get("/refunds")
    def get_refunds(fx: Env, order_id: str) -> JSONResponse:
        return respond(fx, GetRefunds(order_id=order_id))

    @env.delete("/customers/{customer_id}")
    def delete_customer(fx: Env, customer_id: str) -> JSONResponse:
        return respond(fx, DeleteCustomer(customer_id=customer_id))

    app.include_router(env)
    if not admin:
        return app

    admin_routes = APIRouter(prefix="/env/{env_id}/admin")

    @admin_routes.post("/reset")
    def admin_reset(env_id: str, body: ResetBody) -> dict[str, bool]:
        try:
            pool.create(env_id, body.seed, body.faults)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        return {"ok": True}

    @admin_routes.get("/state")
    def admin_state(fx: Env) -> EnvState:
        return EnvState(tables=fx.state(), ledger=fx.ledger())

    app.include_router(admin_routes)
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
