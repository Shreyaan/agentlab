# HTTP API

!!! note
    Auto-generated from `agentlab.console.openapi_schema()`, `agentlab.fixture` and `agentlab.mcp_env`; do not edit. Run `uv run python scripts/gen_reference.py`.


## Console API

Served by `agentlab serve` under `/v1`. Request and response model names refer to `components.schemas` in the OpenAPI document (`agentlab openapi`).

**Auth.** When a token is configured (`serve --token` / `AGENTLAB_CONSOLE_TOKEN`) every `/v1` route needs `Authorization: Bearer <token>`.

**CSRF guard.** Every write (POST, PUT, DELETE) also needs the header `X-AgentLab-Request: 1`.

**Hosts.** Requests whose `Host` header is not allow-listed are rejected (DNS-rebinding defence).

| Method | Path | Summary | Request body | Response | Success |
|---|---|---|---|---|---|
| POST | `/v1/author` | Draft a scenario from a description | `AuthorRequest` | `AuthorDraft` | 200 |
| GET | `/v1/environments` | List environments |  | `list[EnvironmentInfo]` | 200 |
| POST | `/v1/environments` | Save an environment | `EnvironmentDraft` | `SavedScenario` | 200 |
| POST | `/v1/environments/validate` | Validate an environment draft | `EnvironmentDraft` | `ScenarioValidation` | 200 |
| GET | `/v1/environments/{key}/builder` | Editor vocabulary for an environment |  | `BuilderInfo` | 200 |
| GET | `/v1/experiments` | List experiments |  | `list[ExperimentSummary]` | 200 |
| POST | `/v1/experiments` | Start an experiment | `RunRequest` | `Accepted` | 202 |
| GET | `/v1/experiments/{exp_id}` | Get an experiment with its trials |  | `ExperimentDetail` | 200 |
| GET | `/v1/experiments/{exp_id}/canaries` | Get an experiment's canary results |  | `list[CanaryResult]` | 200 |
| GET | `/v1/experiments/{exp_id}/report.html` | Download the HTML report |  |  | 200 |
| POST | `/v1/forks` | Fork a trial from a checkpoint | `ForkRequest` | `Accepted` | 202 |
| GET | `/v1/info` | Console info |  | `ConsoleInfo` | 200 |
| GET | `/v1/judges` | Judge track records |  | `list[JudgeStats]` | 200 |
| GET | `/v1/scenarios` | List scenarios |  | `list[ScenarioInfo]` | 200 |
| POST | `/v1/scenarios` | Save a scenario | `ScenarioDraft` | `SavedScenario` | 200 |
| POST | `/v1/scenarios/dry-run` | Dry-run an unsaved scenario | `DryRunRequest` | `Accepted` | 202 |
| POST | `/v1/scenarios/test-query` | Try a SQL check against seed data | `QueryTest` | `QueryResult` | 200 |
| POST | `/v1/scenarios/validate` | Validate a scenario draft | `ScenarioDraft` | `ScenarioValidation` | 200 |
| GET | `/v1/targets` | List targets with health |  | `list[TargetHealth]` | 200 |
| POST | `/v1/targets/test` | Probe a target draft | `TargetDraft` | `TargetHealth` | 200 |
| PUT | `/v1/targets/{name}` | Save a target | `TargetDraft` | `SavedTarget` | 200 |
| DELETE | `/v1/targets/{name}` | Delete a target |  |  | 204 |
| GET | `/v1/trials/{trial_id}` | Get a trial |  | `Trial` | 200 |

### Status codes

| Status | Meaning |
|---|---|
| 400 | Request could not be processed (e.g. invalid authoring input). |
| 401 | Missing or invalid bearer token (only when a token is configured). |
| 403 | Missing `X-AgentLab-Request: 1` header on a write. |
| 404 | Unknown experiment, trial or environment. |
| 409 | Capability unsupported by the target (fork). |
| 422 | Validation failed: bad body, unknown target/scenario, or a name that does not match the path. |
| 502 | Upstream adapter or model failure. |
| 503 | A config file (targets, scenarios, environments) could not be loaded. |

## Agent-facing environment routes

Served by the fixture service (the runner's own port, or `agentlab fixture` standalone). Agents under test use these to act on their per-trial environment; `{env_id}` is the trial's environment id. No bearer token and no `X-AgentLab-Request` header are involved.

| Method | Path | Description |
|---|---|---|
| GET | `/env/{env_id}/tools` | Tool catalog: `{environment, description, tools: [{name, description, parameters}]}` where `parameters` is a JSON Schema object. |
| POST | `/env/{env_id}/tools/{name}` | Call a tool with a JSON object of arguments. The response body and status are the tool's own result. An `Idempotency-Key` header is folded into the `idempotency_key` argument for idempotent tools. |
| POST | `/env/{env_id}/mcp` | The same tools over MCP (Streamable HTTP, stateless, JSON responses). `tools/list` returns the catalog; `tools/call` runs the same executor, so calls reach the ledger, faults and idempotency identically. Tool errors (status >= 400) are returned as MCP `isError` results. |

Standalone mode (`agentlab fixture`) additionally serves `POST /env/{env_id}/admin/reset` and `GET /env/{env_id}/admin/state`; these are never exposed on the runner's server.

### Tool call status codes

Success uses the tool's `success_status` (default 200); rule failures use the rule's own 4xx.

| Status | Meaning |
|---|---|
| 404 | Unknown environment, or unknown tool name. |
| 409 | Idempotency key already used by another tool. |
| 422 | Arguments failed validation against the tool's parameters. |
| 500 | Database error while running the tool. |
| 503 | Environment unavailable (a harness-injected fault, or the database is down). |
| 504 | Upstream timeout (an injected `timeout_after_commit` fault: the effect may have happened). |
