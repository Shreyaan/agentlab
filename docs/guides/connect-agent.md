# Connect your agent

AgentLab is language-agnostic. Your agent is a **target**: something AgentLab can send a task to, whose tool calls go through the environment service. There are three integration modes.

| Mode | Target config | You provide | You get |
|---|---|---|---|
| `native` | `url` of an adapter | `GET /manifest` + `POST /invoke` | A per-trial environment, events, harness faults, usage, optionally checkpoint/resume/fork |
| `http` | `url` of any endpoint | An endpoint that takes the scenario `input` JSON, optionally a declared `manifest` | State and ledger checks and fixture faults only. No events. One shared environment, trials run one at a time |
| `otel` | none | An OTLP/JSON trace for `agentlab import-otel` | Observe-only. Cannot be invoked, so it is never a run target |

The fastest path is the Python or TypeScript adapter (below). A black-box HTTP endpoint needs no AgentLab code at all but gives up process evidence.

## Targets file

Targets live in `targets.yaml` (`--targets` to use another file). Only hosts in `allowed_hosts` may receive scenarios, because scenarios mutate state. Anything else fails with `UNSAFE_TARGET`.

```yaml
allowed_hosts: [127.0.0.1, localhost]     # default: 127.0.0.1, localhost, ::1
targets:
  my-agent: {mode: native, url: "http://127.0.0.1:7401", version: "my-agent/v2"}
  my-blackbox:
    mode: http
    url: "http://127.0.0.1:7601/chat"
    manifest: {adapter_id: my-blackbox, language: go}
  otel-only: {mode: otel}
```

`version` (default `unversioned`) is a free-form label recorded with every trial; bump it when you change the agent. You can also add, edit and delete targets on the console's **Targets** page, which rewrites `targets.yaml` (it keeps the leading comment block and drops other comments) and refuses a host that is not in `allowed_hosts`.

## The wire protocol (v0.3)

An adapter is an HTTP server with two routes. JSON Schemas are published with `agentlab schema` (written to `protocol/`); see the [protocol reference](../reference/protocol.md).

### `GET /manifest`

```json
{
  "protocol_version": "0.3",
  "adapter_id": "my-agent",
  "language": "python",
  "framework": "custom",
  "transport": "http_json",
  "capabilities": {"invoke": true, "observe": "native_events", "intercept_tools": "declared_only",
                   "checkpoint": false, "resume": false, "fork": false}
}
```

The runner rejects any `protocol_version` other than `0.3` with `PROTOCOL_VERSION_MISMATCH`.

### `POST /invoke`

Request:

```json
{
  "protocol_version": "0.3",
  "trial_id": "exp_20261023_101500_a1b2c3:my-agent:refund.timeout@6:0",
  "scenario_version": "refund.timeout@6",
  "system_version": "my-agent/v2",
  "environment": {"id": "9f2c1d4e7a6b3c58", "base_url": "http://127.0.0.1:8900/env/9f2c1d4e7a6b3c58"},
  "idempotency_key": "exp_...:invoke",
  "input": {"message": "Please refund order ORD-014"},
  "deadline_ms": 120000,
  "traceparent": "00-<trace>-<span>-01",
  "tool_faults": [],
  "resume_from": null
}
```

| Field | Meaning |
|---|---|
| `trial_id`, `scenario_version`, `system_version`, `idempotency_key` | Identity of the trial and target. `scenario_version` carries the scenario key `id@version` |
| `environment.base_url` | The environment service for this trial. **Every tool call must go through it** |
| `input` | The scenario `input` object |
| `deadline_ms` | Time budget. The protocol default is 60000; the CLI sends `--deadline-ms` (default 120000) |
| `traceparent` | W3C trace context |
| `tool_faults` | Harness-boundary faults `[{tool, when, action}]`. Needs `intercept_tools: declared_only`, otherwise answer 400 `CAPABILITY_UNSUPPORTED` |
| `resume_from` | `{trial_id, checkpoint_id}`: continue a prior run. Needs `resume` |

Response:

```json
{
  "run_id": "5d1c...",
  "status": "completed",
  "output": "Your refund of $49.99 was issued once.",
  "events": [
    {"seq": 1, "type": "run_started"},
    {"seq": 2, "type": "tool_requested", "name": "issue_refund"},
    {"seq": 3, "type": "tool_failed", "name": "issue_refund", "data": {"error": "HTTP 504: ..."}},
    {"seq": 4, "type": "run_completed"}
  ],
  "usage": {"steps": 3, "input_tokens": 1200, "output_tokens": 150, "cost_usd": 0.002}
}
```

- `status` is `completed` or `failed`. `output` is any JSON value (usually the reply text).
- `events` need a **strictly increasing `seq`**. Types: `run_started`, `agent_step`, `model_call`, `tool_requested`, `tool_completed`, `tool_failed`, `approval_requested`, `retry_scheduled`, `checkpoint_saved`, `run_completed`, `run_failed`. A tool event carries the tool in `name`. A fired harness fault is a `tool_failed` with `data: {injected, committed}`. `checkpoint_saved` carries `data.checkpoint_id`.
- `usage` fields are all optional. Budget checks on cost and the cost totals need `cost_usd`.
- Errors are HTTP 400 with `{code, message}`. Codes: `CAPABILITY_UNSUPPORTED`, `PROTOCOL_VERSION_MISMATCH`, `UNSAFE_TARGET`, `ENVIRONMENT_NOT_RESETTABLE`, `ADAPTER_TIMEOUT`, `ADAPTER_ERROR`, `TRACE_INCOMPLETE`. An adapter error is never counted as an agent pass or fail.

## Python adapter

`agentlab.adapter` handles the HTTP server, the protocol checks and the event recorder. You write one function.

```python
import httpx
from agentlab.adapter import Recorder, serve
from agentlab.protocol import Capabilities, InvokeRequest, Manifest


def handle(req: InvokeRequest, rec: Recorder) -> str:
    base = req.environment.base_url

    def call(tool: str, args: dict) -> dict:
        r = httpx.post(f"{base}/tools/{tool}", json=args, timeout=10)
        r.raise_for_status()  # 4xx/5xx raise; a 504 may still have committed
        return r.json()

    # One environment call per tool use, wrapped so events and harness faults apply.
    found = rec.tool("find_prescriptions", lambda: call("find_prescriptions", {"patient_name": "Maria Gonzalez"}))
    rec.usage.cost_usd = 0.002
    return "done"  # becomes `output`; raising marks the run "failed"


manifest = Manifest(
    adapter_id="my-agent",
    language="python",
    capabilities=Capabilities(observe="native_events", intercept_tools="declared_only"),
)
serve(manifest, handle, port=7401)  # host defaults to 127.0.0.1
```

What `Recorder.tool(name, fn)` does:

1. Emits `tool_requested`.
2. If a declared `error_before_commit` fault matches: emits `tool_failed` (`injected`, not committed) and raises `ToolFaultError` **without calling** `fn`.
3. Calls `fn`. If it raises, emits `tool_failed` and re-raises.
4. If a `timeout_after_commit` fault matches: `fn` ran, but it emits `tool_failed` (`injected`, `committed: true`) and raises `ToolFaultError`. The agent never learns the call succeeded.
5. Otherwise emits `tool_completed` and returns the result.

Treat `ToolFaultError` like any tool error. Use `rec.emit(kind, name, **data)` for other events (for example `checkpoint_saved`) and `rec.usage` for tokens and cost. An exception in your handler becomes `status: failed` with a `run_failed` event; the trial is still graded on the state the agent left.

Full agents: `examples/openai_agent/` (plain OpenAI SDK loop), `examples/langgraph_agent/` (LangGraph with checkpoint, resume and fork), `examples/agents_sdk_agent/` (OpenAI Agents SDK over MCP).

## TypeScript adapter (Bun)

`packages/adapter-ts/agentlab.ts` mirrors the Python adapter: `serve(manifest, handler, port)`, `Recorder.tool`, `ToolFaultError`. It binds `HOST` (default `127.0.0.1`).

```ts
import { serve, type InvokeRequest, type Recorder } from "./packages/adapter-ts/agentlab.ts";

async function handle(req: InvokeRequest, rec: Recorder): Promise<string> {
  const base = req.environment.base_url;
  await rec.tool("find_prescriptions", async () => {
    const r = await fetch(`${base}/tools/find_prescriptions`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ patient_name: "Maria Gonzalez" }),
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  });
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
```

See `examples/vercel_agent/` for a real Vercel AI SDK agent.

## Tool discovery

Real agents should not hard-code tools. The environment publishes its catalog and the examples build their tools from it at runtime.

`examples/env_tools.py` (Python) and `examples/env_tools.ts` (TypeScript) do the same three things:

1. `GET {base_url}/tools` returns `{environment, description, tools: [{name, description, parameters}]}`, where `parameters` is a JSON Schema object.
2. They turn each entry into a function tool for the model (`{"type": "function", "function": {name, description, parameters}}`) and add the environment `description` to the system prompt.
3. They execute a model-requested tool as exactly one `POST {base_url}/tools/{name}` inside `rec.tool`, returning failures to the model as `{"error": ...}` so it can react.

Only names from the catalog are callable; the model chooses `name`, so the example code checks it against the catalog first.

## MCP

The same tools are served over MCP (Streamable HTTP, stateless) at `{base_url}/mcp`. An MCP client such as the OpenAI Agents SDK connects with no catalog code:

```python
params = MCPServerStreamableHttpParams(url=f"{base_url}/mcp", timeout=10)
async with MCPServerStreamableHttp(name="environment", params=params, cache_tools_list=True) as server:
    agent = Agent(name="ops-agent", instructions=..., mcp_servers=[server], model=...)
```

MCP calls run through the same executor, so the ledger, fixture faults and idempotency behave exactly as over HTTP. Two consequences:

- MCP calls bypass `Recorder.tool`, so your adapter must emit exactly one tool event per call itself (the example does it from the SDK's run hooks).
- Harness faults cannot be injected, because there is no wrapper to apply them. Declare `intercept_tools: "none"` and use `boundary: fixture` faults, which work for MCP.

## Plain HTTP black box

No AgentLab code. Point a `mode: http` target at an endpoint:

```yaml
my-blackbox:
  mode: http
  url: "http://127.0.0.1:7601/chat"
  manifest: {adapter_id: my-blackbox, language: go}
```

AgentLab `POST`s the scenario `input` JSON as the body. Any 2xx response is the output (parsed JSON, or text if it is not JSON). A non-2xx response, a connection error or a timeout is recorded as a failed run or an `ADAPTER_*` error.

The agent cannot be given a per-trial URL, so it must be configured with the static fixture URL `http://127.0.0.1:8900/env/shared` (or whatever `AGENTLAB_FIXTURE_PORT` / `AGENTLAB_FIXTURE_URL` imply). Consequences:

- **One shared environment**; trials are serialized, one at a time.
- **No events**, so `event_present` checks are `unsupported`. If one is critical, the gate returns `INSUFFICIENT_EVIDENCE` (`examples/http_agent` is the demo of this).
- **No harness faults.** Only `boundary: fixture` faults work. Do not declare `intercept_tools` in the manifest: AgentLab does not send `tool_faults` to a black box, so the claim would silently be false.
- There is no request or response field mapping yet: the endpoint must accept the `input` object as its body.

State and ledger checks are unaffected: the environment observes them without the agent's help.

## Capabilities

Declared in the manifest, they decide which scenarios and checks a target can take part in.

| Capability | Values | What it unlocks |
|---|---|---|
| `invoke` | bool, default `true` | Can be run. `false` targets get `CAPABILITY_UNSUPPORTED` |
| `observe` | `native_events`, `otel_partial`, `none` | Only `native_events` satisfies `event_present` checks; otherwise they are `unsupported` |
| `intercept_tools` | `declared_only`, `none` | The adapter applies `tool_faults` (harness faults). Without it, scenarios with harness faults error. `declared_only` means only tools wrapped in `Recorder.tool` are intercepted |
| `checkpoint` | bool | The adapter emits `checkpoint_saved` events |
| `resume` | bool | The adapter continues from `resume_from` |
| `fork` | bool | With `resume`, the target can be used for `agentlab fork` |

What this does not guarantee: events come from the adapter, so an adapter can under-report them. Ledger and database checks are observed by the environment and do not depend on the adapter.

## Conformance

Check a target speaks the protocol before you run a suite:

```bash
uv run agentlab conformance my-agent my-blackbox
```

For each target it validates the manifest, and if the target is invokable it sends a no-op invoke (`{"message": "hello"}`, against a dummy environment URL) and checks that the response is schema-valid and that event `seq` is strictly increasing. It prints `PASS <name>: <language>/<framework> protocol ... capabilities ...` or `FAIL <name>: <reason>`, and exits `0` if all passed, `1` otherwise.

!!! note
    The no-op invoke runs your agent's real handler once (the environment URL it receives is unreachable, so a typical agent fails fast and reports a failed run, which still conforms). An unknown target name prints `FAIL`.
