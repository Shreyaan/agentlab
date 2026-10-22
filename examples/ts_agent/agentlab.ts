// Native TS adapter for the AgentLab wire protocol v0.2 (mirrors src/agentlab/adapter.py).
export const PROTOCOL_VERSION = "0.2";

export type Manifest = {
  protocol_version?: string;
  adapter_id: string;
  language: string;
  framework?: string;
  transport?: "http_json";
  capabilities?: {
    invoke?: boolean;
    observe?: "native_events" | "otel_partial" | "none";
    intercept_tools?: "declared_only" | "none";
    checkpoint?: boolean;
    resume?: boolean;
    fork?: boolean;
  };
};

export type EventType =
  | "run_started" | "agent_step" | "model_call" | "tool_requested" | "tool_completed"
  | "tool_failed" | "approval_requested" | "retry_scheduled" | "checkpoint_saved"
  | "run_completed" | "run_failed";

export type Event = {
  seq: number;
  type: EventType;
  name?: string | null;
  ts?: number | null;
  span_id?: string | null;
  parent_id?: string | null;
  data?: Record<string, unknown>;
};

export type InvokeRequest = {
  protocol_version?: string;
  trial_id: string;
  scenario_version: string;
  system_version: string;
  environment: { id: string; base_url: string };
  idempotency_key: string;
  input: Record<string, any>;
  deadline_ms?: number;
  traceparent?: string | null;
};

export type InvokeResponse = {
  run_id: string;
  status: "completed" | "failed";
  output: unknown;
  events: Event[];
  usage?: { steps?: number | null; cost_usd?: number | null };
};

const errorMessage = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** Collects normalized events for one run. Wrap each tool call with `tool()`. */
export class Recorder {
  events: Event[] = [];

  emit(type: EventType, name: string | null = null, data: Record<string, unknown> = {}): void {
    this.events.push({ seq: this.events.length + 1, type, name, ts: Date.now() / 1000, data });
  }

  async tool<T>(name: string, fn: () => Promise<T> | T): Promise<T> {
    this.emit("tool_requested", name);
    try {
      const result = await fn();
      this.emit("tool_completed", name);
      return result;
    } catch (e) {
      this.emit("tool_failed", name, { error: errorMessage(e) });
      throw e;
    }
  }
}

export type Handler = (req: InvokeRequest, rec: Recorder) => Promise<unknown> | unknown;

export function serve(manifest: Manifest, handler: Handler, port: number) {
  return Bun.serve({
    port,
    hostname: process.env.HOST ?? "127.0.0.1",
    async fetch(request) {
      const { pathname } = new URL(request.url);
      if (request.method === "GET" && pathname === "/manifest") return Response.json(manifest);
      if (request.method !== "POST" || pathname !== "/invoke") return new Response("not found", { status: 404 });

      const req = (await request.json()) as InvokeRequest;
      if ((req.protocol_version ?? PROTOCOL_VERSION) !== PROTOCOL_VERSION) {
        return Response.json(
          { code: "PROTOCOL_VERSION_MISMATCH", message: `adapter speaks ${PROTOCOL_VERSION}` },
          { status: 400 },
        );
      }
      const rec = new Recorder();
      rec.emit("run_started");
      let output: unknown;
      let status: InvokeResponse["status"];
      try {
        output = await handler(req, rec);
        status = "completed";
        rec.emit("run_completed");
      } catch (e) { // an agent crash is an agent failure, reported in-band
        output = { error: errorMessage(e) };
        status = "failed";
        rec.emit("run_failed", null, { error: errorMessage(e) });
      }
      const body: InvokeResponse = { run_id: crypto.randomUUID(), status, output, events: rec.events };
      return Response.json(body);
    },
  });
}
