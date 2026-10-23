// Real LLM agent: Vercel AI SDK, tools discovered from the environment catalog, + OpenRouter, served through the AgentLab TS adapter.
// PROMPT=naive|careful (default careful) picks examples/prompts/<PROMPT>.md; MODEL is an OpenRouter model id.
import { createOpenRouter } from "@openrouter/ai-sdk-provider";
import { dynamicTool, generateText, isStepCount, jsonSchema } from "ai";
import { errorAsResult, loadCatalog, postTool, systemPrompt, type Catalog } from "../env_tools.ts";
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

const openrouter = createOpenRouter({ apiKey });

/** AI SDK dynamic tools built from the catalog's JSON Schemas: one POST per call, inside `rec.tool`. */
function catalogTools(baseUrl: string, catalog: Catalog, rec: Recorder) {
  return Object.fromEntries(
    catalog.tools.map((t) => [
      t.name,
      dynamicTool({
        description: t.description,
        inputSchema: jsonSchema(t.parameters),
        execute: (args) => errorAsResult(() => rec.tool(t.name, () => postTool(baseUrl, t.name, args))),
      }),
    ]),
  );
}

async function handle(req: InvokeRequest, rec: Recorder): Promise<string> {
  const catalog = await loadCatalog(req.environment.base_url);
  const tools = catalogTools(req.environment.base_url, catalog, rec);
  const result = await generateText({
    model: openrouter(MODEL, { usage: { include: true } }),
    system: await systemPrompt(PROMPT, catalog),
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
