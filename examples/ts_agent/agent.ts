// Reference customer-ops agent in TypeScript (port of examples/python_agent/agent.py).
// AGENT_VARIANT=buggy  retries a timed-out refund without an idempotency key and ignores denied approvals.
// AGENT_VARIANT=fixed  sends an idempotency key on every refund attempt and stops when approval is denied.
import { serve, type InvokeRequest, type Recorder } from "./agentlab";

const VARIANT = process.env.AGENT_VARIANT ?? "fixed";
const MAX_ATTEMPTS = 3;

async function handle(req: InvokeRequest, rec: Recorder): Promise<string> {
  const orderId = /ORD-\d+/.exec(req.input.message ?? "")?.[0];
  if (!orderId) return "Which order should I refund? Please include the order ID.";

  const call = (name: string, method: string, path: string, body?: unknown, headers: Record<string, string> = {}) =>
    rec.tool(name, async () => {
      const r = await fetch(req.environment.base_url + path, {
        method,
        headers: { ...(body ? { "content-type": "application/json" } : {}), ...headers },
        body: body ? JSON.stringify(body) : undefined,
        signal: AbortSignal.timeout(10_000),
      });
      if (!r.ok) throw new Error(`${method} ${path} -> HTTP ${r.status}`);
      return (await r.json()) as any;
    });

  const order = await call("get_order", "GET", `/orders/${orderId}`);
  rec.emit("approval_requested", null, { order_id: orderId });
  const approval = await call("request_approval", "POST", "/approvals", { order_id: orderId });
  if (approval.status !== "granted" && VARIANT === "fixed") {
    return `Refund for ${orderId} needs manual review; I've escalated it.`;
  }

  const body = { order_id: orderId, amount_cents: order.amount_cents, approval_id: approval.approval_id };
  const headers: Record<string, string> = VARIANT === "fixed" ? { "Idempotency-Key": `refund-${req.idempotency_key}` } : {};
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    try {
      await call("issue_refund", "POST", "/refunds", body, headers);
      break;
    } catch (e) {
      if (attempt === MAX_ATTEMPTS) throw e;
      rec.emit("retry_scheduled", "issue_refund", { attempt: attempt + 1 });
    }
  }
  return `Your refund of $${(order.amount_cents / 100).toFixed(2)} for ${orderId} is complete.`;
}

serve(
  {
    adapter_id: `ts-customer-ops-${VARIANT}`,
    language: "typescript",
    capabilities: { observe: "native_events" },
  },
  handle,
  Number(process.env.PORT ?? 7101),
);
