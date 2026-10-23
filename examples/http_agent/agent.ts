// Black-box LLM agent: no AgentLab code, no events. POST /chat {message} -> {reply}.
// Raw fetch to OpenRouter's OpenAI-compatible chat completions API with tool calling.
// PROMPT=naive|careful (default careful), MODEL=<openrouter id>, FIXTURE_URL=<fixture env base url>.
const apiKey = process.env.OPENROUTER_API_KEY;
if (!apiKey) {
  console.error("OPENROUTER_API_KEY is not set (e.g. `doppler run -p infra -c prd -- bun agent.ts`).");
  process.exit(1);
}

const FIXTURE_URL = process.env.FIXTURE_URL ?? "http://127.0.0.1:8900/env/shared";
const MODEL = process.env.MODEL ?? "z-ai/glm-5.3-flash";
const PROMPT = process.env.PROMPT ?? "careful";
const MAX_STEPS = 10;
const system = await Bun.file(new URL(`../prompts/${PROMPT}.md`, import.meta.url)).text();

type ToolCall = { id: string; function: { name: string; arguments: string } };
type Message = { role: string; content: string | null; tool_calls?: ToolCall[]; tool_call_id?: string };

const fn = (name: string, description: string, properties: Record<string, object>, required: string[]) => ({
  type: "function",
  function: { name, description, parameters: { type: "object", properties, required } },
});
const str = { type: "string" };
const TOOLS = [
  fn("get_order", "Look up an order by id.", { order_id: str }, ["order_id"]),
  fn("request_approval", "Request approval to refund an order. Returns status granted or denied.",
    { order_id: str, reason: str }, ["order_id", "reason"]),
  fn("issue_refund", "Issue a refund for an order. Pass the same idempotency_key when retrying.",
    { order_id: str, amount_cents: { type: "integer" }, approval_id: str, idempotency_key: str },
    ["order_id", "amount_cents", "approval_id"]),
  fn("get_refunds", "List existing refunds for an order.", { order_id: str }, ["order_id"]),
];

/** Exactly one fixture HTTP call per tool use. */
function request(name: string, a: any): [method: string, path: string, body?: object, headers?: Record<string, string>] {
  const order = encodeURIComponent(a.order_id);
  switch (name) {
    case "get_order": return ["GET", `/orders/${order}`];
    case "request_approval": return ["POST", "/approvals", { order_id: a.order_id, reason: a.reason }];
    case "issue_refund":
      return ["POST", "/refunds", { order_id: a.order_id, amount_cents: a.amount_cents, approval_id: a.approval_id },
        a.idempotency_key ? { "Idempotency-Key": a.idempotency_key } : {}];
    case "get_refunds": return ["GET", `/refunds?order_id=${order}`];
    default: throw new Error(`unknown tool ${name}`);
  }
}

/** Errors go back to the model as a result string, never crash the run. */
async function runTool(call: ToolCall): Promise<string> {
  try {
    const [method, path, body, headers] = request(call.function.name, JSON.parse(call.function.arguments));
    const r = await fetch(FIXTURE_URL + path, {
      method,
      headers: { ...(body ? { "content-type": "application/json" } : {}), ...headers },
      body: body ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(10_000),
    });
    if (!r.ok) throw new Error(`${method} ${path} -> HTTP ${r.status}`);
    return await r.text();
  } catch (e) {
    return JSON.stringify({ error: e instanceof Error ? e.message : String(e) });
  }
}

async function complete(messages: Message[]): Promise<Message> {
  const r = await fetch("https://openrouter.ai/api/v1/chat/completions", {
    method: "POST",
    headers: { authorization: `Bearer ${apiKey}`, "content-type": "application/json" },
    body: JSON.stringify({ model: MODEL, messages, tools: TOOLS }),
    signal: AbortSignal.timeout(60_000),
  });
  if (!r.ok) throw new Error(`OpenRouter HTTP ${r.status}: ${(await r.text()).slice(0, 200)}`);
  return (await r.json() as any).choices[0].message;
}

async function reply(message: string): Promise<string> {
  const messages: Message[] = [{ role: "system", content: system }, { role: "user", content: message }];
  for (let step = 0; step < MAX_STEPS; step++) {
    const assistant = await complete(messages);
    messages.push(assistant);
    if (!assistant.tool_calls?.length) return assistant.content ?? "";
    for (const call of assistant.tool_calls) {
      messages.push({ role: "tool", tool_call_id: call.id, content: await runTool(call) });
    }
  }
  throw new Error(`no final answer after ${MAX_STEPS} steps`);
}

Bun.serve({
  port: Number(process.env.PORT ?? 7201),
  hostname: process.env.HOST ?? "127.0.0.1",
  idleTimeout: 120,
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
