# AgentLab

AgentLab tests what an AI agent does to its environment, not just how its reply reads. After each run it checks the final state of the environment (rows written, duplicate side effects, approvals obtained), the side-effect ledger (which tools were called, and whether they succeeded), and the agent's reported events and output. It then gates a release as `PASS`, `BLOCK`, or `INSUFFICIENT_EVIDENCE`. The control plane is Python (uv); agents can be written in any language that speaks the wire protocol or is reachable over HTTP.

## Quickstart

Requires uv, Python 3.13 (uv installs it from `.python-version`), and bun for the demo agents.

```bash
uv sync
./scripts/demo.sh
```

The demo starts five reference agents and runs three gates against the same refund scenarios. Expected results:

| Run | Result | Exit |
|---|---|---|
| `ts-fixed` vs baseline `ts-buggy` | `PASS` | 0 |
| `py-buggy` | `BLOCK` (duplicate refund, issued without approval) | 1 |
| `http-fixed` (black box, no events) | `INSUFFICIENT_EVIDENCE` | 2 |

Each run writes an HTML report to `.agentlab/reports/<experiment>.html`.

## Concepts

**Harness vs environment.** The harness is the agent under test. It can be any language, and it is reached over the wire protocol or plain HTTP. The environment is the fixture: a resettable refund service backed by SQLite, with a side-effect ledger and scripted faults. The runner resets the fixture before every trial and gives each target the same initial state for a given scenario and repeat. The agent must call the fixture's `base_url` for its tool calls, so the fixture's state and ledger are the ground truth. Assertions are graded in this order: environment state, then process (ledger and events), then output text.

**Integration modes** (`mode` in `targets.yaml`):

| Mode | Runner gets | Guarantees | Does not guarantee |
|---|---|---|---|
| `native` | Manifest, events, output, usage | Full grading: state, ledger, events, output, budget | Events are self-reported by the adapter. `event_present` proves what the adapter claims, not what it did. Tool calls are not intercepted; faults are injected at the fixture boundary only. |
| `http` | Output text and the fixture's state and ledger | Works with any agent that has an HTTP endpoint | No events, so `event_present` checks are unsupported. A critical unsupported check gives `INSUFFICIENT_EVIDENCE`. The manifest must be declared in `targets.yaml`. |
| `otel` | Nothing invokable | Observe-only; `agentlab import-otel` normalizes an OTLP/JSON trace | Cannot be invoked, so it cannot be gated. Trials against it end in `CAPABILITY_UNSUPPORTED`. |

**Flagship scenario: `refund_timeout`** (`scenarios/refund_timeout.yaml`). The payment service commits the refund, but the caller receives `504 upstream timeout`. A buggy agent retries without an idempotency key and issues a second refund. A fixed agent sends an `Idempotency-Key`, so the fixture returns the prior refund. The critical assertion is `exactly one refund for ORD-014`. The scenario also requires approval before the refund, forbids `delete_customer`, requires the agent to report the failed call, and sets a budget of 12 tool calls and 30 s.

## Connect your agent

### Native protocol (any language)

Implement two endpoints, both JSON, protocol version `0.2`:

- `GET /manifest` returns a `Manifest`: `protocol_version`, `adapter_id`, `language`, `framework`, `transport: "http_json"`, and `capabilities` (`invoke`, `observe: native_events | otel_partial | none`, `intercept_tools`, `checkpoint`, `resume`, `fork`).
- `POST /invoke` takes an `InvokeRequest`: `protocol_version`, `trial_id`, `scenario_version`, `system_version`, `environment: {id, base_url}`, `idempotency_key`, `input`, `deadline_ms`, `traceparent`. It returns an `InvokeResponse`: `run_id`, `status` (`completed | failed`), `output`, `events[]`, `usage` (`steps`, `cost_usd`).

Each event has `seq`, `type`, `name`, `ts`, `span_id`, `parent_id`, and `data`. Types: `run_started`, `agent_step`, `model_call`, `tool_requested`, `tool_completed`, `tool_failed`, `approval_requested`, `retry_scheduled`, `checkpoint_saved`, `run_completed`, `run_failed`. Use `seq` for ordering, not `ts`.

On a protocol version mismatch, return HTTP 400 with `{"code": "PROTOCOL_VERSION_MISMATCH", "message": "..."}`. The JSON Schemas are in `protocol/`. Regenerate them with `uv run agentlab schema --out protocol`.

### Python adapter

```python
from agentlab.adapter import Recorder, serve
from agentlab.protocol import Capabilities, InvokeRequest, Manifest

def handle(req: InvokeRequest, rec: Recorder) -> str:
    order = rec.tool("get_order", lambda: fetch_order(req.environment.base_url, "ORD-1"))
    return f"found {order['id']}"

serve(Manifest(adapter_id="my-agent", language="python",
               capabilities=Capabilities(observe="native_events")), handle, port=7102)
```

`rec.tool(name, fn)` emits `tool_requested`, then `tool_completed` or `tool_failed`. Use `rec.emit(type, name, **data)` for other events. `serve` binds to `127.0.0.1` by default. See `examples/python_agent/agent.py`.

### TypeScript adapter (Bun)

Copy `examples/ts_agent/agentlab.ts` into your project and import `serve` and `Recorder`. It mirrors the Python adapter: `rec.tool(name, async () => ...)` and `rec.emit(...)`. It binds to `HOST` (default `127.0.0.1`). See `examples/ts_agent/agent.ts`.

### Generic HTTP (black box)

```yaml
http-fixed:
  mode: http
  url: "http://127.0.0.1:7201/chat"
  version: http-v2
  manifest: {adapter_id: http-blackbox, language: typescript}
```

The runner POSTs the scenario `input` JSON as-is, with no field mapping. Any 2xx response is the output: JSON if it parses, otherwise text. A non-2xx response is recorded as a failed run with the HTTP status and body. The agent gets the fixture URL from its own configuration. The runner does not pass it. See `examples/http_agent/agent.ts`.

### Conformance

```bash
uv run agentlab conformance ts-fixed py-fixed http-fixed
```

For each target, this checks that the manifest validates and that a no-op invoke returns a valid response with strictly increasing event `seq`. It exits 1 if any target fails.

## Writing scenarios

A scenario is one YAML file in `scenarios/`:

```yaml
id: refund.happy            # scenario identity
version: 1                  # bump when assertions change; the key is id@version
risk_tier: normal           # critical | high | normal
source: synthetic           # free text, for provenance
slices: [refund]            # free-form tags
fixture:
  customers: [{id: C-2, name: Grace Hopper}]
  orders: [{id: ORD-021, customer_id: C-2, amount_cents: 1250}]
  approval_limit_cents: 50000   # approvals above this are denied (default 50000)
input:                      # sent to the agent as-is (native: in InvokeRequest.input)
  message: "Can I get a refund for ORD-021?"
faults:                     # optional
  - {tool: issue_refund, when: first_call, action: timeout_after_commit}
assertions:
  - type: sql
    description: one refund for the full order amount   # optional label
    query: "SELECT COUNT(*) FROM refunds WHERE order_id = 'ORD-021' AND amount_cents = 1250"
    equals: 1
    critical: true          # a failed critical check blocks the release
  - type: output_matches
    pattern: "refund"       # case-insensitive regex on the output text
budget:
  max_tool_calls: 6
  max_latency_ms: 30000
  max_cost_usd: 0.50        # needs usage.cost_usd from the adapter, else unsupported
```

Assertion types:

| Type | Fields | Passes when |
|---|---|---|
| `sql` | `query`, `equals` | Read-only query over final state returns `equals`. A single cell is compared as a scalar, otherwise rows are compared. |
| `tool_order` | `before`, `requires` | `requires` succeeds (2xx) in the ledger before the first `before` call, or `before` is never called. |
| `forbidden_tool` | `name` | The tool is never called. |
| `event_present` | `event`, `name?` | The adapter reports the event (native mode only; otherwise unsupported). |
| `output_matches` | `pattern` | The output text matches the regex. |

Every assertion accepts `critical` and `description`. A trial fails if any assertion fails, including non-critical ones. Budget checks are non-critical.

Faults (`faults:`) are injected at the fixture boundary:

- `tool`: the fixture endpoint name, such as `issue_refund`, `request_approval`, `get_order`, or `delete_customer`.
- `when`: `first_call`, `always`, or `n` (an integer, 1-based call count).
- `action`: `timeout_after_commit` (the write happens, but the caller gets 504) or `error_before_commit` (the caller gets 503 and nothing is written).

## CLI reference

```bash
uv run agentlab test scenarios --candidate ts-fixed --baseline ts-buggy --repeats 3
```

| Command | Key flags | Purpose |
|---|---|---|
| `test <suite>` | `--candidate` (required), `--baseline`, `--repeats N`, `--max-regression 0-1`, `--deadline-ms`, `--targets`, `--fixture-port` (8900), `--fixture-bind` (127.0.0.1), `--fixture-url`, `--db`, `--report-dir` | Run a suite, gate the candidate, write an HTML report |
| `conformance <names...>` | `--targets` | Check that targets speak the protocol |
| `fixture` | `--port` (8900), `--bind` | Serve the reference refund environment standalone (`POST /admin/reset`, `GET /admin/state`) |
| `schema` | `--out` (protocol) | Write protocol JSON Schemas |
| `import-otel <file>` | | Normalize an OTLP/JSON trace to events and print JSON (observe-only) |

Exit codes for `test`: `0` PASS, `1` BLOCK, `2` INSUFFICIENT_EVIDENCE, `3` config or usage error (unknown target, invalid YAML, missing file). Usage errors (missing flag, `--repeats 0`) also exit `3`. An assertion that crashes (for example, SQL that tries to write) is recorded as `unsupported` with `grader error: ...`; on a critical check that yields INSUFFICIENT_EVIDENCE, never a pass or a block.

GitHub Actions gate (start your agent in an earlier step):

```yaml
- uses: actions/checkout@v4
- uses: astral-sh/setup-uv@v6
- run: uv run agentlab test scenarios --candidate my-agent --targets targets.yaml
```

Any non-zero exit fails the job, so only `PASS` (0) lets the release through.

## Docker

Use Docker if you don't want Python installed locally. The image has the CLI, the reference fixture, and the default `scenarios/` and `targets.yaml`.

```bash
docker build -t agentlab .
docker run --rm agentlab --help
```

The baked-in `targets.yaml` points at `127.0.0.1`, which is the container itself inside Docker. To run a suite, use the host-agent setup below.

The container runs as uid 10001. Anything it writes under `/app/.agentlab` (the database and reports) must be writable by that uid, or you should point `--db` and `--report-dir` at a writable mount.

To test agents on your host, bind the fixture to all interfaces and give the container a URL that reaches your host:

```bash
docker run --rm \
  -v "$PWD/targets.yaml:/app/targets.yaml" \
  agentlab test scenarios --candidate ts-fixed --targets targets.yaml \
  --fixture-bind 0.0.0.0 --fixture-url http://host.docker.internal:8900
```

Agents on the host must:

- Bind to `0.0.0.0`. The Python adapter takes `serve(..., host="0.0.0.0")`. All reference agents read `HOST` (default `127.0.0.1`); set `HOST=0.0.0.0`.
- Be listed in `targets.yaml` as `http://host.docker.internal:<port>`, and `host.docker.internal` must be in `allowed_hosts`. On Linux, add `--add-host=host.docker.internal:host-gateway`.

Binding to `0.0.0.0` exposes the fixture and your agents to the local network. Use this only on a trusted network.

## Gate rules

From `src/agentlab/gate.py`. Only candidate trials count toward these rules. Baseline trials affect stats and pairing only.

1. **BLOCK** if any candidate trial has a failed critical check. Also BLOCK if a baseline is given, the candidate pass rate is below the baseline pass rate minus `--max-regression`, and at least one paired trial regressed (passed in the baseline, failed in the candidate).
2. Otherwise **INSUFFICIENT_EVIDENCE** if any of these hold:
   - A candidate trial did not complete (adapter error, timeout, unsafe target, or a trial that never finished grading). Such trials are excluded from pass rates.
   - A scenario has no graded candidate trial.
   - A critical check is unsupported by the harness (for example, `event_present` against a black-box target).
3. Otherwise **PASS**.

Non-critical unsupported checks are listed as coverage gaps and do not change the decision.

## Safety

- **Allowed hosts.** Each target's host must be in `allowed_hosts` in `targets.yaml`. The default is `127.0.0.1`, `localhost`, and `::1`. A target outside the list is recorded as `UNSAFE_TARGET` and its trials do not complete. This leads to `INSUFFICIENT_EVIDENCE`, not a pass.
- **Read-only assertions.** `sql` assertions run with `PRAGMA query_only = ON`, so writes are rejected. See the exit-code caveat above.
- **Redaction.** Output, events, and ledger entries are redacted before they are stored. Keys matching `secret`, `token`, `password`, `authorization`, or `api_key` are replaced with `[REDACTED]`. Grading uses the unredacted values.
- **Errors are not passes.** Adapter failures and timeouts are stored as errors and excluded from pass rates. They lead to `INSUFFICIENT_EVIDENCE`.

## Current limits

- One in-memory fixture, so trials run sequentially.
- Only the reference refund fixture exists.
- No in-harness tool interception. Faults are injected at the fixture boundary only.
- No checkpoint or replay.
- The reference agents are deterministic stand-ins, not LLMs.
- The only UI is the static HTML report. There is no web console.
- Generic HTTP targets have no field mapping.
- The Node CLI is not built. Use Docker instead.

## Testing

```bash
uv run pytest
```
