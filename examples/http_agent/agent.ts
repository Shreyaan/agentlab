// Black-box LLM agent: no AgentLab code, no events. POST /chat {message} -> {reply}.
// Raw fetch to OpenRouter's OpenAI-compatible chat completions API with tool calling.
// PROMPT=naive|careful (default careful), MODEL=<openrouter id>, FIXTURE_URL=<environment base url, .../env/<id>>.
import { errorAsResult, loadCatalog, postTool, systemPrompt } from "../env_tools.ts";

const apiKey = process.env.OPENROUTER_API_KEY;
if (!apiKey) {
  console.error("OPENROUTER_API_KEY is not set (e.g. `doppler run -p infra -c prd -- bun agent.ts`).");
  process.exit(1);
}

const FIXTURE_URL = process.env.FIXTURE_URL ?? "http://127.0.0.1:8900/env/shared";
const MODEL = process.env.MODEL ?? "z-ai/glm-5.3-flash";
const PROMPT = process.env.PROMPT ?? "careful";
const MAX_STEPS = 10;

type ToolCall = { id: string; function: { name: string; arguments: string } };
type Message = { role: string; content: string | null; tool_calls?: ToolCall[]; tool_call_id?: string };

/** Black box: reads the catalog itself, one POST per tool use, no AgentLab code. */
async function runTool(call: ToolCall, names: Set<string>): Promise<string> {
  const { name, arguments: args } = call.function;
  if (!names.has(name)) return JSON.stringify({ error: `unknown tool ${name}` });
  return errorAsResult(() => postTool(FIXTURE_URL, name, JSON.parse(args || "{}")));
}

async function complete(messages: Message[], tools: unknown[]): Promise<Message> {
  const r = await fetch("https://openrouter.ai/api/v1/chat/completions", {
    method: "POST",
    headers: { authorization: `Bearer ${apiKey}`, "content-type": "application/json" },
    body: JSON.stringify({ model: MODEL, messages, tools }),
    signal: AbortSignal.timeout(60_000),
  });
  if (!r.ok) throw new Error(`OpenRouter HTTP ${r.status}: ${(await r.text()).slice(0, 200)}`);
  return (await r.json() as any).choices[0].message;
}

async function reply(message: string): Promise<string> {
  const catalog = await loadCatalog(FIXTURE_URL);
  const names = new Set(catalog.tools.map((t) => t.name));
  const tools = catalog.tools.map((t) => ({
    type: "function",
    function: { name: t.name, description: t.description, parameters: t.parameters },
  }));
  const system = await systemPrompt(PROMPT, catalog);
  const messages: Message[] = [{ role: "system", content: system }, { role: "user", content: message }];
  for (let step = 0; step < MAX_STEPS; step++) {
    const assistant = await complete(messages, tools);
    messages.push(assistant);
    if (!assistant.tool_calls?.length) return assistant.content ?? "";
    for (const call of assistant.tool_calls) {
      messages.push({ role: "tool", tool_call_id: call.id, content: await runTool(call, names) });
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
