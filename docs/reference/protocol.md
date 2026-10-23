# BYOH wire protocol v0.3

!!! note
    Auto-generated from `agentlab.protocol` (pydantic models and `json_schemas()`); do not edit. Run `uv run python scripts/gen_reference.py`.


The language-neutral contract between the runner and any harness. Schemas are also written by `agentlab schema`.

## Models

### Manifest

A harness's self-description, returned by `GET /manifest`.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `protocol_version` | `str` | no | `"0.3"` | Wire protocol version the harness speaks; a mismatch is refused. |
| `adapter_id` | `str` | yes |  | Stable identifier of this adapter, e.g. `acme-support-bot`. |
| `language` | `str` | yes |  | Language the harness is written in, e.g. `python` or `typescript`. |
| `framework` | `str` | no | `"custom"` | Agent framework in use, e.g. `langgraph`; `custom` if none. |
| `transport` | `"http_json"` | no | `"http_json"` | Wire transport; only HTTP+JSON exists. |
| `capabilities` | `Capabilities` | no | `{"invoke": true, "observe": "none", "intercept_tools": "none", "checkpoint": false, "resume": false, "fork": false}` | Optional features the harness supports. |

### Capabilities

What a harness can do beyond plain invoke; the runner skips or marks checks the harness cannot support.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `invoke` | `bool` | no | `true` | Accepts `POST /invoke`. Always true for a working harness. |
| `observe` | `"native_events" \| "otel_partial" \| "none"` | no | `"none"` | How much of the run the harness reveals: `native_events` streams the full event list in the response, `otel_partial` exports OpenTelemetry spans only, `none` is a black box. |
| `intercept_tools` | `"declared_only" \| "none"` | no | `"none"` | `declared_only` means the harness applies the `tool_faults` it receives at its own tool boundary; `none` means it ignores them. |
| `checkpoint` | `bool` | no | `false` | Emits `checkpoint_saved` events that a run can be resumed from. |
| `resume` | `bool` | no | `false` | Can continue a prior trial from a checkpoint (`resume_from`). |
| `fork` | `bool` | no | `false` | Can branch a prior trial's checkpoint into a new run (`resume_from`). |

### InvokeRequest

Body of `POST /invoke`: one trial for the harness to run.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `protocol_version` | `str` | no | `"0.3"` | Wire protocol version of the sender. |
| `trial_id` | `str` | yes |  | Unique id of this trial (one scenario, one repeat, one target). |
| `scenario_version` | `str` | yes |  | Scenario `id@version` being run. |
| `system_version` | `str` | yes |  | Version label of the system under test, from the target config. |
| `environment` | `Environment` | yes |  | Where the agent's tools live. |
| `idempotency_key` | `str` | yes |  | Stable key for this invocation (`<trial_id>:invoke`), so a harness can de-duplicate a retried request. |
| `input` | `dict[str, JSON]` | yes |  | The scenario's `input`, handed to the agent as-is. |
| `deadline_ms` | `int` | no | `60000` | Time budget for the whole invocation, in milliseconds. |
| `traceparent` | `str \| null` | no | `null` | W3C `traceparent` header value, so the harness can join the runner's trace. |
| `tool_faults` | `list[ToolFault]` | no | `[]` | Faults the harness must apply at its own tool boundary; sent only to `intercept_tools="declared_only"`. |
| `resume_from` | `ResumeFrom \| null` | no | `null` | Checkpoint to continue from, for resume/fork runs. |

### Environment

The fixture environment a trial runs against.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `id` | `str` | yes |  | Environment `id@version` key, e.g. `refund@2`. |
| `base_url` | `str` | yes |  | Fixture service URL the agent must use for every tool call. |

### ToolFault

A scripted tool failure. Applied by the fixture service, or by the harness when sent in `tool_faults`.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `tool` | `str` | yes |  | Name of the tool to break. |
| `when` | `"first_call" \| "always" \| int` | no | `"first_call"` | Which calls fail: `first_call`, `always`, or an integer N for the Nth call (1-based). |
| `action` | `"timeout_after_commit" \| "error_before_commit"` | yes |  | `timeout_after_commit`: the side effect happens but the caller sees a failure. `error_before_commit`: the call fails with no side effect. |

### ResumeFrom

Continue a prior run from one of its checkpoints. Only for adapters declaring resume/fork.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `trial_id` | `str` | yes |  | Trial whose run to continue. |
| `checkpoint_id` | `str` | yes |  | `checkpoint_id` from one of that trial's `checkpoint_saved` events. |

### InvokeResponse

Body returned by `POST /invoke`.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `run_id` | `str` | yes |  | Harness-side identifier of this run. |
| `status` | `"completed" \| "failed"` | yes |  | Whether the agent finished its run; this is not a grading result. |
| `output` | `JSON` | no | `null` | The agent's final answer, in any JSON shape. |
| `events` | `list[Event]` | no | `[]` | Ordered steps the agent took, if `observe` allows. |
| `usage` | `Usage` | no | `{"steps": null, "input_tokens": null, "output_tokens": null, "cost_usd": null}` | Resources used by the run. |

### Event

One step the harness reports about its own run (only when `observe` is `native_events`).

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `seq` | `int` | yes |  | Position in the run, starting at 1. Ordering always uses `seq`, never `ts`. |
| `type` | `"run_started" \| "agent_step" \| "model_call" \| "tool_requested" \| "tool_completed" \| "tool_failed" \| "approval_requested" \| "retry_scheduled" \| "checkpoint_saved" \| "run_completed" \| "run_failed"` | yes |  | What happened, e.g. `tool_requested` or `model_call`. |
| `name` | `str \| null` | no | `null` | Tool name, for `tool_*` events. |
| `ts` | `float \| null` | no | `null` | Unix time in seconds; informational, clocks differ across runtimes. |
| `span_id` | `str \| null` | no | `null` | Identifier of this step, for correlating with traces. |
| `parent_id` | `str \| null` | no | `null` | `span_id` of the step that caused this one. |
| `data` | `dict[str, JSON]` | no | `{}` | Event payload. `tool_failed`: `{"injected": bool, "committed": bool}` when a fault fired. `checkpoint_saved`: `{"checkpoint_id": str}`. |

### Usage

Resource use the harness reports for a run; omitted values are unknown, not zero.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `steps` | `int \| null` | no | `null` | Agent steps taken. |
| `input_tokens` | `int \| null` | no | `null` | Prompt tokens consumed across all model calls. |
| `output_tokens` | `int \| null` | no | `null` | Completion tokens produced across all model calls. |
| `cost_usd` | `float \| null` | no | `null` | Total model spend in US dollars. |

### ErrorBody

Error body a harness returns on a non-2xx response.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `code` | `ErrorCode` | yes |  | Machine-readable failure category. |
| `message` | `str` | yes |  | Human-readable explanation; must not contain secrets. |

## Event types

- `run_started`
- `agent_step`
- `model_call`
- `tool_requested`
- `tool_completed`
- `tool_failed`
- `approval_requested`
- `retry_scheduled`
- `checkpoint_saved`
- `run_completed`
- `run_failed`

## Error codes

An `ErrorBody` is returned with HTTP status 400.

- `CAPABILITY_UNSUPPORTED`
- `PROTOCOL_VERSION_MISMATCH`
- `UNSAFE_TARGET`
- `ENVIRONMENT_NOT_RESETTABLE`
- `ADAPTER_TIMEOUT`
- `ADAPTER_ERROR`
- `TRACE_INCOMPLETE`

## Invariants

- **Event ordering.** Events are ordered by `seq` (1-based, strictly increasing within a run). `ts` is informational and never used to order events across runtimes.
- **One tool event per environment call.** Each call to the environment emits `tool_requested`, then exactly one of `tool_completed` or `tool_failed`. Fork/resume maps checkpoints to ledger positions by counting these terminal events.
- **Injected failures.** A `tool_failed` event with `data.committed = false` marks a harness-injected failure that never reached the environment; it is not counted as an environment call. `data.injected = true` marks any harness-injected fault; `timeout_after_commit` faults report `committed = true`.
- **Checkpoints.** `checkpoint_saved` carries `data.checkpoint_id`.
- **Adapter failures are never agent results.** Infrastructure errors use `ErrorBody` codes.

## JSON Schemas

??? abstract "ErrorBody JSON Schema"

    ```json
    {
      "$defs": {
        "ErrorCode": {
          "enum": [
            "CAPABILITY_UNSUPPORTED",
            "PROTOCOL_VERSION_MISMATCH",
            "UNSAFE_TARGET",
            "ENVIRONMENT_NOT_RESETTABLE",
            "ADAPTER_TIMEOUT",
            "ADAPTER_ERROR",
            "TRACE_INCOMPLETE"
          ],
          "title": "ErrorCode",
          "type": "string"
        }
      },
      "description": "Error body a harness returns on a non-2xx response.",
      "properties": {
        "code": {
          "$ref": "#/$defs/ErrorCode",
          "description": "Machine-readable failure category."
        },
        "message": {
          "description": "Human-readable explanation; must not contain secrets.",
          "title": "Message",
          "type": "string"
        }
      },
      "required": [
        "code",
        "message"
      ],
      "title": "ErrorBody",
      "type": "object"
    }
    ```


??? abstract "Event JSON Schema"

    ```json
    {
      "$defs": {
        "EventType": {
          "enum": [
            "run_started",
            "agent_step",
            "model_call",
            "tool_requested",
            "tool_completed",
            "tool_failed",
            "approval_requested",
            "retry_scheduled",
            "checkpoint_saved",
            "run_completed",
            "run_failed"
          ],
          "type": "string"
        },
        "JsonObject": {
          "additionalProperties": {
            "$ref": "#/$defs/JsonValue"
          },
          "type": "object"
        },
        "JsonValue": {}
      },
      "description": "One step the harness reports about its own run (only when `observe` is `native_events`).",
      "properties": {
        "data": {
          "$ref": "#/$defs/JsonObject",
          "default": {},
          "description": "Event payload. `tool_failed`: `{\"injected\": bool, \"committed\": bool}` when a fault fired. `checkpoint_saved`: `{\"checkpoint_id\": str}`."
        },
        "name": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Tool name, for `tool_*` events.",
          "title": "Name"
        },
        "parent_id": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "`span_id` of the step that caused this one.",
          "title": "Parent Id"
        },
        "seq": {
          "description": "Position in the run, starting at 1. Ordering always uses `seq`, never `ts`.",
          "title": "Seq",
          "type": "integer"
        },
        "span_id": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Identifier of this step, for correlating with traces.",
          "title": "Span Id"
        },
        "ts": {
          "anyOf": [
            {
              "type": "number"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Unix time in seconds; informational, clocks differ across runtimes.",
          "title": "Ts"
        },
        "type": {
          "$ref": "#/$defs/EventType",
          "description": "What happened, e.g. `tool_requested` or `model_call`."
        }
      },
      "required": [
        "seq",
        "type"
      ],
      "title": "Event",
      "type": "object"
    }
    ```


??? abstract "InvokeRequest JSON Schema"

    ```json
    {
      "$defs": {
        "Environment": {
          "description": "The fixture environment a trial runs against.",
          "properties": {
            "base_url": {
              "description": "Fixture service URL the agent must use for every tool call.",
              "title": "Base Url",
              "type": "string"
            },
            "id": {
              "description": "Environment `id@version` key, e.g. `refund@2`.",
              "title": "Id",
              "type": "string"
            }
          },
          "required": [
            "id",
            "base_url"
          ],
          "title": "Environment",
          "type": "object"
        },
        "FaultAction": {
          "enum": [
            "timeout_after_commit",
            "error_before_commit"
          ],
          "type": "string"
        },
        "FaultWhen": {
          "anyOf": [
            {
              "enum": [
                "first_call",
                "always"
              ],
              "type": "string"
            },
            {
              "type": "integer"
            }
          ]
        },
        "JsonObject": {
          "additionalProperties": {
            "$ref": "#/$defs/JsonValue"
          },
          "type": "object"
        },
        "JsonValue": {},
        "ResumeFrom": {
          "description": "Continue a prior run from one of its checkpoints. Only for adapters declaring resume/fork.",
          "properties": {
            "checkpoint_id": {
              "description": "`checkpoint_id` from one of that trial's `checkpoint_saved` events.",
              "title": "Checkpoint Id",
              "type": "string"
            },
            "trial_id": {
              "description": "Trial whose run to continue.",
              "title": "Trial Id",
              "type": "string"
            }
          },
          "required": [
            "trial_id",
            "checkpoint_id"
          ],
          "title": "ResumeFrom",
          "type": "object"
        },
        "ToolFault": {
          "description": "A scripted tool failure. Applied by the fixture service, or by the harness when sent in `tool_faults`.",
          "properties": {
            "action": {
              "$ref": "#/$defs/FaultAction",
              "description": "`timeout_after_commit`: the side effect happens but the caller sees a failure. `error_before_commit`: the call fails with no side effect."
            },
            "tool": {
              "description": "Name of the tool to break.",
              "title": "Tool",
              "type": "string"
            },
            "when": {
              "$ref": "#/$defs/FaultWhen",
              "default": "first_call",
              "description": "Which calls fail: `first_call`, `always`, or an integer N for the Nth call (1-based)."
            }
          },
          "required": [
            "tool",
            "action"
          ],
          "title": "ToolFault",
          "type": "object"
        }
      },
      "description": "Body of `POST /invoke`: one trial for the harness to run.",
      "properties": {
        "deadline_ms": {
          "default": 60000,
          "description": "Time budget for the whole invocation, in milliseconds.",
          "title": "Deadline Ms",
          "type": "integer"
        },
        "environment": {
          "$ref": "#/$defs/Environment",
          "description": "Where the agent's tools live."
        },
        "idempotency_key": {
          "description": "Stable key for this invocation (`<trial_id>:invoke`), so a harness can de-duplicate a retried request.",
          "title": "Idempotency Key",
          "type": "string"
        },
        "input": {
          "$ref": "#/$defs/JsonObject",
          "description": "The scenario's `input`, handed to the agent as-is."
        },
        "protocol_version": {
          "default": "0.3",
          "description": "Wire protocol version of the sender.",
          "title": "Protocol Version",
          "type": "string"
        },
        "resume_from": {
          "anyOf": [
            {
              "$ref": "#/$defs/ResumeFrom"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Checkpoint to continue from, for resume/fork runs."
        },
        "scenario_version": {
          "description": "Scenario `id@version` being run.",
          "title": "Scenario Version",
          "type": "string"
        },
        "system_version": {
          "description": "Version label of the system under test, from the target config.",
          "title": "System Version",
          "type": "string"
        },
        "tool_faults": {
          "default": [],
          "description": "Faults the harness must apply at its own tool boundary; sent only to `intercept_tools=\"declared_only\"`.",
          "items": {
            "$ref": "#/$defs/ToolFault"
          },
          "title": "Tool Faults",
          "type": "array"
        },
        "traceparent": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "W3C `traceparent` header value, so the harness can join the runner's trace.",
          "title": "Traceparent"
        },
        "trial_id": {
          "description": "Unique id of this trial (one scenario, one repeat, one target).",
          "title": "Trial Id",
          "type": "string"
        }
      },
      "required": [
        "trial_id",
        "scenario_version",
        "system_version",
        "environment",
        "idempotency_key",
        "input"
      ],
      "title": "InvokeRequest",
      "type": "object"
    }
    ```


??? abstract "InvokeResponse JSON Schema"

    ```json
    {
      "$defs": {
        "Event": {
          "description": "One step the harness reports about its own run (only when `observe` is `native_events`).",
          "properties": {
            "data": {
              "$ref": "#/$defs/JsonObject",
              "default": {},
              "description": "Event payload. `tool_failed`: `{\"injected\": bool, \"committed\": bool}` when a fault fired. `checkpoint_saved`: `{\"checkpoint_id\": str}`."
            },
            "name": {
              "anyOf": [
                {
                  "type": "string"
                },
                {
                  "type": "null"
                }
              ],
              "default": null,
              "description": "Tool name, for `tool_*` events.",
              "title": "Name"
            },
            "parent_id": {
              "anyOf": [
                {
                  "type": "string"
                },
                {
                  "type": "null"
                }
              ],
              "default": null,
              "description": "`span_id` of the step that caused this one.",
              "title": "Parent Id"
            },
            "seq": {
              "description": "Position in the run, starting at 1. Ordering always uses `seq`, never `ts`.",
              "title": "Seq",
              "type": "integer"
            },
            "span_id": {
              "anyOf": [
                {
                  "type": "string"
                },
                {
                  "type": "null"
                }
              ],
              "default": null,
              "description": "Identifier of this step, for correlating with traces.",
              "title": "Span Id"
            },
            "ts": {
              "anyOf": [
                {
                  "type": "number"
                },
                {
                  "type": "null"
                }
              ],
              "default": null,
              "description": "Unix time in seconds; informational, clocks differ across runtimes.",
              "title": "Ts"
            },
            "type": {
              "$ref": "#/$defs/EventType",
              "description": "What happened, e.g. `tool_requested` or `model_call`."
            }
          },
          "required": [
            "seq",
            "type"
          ],
          "title": "Event",
          "type": "object"
        },
        "EventType": {
          "enum": [
            "run_started",
            "agent_step",
            "model_call",
            "tool_requested",
            "tool_completed",
            "tool_failed",
            "approval_requested",
            "retry_scheduled",
            "checkpoint_saved",
            "run_completed",
            "run_failed"
          ],
          "type": "string"
        },
        "JsonObject": {
          "additionalProperties": {
            "$ref": "#/$defs/JsonValue"
          },
          "type": "object"
        },
        "JsonValue": {},
        "Usage": {
          "description": "Resource use the harness reports for a run; omitted values are unknown, not zero.",
          "properties": {
            "cost_usd": {
              "anyOf": [
                {
                  "type": "number"
                },
                {
                  "type": "null"
                }
              ],
              "default": null,
              "description": "Total model spend in US dollars.",
              "title": "Cost Usd"
            },
            "input_tokens": {
              "anyOf": [
                {
                  "type": "integer"
                },
                {
                  "type": "null"
                }
              ],
              "default": null,
              "description": "Prompt tokens consumed across all model calls.",
              "title": "Input Tokens"
            },
            "output_tokens": {
              "anyOf": [
                {
                  "type": "integer"
                },
                {
                  "type": "null"
                }
              ],
              "default": null,
              "description": "Completion tokens produced across all model calls.",
              "title": "Output Tokens"
            },
            "steps": {
              "anyOf": [
                {
                  "type": "integer"
                },
                {
                  "type": "null"
                }
              ],
              "default": null,
              "description": "Agent steps taken.",
              "title": "Steps"
            }
          },
          "title": "Usage",
          "type": "object"
        }
      },
      "description": "Body returned by `POST /invoke`.",
      "properties": {
        "events": {
          "default": [],
          "description": "Ordered steps the agent took, if `observe` allows.",
          "items": {
            "$ref": "#/$defs/Event"
          },
          "title": "Events",
          "type": "array"
        },
        "output": {
          "$ref": "#/$defs/JsonValue",
          "default": null,
          "description": "The agent's final answer, in any JSON shape."
        },
        "run_id": {
          "description": "Harness-side identifier of this run.",
          "title": "Run Id",
          "type": "string"
        },
        "status": {
          "description": "Whether the agent finished its run; this is not a grading result.",
          "enum": [
            "completed",
            "failed"
          ],
          "title": "Status",
          "type": "string"
        },
        "usage": {
          "$ref": "#/$defs/Usage",
          "default": {
            "cost_usd": null,
            "input_tokens": null,
            "output_tokens": null,
            "steps": null
          },
          "description": "Resources used by the run."
        }
      },
      "required": [
        "run_id",
        "status"
      ],
      "title": "InvokeResponse",
      "type": "object"
    }
    ```


??? abstract "Manifest JSON Schema"

    ```json
    {
      "$defs": {
        "Capabilities": {
          "description": "What a harness can do beyond plain invoke; the runner skips or marks checks the harness cannot support.",
          "properties": {
            "checkpoint": {
              "default": false,
              "description": "Emits `checkpoint_saved` events that a run can be resumed from.",
              "title": "Checkpoint",
              "type": "boolean"
            },
            "fork": {
              "default": false,
              "description": "Can branch a prior trial's checkpoint into a new run (`resume_from`).",
              "title": "Fork",
              "type": "boolean"
            },
            "intercept_tools": {
              "default": "none",
              "description": "`declared_only` means the harness applies the `tool_faults` it receives at its own tool boundary; `none` means it ignores them.",
              "enum": [
                "declared_only",
                "none"
              ],
              "title": "Intercept Tools",
              "type": "string"
            },
            "invoke": {
              "default": true,
              "description": "Accepts `POST /invoke`. Always true for a working harness.",
              "title": "Invoke",
              "type": "boolean"
            },
            "observe": {
              "default": "none",
              "description": "How much of the run the harness reveals: `native_events` streams the full event list in the response, `otel_partial` exports OpenTelemetry spans only, `none` is a black box.",
              "enum": [
                "native_events",
                "otel_partial",
                "none"
              ],
              "title": "Observe",
              "type": "string"
            },
            "resume": {
              "default": false,
              "description": "Can continue a prior trial from a checkpoint (`resume_from`).",
              "title": "Resume",
              "type": "boolean"
            }
          },
          "title": "Capabilities",
          "type": "object"
        }
      },
      "description": "A harness's self-description, returned by `GET /manifest`.",
      "properties": {
        "adapter_id": {
          "description": "Stable identifier of this adapter, e.g. `acme-support-bot`.",
          "title": "Adapter Id",
          "type": "string"
        },
        "capabilities": {
          "$ref": "#/$defs/Capabilities",
          "default": {
            "checkpoint": false,
            "fork": false,
            "intercept_tools": "none",
            "invoke": true,
            "observe": "none",
            "resume": false
          },
          "description": "Optional features the harness supports."
        },
        "framework": {
          "default": "custom",
          "description": "Agent framework in use, e.g. `langgraph`; `custom` if none.",
          "title": "Framework",
          "type": "string"
        },
        "language": {
          "description": "Language the harness is written in, e.g. `python` or `typescript`.",
          "title": "Language",
          "type": "string"
        },
        "protocol_version": {
          "default": "0.3",
          "description": "Wire protocol version the harness speaks; a mismatch is refused.",
          "title": "Protocol Version",
          "type": "string"
        },
        "transport": {
          "const": "http_json",
          "default": "http_json",
          "description": "Wire transport; only HTTP+JSON exists.",
          "title": "Transport",
          "type": "string"
        }
      },
      "required": [
        "adapter_id",
        "language"
      ],
      "title": "Manifest",
      "type": "object"
    }
    ```
