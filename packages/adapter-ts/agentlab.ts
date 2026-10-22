// Native TS adapter for the AgentLab wire protocol v0.3 (mirrors src/agentlab/adapter.py).
export const PROTOCOL_VERSION = "0.3";

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

export type ToolFault = {
  tool: string;
  when?: "first_call" | "always" | number; // number = nth call (1-based)
  action: "timeout_after_commit" | "error_before_commit";
};

export type ResumeFrom = { trial_id: string; checkpoint_id: string };

export type Usage = {
  steps?: number | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  cost_usd?: number | null;
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
  tool_faults?: ToolFault[]; // requires intercept_tools="declared_only"
  resume_from?: ResumeFrom | null;
};

export type InvokeResponse = {
  run_id: string;
  status: "completed" | "failed";
  output: unknown;
  events: Event[];
  usage: Usage;
};

const errorMessage = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** Raised by `Recorder.tool` when a declared harness fault fires. Agents should treat it like any tool error. */
export class ToolFaultError extends Error {}

const firesOn = (f: ToolFault, tool: string, callNumber: number) =>
  f.tool === tool && (f.when === "always" || ((f.when ?? "first_call") === "first_call" && callNumber === 1) || f.when === callNumber);

/** Collects normalized events for one run and applies declared harness faults. Wrap each tool call with `tool()`. */
export class Recorder {
  events: Event[] = [];
  usage: Usage = {};
  private calls = new Map<string, number>();

  constructor(private toolFaults: ToolFault[] = []) {}

  emit(type: EventType, name: string | null = null, data: Record<string, unknown> = {}): void {
    this.events.push({ seq: this.events.length + 1, type, name, ts: Date.now() / 1000, data });
  }

  async tool<T>(name: string, fn: () => Promise<T> | T): Promise<T> {
    const callNumber = (this.calls.get(name) ?? 0) + 1;
    this.calls.set(name, callNumber);
    const fault = this.toolFaults.find((f) => firesOn(f, name, callNumber));
    this.emit("tool_requested", name);
    if (fault?.action === "error_before_commit") {
      this.emit("tool_failed", name, { error: "injected error", injected: true, committed: false });
      throw new ToolFaultError(`${name}: service unavailable (injected)`);
    }
    let result: T;
    try {
      result = await fn();
    } catch (e) {
      this.emit("tool_failed", name, { error: errorMessage(e) });
      throw e;
    }
    if (fault) { // timeout_after_commit: the call went through, the agent never learns it
      this.emit("tool_failed", name, { error: "injected timeout", injected: true, committed: true });
      throw new ToolFaultError(`${name}: upstream timeout (injected)`);
    }
    this.emit("tool_completed", name);
    return result;
  }
}

export type Handler = (req: InvokeRequest, rec: Recorder) => Promise<unknown> | unknown;

const unsupported = (message: string) =>
  Response.json({ code: "CAPABILITY_UNSUPPORTED", message }, { status: 400 });

export function serve(manifest: Manifest, handler: Handler, port: number) {
  const caps = manifest.capabilities ?? {};
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
      if (req.tool_faults?.length && (caps.intercept_tools ?? "none") === "none") {
        return unsupported("adapter does not intercept tools");
      }
      if (req.resume_from && !caps.resume) return unsupported("adapter cannot resume from checkpoints");
      const rec = new Recorder(req.tool_faults);
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
      const body: InvokeResponse = { run_id: crypto.randomUUID(), status, output, events: rec.events, usage: rec.usage };
      return Response.json(body);
    },
  });
}
