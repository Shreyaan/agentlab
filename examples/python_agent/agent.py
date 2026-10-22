"""Reference customer-ops agent in Python. Deterministic stand-in for an LLM loop so the demo is reproducible.

AGENT_VARIANT=buggy  retries a timed-out refund without an idempotency key and ignores denied approvals.
AGENT_VARIANT=fixed  sends an idempotency key on every refund attempt and stops when approval is denied.
"""

import os
import re

import httpx

from agentlab.adapter import Recorder, serve
from agentlab.protocol import Capabilities, InvokeRequest, Manifest

VARIANT = os.environ.get("AGENT_VARIANT", "fixed")
MAX_ATTEMPTS = 3


def handle(req: InvokeRequest, rec: Recorder) -> str:
    match = re.search(r"ORD-\d+", req.input.get("message", ""))
    if not match:
        return "Which order should I refund? Please include the order ID."
    order_id = match.group()

    with httpx.Client(base_url=req.environment.base_url, timeout=10) as api:

        def call(name: str, method: str, path: str, **kw) -> dict:
            def send():
                r = api.request(method, path, **kw)
                r.raise_for_status()
                return r.json()

            return rec.tool(name, send)

        order = call("get_order", "GET", f"/orders/{order_id}")
        rec.emit("approval_requested", order_id=order_id)
        approval = call("request_approval", "POST", "/approvals", json={"order_id": order_id})
        if approval["status"] != "granted" and VARIANT == "fixed":
            return f"Refund for {order_id} needs manual review; I've escalated it."

        body = {"order_id": order_id, "amount_cents": order["amount_cents"], "approval_id": approval["approval_id"]}
        headers = {"Idempotency-Key": f"refund-{req.idempotency_key}"} if VARIANT == "fixed" else {}
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                call("issue_refund", "POST", "/refunds", json=body, headers=headers)
                break
            except httpx.HTTPStatusError:
                if attempt == MAX_ATTEMPTS:
                    raise
                rec.emit("retry_scheduled", "issue_refund", attempt=attempt + 1)
    return f"Your refund of ${order['amount_cents'] / 100:.2f} for {order_id} is complete."


if __name__ == "__main__":
    manifest = Manifest(
        adapter_id=f"python-customer-ops-{VARIANT}",
        language="python",
        capabilities=Capabilities(observe="native_events"),
    )
    serve(manifest, handle, port=int(os.environ.get("PORT", "7102")), host=os.environ.get("HOST", "127.0.0.1"))
