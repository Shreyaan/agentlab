// Generic black-box HTTP agent: no AgentLab code, no events. POST /chat {message} -> {reply}.
// AGENT_VARIANT=buggy|fixed behaves like the other reference agents.
const VARIANT = process.env.AGENT_VARIANT ?? "fixed";
const FIXTURE_URL = process.env.FIXTURE_URL ?? "http://127.0.0.1:8900";
const MAX_ATTEMPTS = 3;

async function api(method: string, path: string, body?: unknown, headers: Record<string, string> = {}) {
  const r = await fetch(FIXTURE_URL + path, {
    method,
    headers: { ...(body ? { "content-type": "application/json" } : {}), ...headers },
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(10_000),
  });
  if (!r.ok) throw new Error(`${method} ${path} -> HTTP ${r.status}`);
  return (await r.json()) as any;
}

async function reply(message: string): Promise<string> {
  const orderId = /ORD-\d+/.exec(message)?.[0];
  if (!orderId) return "Which order should I refund? Please include the order ID.";

  const order = await api("GET", `/orders/${orderId}`);
  const approval = await api("POST", "/approvals", { order_id: orderId });
  if (approval.status !== "granted" && VARIANT === "fixed") {
    return `Refund for ${orderId} needs manual review; I've escalated it.`;
  }

  const body = { order_id: orderId, amount_cents: order.amount_cents, approval_id: approval.approval_id };
  // Stable key per order+approval so retries of the same refund dedupe.
  const headers: Record<string, string> = VARIANT === "fixed" ? { "Idempotency-Key": `refund-${approval.approval_id}` } : {};
  for (let attempt = 1; ; attempt++) {
    try {
      await api("POST", "/refunds", body, headers);
      break;
    } catch (e) {
      if (attempt === MAX_ATTEMPTS) throw e;
    }
  }
  return `Your refund of $${(order.amount_cents / 100).toFixed(2)} for ${orderId} is complete.`;
}

Bun.serve({
  port: Number(process.env.PORT ?? 7201),
  hostname: process.env.HOST ?? "127.0.0.1",
  async fetch(request) {
    if (request.method !== "POST" || new URL(request.url).pathname !== "/chat") {
      return new Response("not found", { status: 404 });
    }
    try {
      const { message } = (await request.json()) as { message?: string };
      return Response.json({ reply: await reply(message ?? "") });
    } catch (e) {
      return Response.json({ error: e instanceof Error ? e.message : String(e) }, { status: 500 });
    }
  },
});
