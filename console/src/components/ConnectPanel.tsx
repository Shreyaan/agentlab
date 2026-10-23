import { useState } from "react";
import { Card, SectionTitle, btn } from "./ui";

type Mode = "native" | "http" | "otel";

const FIXTURE_NOTE =
  "Your agent calls the environment at req.environment.base_url (native) or the static fixture URL http://127.0.0.1:8900/env/shared (http).";

const SNIPPETS: Record<string, { label: string; mode: Mode; lang: string; note: string; code: string }> = {
  python: {
    label: "Python adapter",
    mode: "native",
    lang: "python",
    note: `Wrap each tool call in Recorder.tool so events and harness faults apply. ${FIXTURE_NOTE}`,
    code: `from agentlab.adapter import Recorder, serve
from agentlab.protocol import Capabilities, InvokeRequest, Manifest


def handle(req: InvokeRequest, rec: Recorder) -> str:
    base = req.environment.base_url
    order = rec.tool("get_order", lambda: http.get(f"{base}/orders/ORD-1").json())
    rec.usage.cost_usd = 0.002
    return "done"  # becomes the output; raising marks the run failed


manifest = Manifest(
    adapter_id="my-agent",
    language="python",
    capabilities=Capabilities(observe="native_events", intercept_tools="declared_only"),
)
serve(manifest, handle, port=7401)
# Then add a native target with url http://127.0.0.1:7401`,
  },
  typescript: {
    label: "TypeScript adapter",
    mode: "native",
    lang: "typescript",
    note: `Uses packages/adapter-ts/agentlab.ts (Bun). ${FIXTURE_NOTE}`,
    code: `import { serve, type InvokeRequest, type Recorder } from "./packages/adapter-ts/agentlab.ts";

async function handle(req: InvokeRequest, rec: Recorder): Promise<string> {
  const base = req.environment.base_url;
  await rec.tool("get_order", async () => (await fetch(\`\${base}/orders/ORD-1\`)).json());
  return "done"; // becomes the output; throwing marks the run failed
}

serve(
  {
    adapter_id: "my-agent",
    language: "typescript",
    capabilities: { observe: "native_events", intercept_tools: "declared_only" },
  },
  handle,
  7401,
);
// Then add a native target with url http://127.0.0.1:7401`,
  },
  http: {
    label: "Raw HTTP",
    mode: "http",
    lang: "http",
    note: `No AgentLab code. AgentLab POSTs the scenario input as the JSON body; any 2xx JSON or text body is the output, a non-2xx response is a failed run. No events, so event_present checks are unsupported. ${FIXTURE_NOTE}`,
    code: `POST /chat HTTP/1.1
Content-Type: application/json

{"message": "Please refund order ORD-014"}

HTTP/1.1 200 OK
Content-Type: application/json

{"reply": "Refund issued."}

# Add an http target with url http://127.0.0.1:7601/chat and a declared manifest.`,
  },
  otel: {
    label: "OpenTelemetry",
    mode: "otel",
    lang: "yaml",
    note: "Observe-only: AgentLab reads traces your agent already emits and cannot run it. Use it to grade production-like runs.",
    code: `# targets.yaml
targets:
  otel-only: {mode: otel}`,
  },
};

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    void navigator.clipboard.writeText(text).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      },
      () => setCopied(false),
    );
  };
  return (
    <button type="button" className={btn} onClick={copy}>
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

export function ConnectPanel() {
  const [active, setActive] = useState<keyof typeof SNIPPETS>("python");
  const snippet = SNIPPETS[active]!;
  return (
    <Card className="mt-6 p-4">
      <SectionTitle aside={<CopyButton text={snippet.code} />}>Connect your agent</SectionTitle>
      <div role="tablist" aria-label="Integration mode" className="mb-3 flex flex-wrap gap-1">
        {Object.entries(SNIPPETS).map(([key, s]) => (
          <button
            key={key}
            role="tab"
            aria-selected={key === active}
            onClick={() => setActive(key)}
            className={`rounded-md px-2.5 py-1 ${key === active ? "bg-sunken font-medium text-ink" : "text-ink2 hover:bg-sunken"}`}
          >
            {s.label}
          </button>
        ))}
      </div>
      <p className="mb-2 text-ink2">
        Target mode <code>{snippet.mode}</code>. {snippet.note}
      </p>
      <pre className="overflow-auto rounded-md bg-sunken p-3 whitespace-pre" tabIndex={0}>
        {snippet.code}
      </pre>
    </Card>
  );
}
