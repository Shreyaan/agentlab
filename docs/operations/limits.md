# Known limits

What AgentLab does not do today, so you can plan around it. Each item is a property of the current code.

## What a result means

- **LLM results are stochastic.** Use `--repeats` and read the confidence intervals; a single run proves little. Six clean trials cannot show a pass rate above 61% with 95% confidence (see [The release gate](../concepts/gate.md#wilson-intervals)).
- **An offline gate is evidence, not proof** of production safety. It covers the scenarios you wrote.
- **A critical model-judged failure cannot block until its judges are calibrated.** A fresh database has no calibration history, so such failures report `INSUFFICIENT_EVIDENCE` until a judge has 20+ evidence-reading samples and 10+ canaries, each at 90%+ accuracy. SQL checks block immediately.
- **The default judges use an alpha API.** The OpenRouter Decisions endpoint is `/api/alpha/decisions`.
- **The injection evidence is small.** One live test with one injection string showed the default decision models resisting; a chat model followed it. It is not a proof of robustness.
- **Events come from the adapter.** An adapter can under-report them. Ledger and database checks are observed by the environment and do not depend on the adapter. `declared_only` interception covers only tools wrapped in `Recorder.tool`.
- **`risk_tier` is a label.** It does not change grading or the gate.

## Environments

- **Postgres only, one SQL statement per tool.** Tools cannot call external services or run multi-step logic outside a single statement (use CTEs). Tool SQL has a 5 second timeout.
- **Fixed column and parameter types.** Columns: `text`, `integer`, `bigint`, `numeric`, `boolean`, `timestamptz`, `jsonb`. Parameters: `string`, `integer`, `number`, `boolean`.
- **Seeds are table rows.** The ledger and idempotency tables are owned by the runtime.
- **Only two fault actions:** `timeout_after_commit` and `error_before_commit`, selected by tool and call number (`first_call`, `always`, nth). There is no latency injection, response corruption, or fault selection by argument value.
- **Tool calls within a trial are serialized**, so the ledger order is exact. An agent that issues parallel tool calls sees them run one at a time.
- **Saved versions are not kept on disk.** Saving a changed scenario or environment in the console rewrites the file with the next version number. Older definitions survive in git and inside the experiments that ran them. Two files with the same `id@version` are an error.
- **Fork restore replays committed calls**, so it reproduces state exactly only when the tool SQL is deterministic (serial ids are; clock or random values are not).

## Integration

- **Generic `http` targets** have no request or response field mapping (the endpoint must accept the scenario `input` object as its body), no events (so `event_present` checks are `unsupported`), no harness faults, and share one environment, so their trials run one at a time.
- **Fork needs cooperating adapters:** `checkpoint_saved` events, exactly one tool event per environment call, and `resume`. The LangGraph example keeps checkpoints in an in-memory saver, so the agent process must stay up between the original run and the fork.
- **MCP agents bypass `Recorder.tool`.** Their adapter must emit tool events itself, and harness faults cannot be injected (use fixture faults).
- **`otel` is observe-only.** `agentlab import-otel` prints normalized events from a trace; an `otel` target cannot be invoked, so it is never a run target.
- **The protocol version must match exactly** (`0.3`).

## Console and operations

- **Auth is a single shared bearer token.** No users, roles or audit log. There is **no TLS**.
- **The environment service has no authentication.** Keep it on localhost.
- **The console writes files on the server:** scenarios, environments and `targets.yaml`. Writes are atomic but there is no edit history.
- **Jobs run inside the server process**, at most 2 experiments at a time. If the process dies mid-run, the experiment shows `incomplete`, its unfinished trials stay `running`, and nothing resumes it.
- **A hard kill can leave `env_*` schemas and `agentlab_*` roles in Postgres.** They are dropped after each trial in normal operation.
- **The console accepts 1 to 20 repeats** per run; the CLI accepts any value of at least 1.
- **The Compose console is for browsing results** as shipped: it publishes only port 8800, receives no `OPENROUTER_API_KEY`, and keeps saved files inside the container.
- **AgentLab's database user must be able to create schemas and roles.**
- **Plain-English authoring is only as good as its model.** It validates that SQL runs and names exist, up to 3 attempts, not that the checks are meaningful. Review every draft.

## Project status

- **Market fit is unvalidated.**
- **The name "AgentLab" is used by other projects;** it may need to change.
