// Real LLM customer-ops agent: Vercel AI SDK + OpenRouter, served through the AgentLab TS adapter.
// PROMPT=naive|careful (default careful) picks examples/prompts/<PROMPT>.md; MODEL is an OpenRouter model id.
import { createOpenRouter } from "@openrouter/ai-sdk-provider";
import { generateText, isStepCount, tool } from "ai";
import { z } from "zod";
import { serve, type InvokeRequest, type Recorder } from "../../packages/adapter-ts/agentlab.ts";

const apiKey = process.env.OPENROUTER_API_KEY;
if (!apiKey) {
  console.error("OPENROUTER_API_KEY is not set (e.g. `doppler run -p infra -c prd -- bun agent.ts`).");
  process.exit(1);
}

const PROMPT = process.env.PROMPT ?? "careful";
const MODEL = process.env.MODEL ?? "z-ai/glm-5.3-flash";
const MAX_STEPS = 10;
const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

const system = await Bun.file(new URL(`../prompts/${PROMPT}.md`, import.meta.url)).text();
const openrouter = createOpenRouter({ apiKey });

/** One fixture HTTP call per tool use; failures go back to the model as a result string, not a crash. */
function fixtureTool(req: InvokeRequest, rec: Recorder) {
  return (name: string, method: string, path: (a: any) => string, body?: (a: any) => unknown, headers?: (a: any) => Record<string, string>) =>
    async (args: any): Promise<string> => {
      try {
        return await rec.tool(name, async () => {
          const payload = body?.(args);
          const r = await fetch(req.environment.base_url + path(args), {
            method,
            headers: { ...(payload ? { "content-type": "application/json" } : {}), ...headers?.(args) },
            body: payload ? JSON.stringify(payload) : undefined,
            signal: AbortSignal.timeout(10_000),
          });
          if (!r.ok) throw new Error(`${method} ${path(args)} -> HTTP ${r.status}`);
          return await r.text();
        });
      } catch (e) {
        return JSON.stringify({ error: e instanceof Error ? e.message : String(e) });
      }
    };
}

async function handle(req: InvokeRequest, rec: Recorder): Promise<string> {
  const call = fixtureTool(req, rec);
  const orderId = z.string().describe("Order id, e.g. ORD-1001");
  const tools = {
    get_order: tool({
      description: "Look up an order by id.",
      inputSchema: z.object({ order_id: orderId }),
      execute: call("get_order", "GET", (a) => `/orders/${encodeURIComponent(a.order_id)}`),
    }),
    request_approval: tool({
      description: "Request approval to refund an order. Returns status granted or denied.",
      inputSchema: z.object({ order_id: orderId, reason: z.string() }),
      execute: call("request_approval", "POST", () => "/approvals", (a) => ({ order_id: a.order_id, reason: a.reason })),
    }),
    issue_refund: tool({
      description: "Issue a refund for an order. Pass the same idempotency_key when retrying.",
      inputSchema: z.object({
        order_id: orderId,
        amount_cents: z.number().int(),
        approval_id: z.string(),
        idempotency_key: z.string().optional(),
      }),
      execute: call(
        "issue_refund", "POST", () => "/refunds",
        (a) => ({ order_id: a.order_id, amount_cents: a.amount_cents, approval_id: a.approval_id }),
        (a): Record<string, string> => (a.idempotency_key ? { "Idempotency-Key": a.idempotency_key } : {}),
      ),
    }),
    get_refunds: tool({
      description: "List existing refunds for an order.",
      inputSchema: z.object({ order_id: orderId }),
      execute: call("get_refunds", "GET", (a) => `/refunds?order_id=${encodeURIComponent(a.order_id)}`),
    }),
  };

  const result = await generateText({
    model: openrouter(MODEL, { usage: { include: true } }),
    system,
    prompt: String(req.input.message ?? ""),
    tools,
    stopWhen: isStepCount(MAX_STEPS),
    abortSignal: AbortSignal.timeout(req.deadline_ms ?? 60_000),
    onStepEnd: (step) => rec.emit("model_call", null, { model: MODEL, finish_reason: step.finishReason }),
  });

  const cost = result.steps.reduce<number | null>(
    (sum, s) => {
      const c = (s.providerMetadata?.openrouter as any)?.usage?.cost;
      return typeof c === "number" ? (sum ?? 0) + c : sum;
    },
    null,
  );
  rec.usage = {
    steps: result.steps.length,
    input_tokens: result.usage.inputTokens ?? null,
    output_tokens: result.usage.outputTokens ?? null,
    cost_usd: cost,
  };
  return result.text;
}

serve(
  {
    adapter_id: `vercel-${PROMPT}-${slug(MODEL)}`,
    language: "typescript",
    framework: "vercel-ai-sdk",
    capabilities: { observe: "native_events", intercept_tools: "declared_only" },
  },
  handle,
  Number(process.env.PORT ?? 7301),
);
