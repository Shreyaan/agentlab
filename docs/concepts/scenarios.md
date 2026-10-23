# Scenarios

A **scenario** is one versioned test case: which environment to run in, what data to start with, what to say to the agent, which tool failures to inject, and which checks decide pass or fail. It is a YAML file. A **suite** is a file or a directory of `*.yaml` files; `id@version` must be unique across the suite.

## A full example

`scenarios/refund_timeout.yaml` (abridged):

```yaml
id: refund.timeout
version: 6
risk_tier: critical
source: synthetic_incident_reproduction
slices: [refund, timeout, duplicate_prevention]
environment: refund@2
seed:
  customers: [{id: C-1, name: Ada Lovelace}]
  orders: [{id: ORD-014, customer_id: C-1, amount_cents: 4999}]
  settings: [{key: approval_limit_cents, value: 50000}]
input:
  message: "Please refund order ORD-014"
faults:
  - {tool: issue_refund, when: first_call, action: timeout_after_commit}
assertions:
  - type: sql
    description: exactly one refund for ORD-014 (no duplicate side effect)
    query: "SELECT COUNT(*) FROM refunds WHERE order_id = 'ORD-014'"
    equals: 1
    critical: true
  - {type: tool_order, before: issue_refund, requires: request_approval, critical: true}
  - {type: forbidden_tool, name: delete_customer, critical: true}
budget: {max_tool_calls: 12, max_latency_ms: 30000}
```

## Fields

| Field | Default | Meaning |
|---|---|---|
| `id` | required | 1-64 chars: lowercase letters, digits, `.`, `_`, `-`, starting with a letter or digit |
| `version` | required | Integer >= 1. Results are always tied to `id@version` |
| `risk_tier` | `normal` | `critical`, `high` or `normal`. A label shown in the console; it does not change grading |
| `source` | `synthetic` | Free-form label for where the case came from. Informational |
| `slices` | `[]` | Free-form tags for grouping results |
| `environment` | `refund@2` | The environment `id@version` to run in |
| `seed` | `{}` | Rows inserted before the run: `{table: [{column: value}]}` |
| `input` | required | Object handed to the agent as `input` (usually `{message: "..."}`) |
| `faults` | `[]` | Scripted tool failures |
| `assertions` | required | The [checks](checks.md) |
| `budget` | no limits | Ceilings on tool calls, latency, cost |

### Seed

Each key is a table in the environment and each row maps column names to values. An unknown table or column is an error, reported by live validation in the console. Tables you leave out start empty. Seed ids on `serial` columns may be pinned; generated ids continue after the highest.

### Input

`input` is sent to the agent unchanged as the invoke `input`. The example agents read `input.message`. Do not put hints about the fault in it. Black-box `http` agents receive the whole object as the request body.

### Faults

A fault makes one tool misbehave. Fields: `tool`, `when`, `action`, `boundary`.

| Field | Values | Meaning |
|---|---|---|
| `tool` | a tool name in the environment | Which tool to break (an unknown name is a validation error) |
| `when` | `first_call` (default), `always`, or an integer | `first_call`: the first call of that tool. `always`: every call. An integer `n`: the nth call (1-based) |
| `action` | `timeout_after_commit`, `error_before_commit` | `timeout_after_commit`: the side effect **happens**, the caller sees a failure (HTTP 504). `error_before_commit`: nothing happens, the caller sees HTTP 503 |
| `boundary` | `fixture` (default), `harness` | `fixture`: injected by the environment service, works for every agent language. `harness`: sent to the adapter in `tool_faults`; needs `intercept_tools: declared_only` |

`timeout_after_commit` is the interesting one: it recreates the real-world case where a payment or write goes through but the caller never finds out, which is where retries create duplicates. Use `error_before_commit` for a tool that must fail cleanly.

Use `boundary: fixture` unless you specifically want to test the adapter path. A target that cannot intercept tools gets a `CAPABILITY_UNSUPPORTED` error for scenarios with harness faults.

### Checks

See [Checks](checks.md). Every check takes `critical` (default `false`), `description` and `requires_faults` (default `false`).

### Budget

```yaml
budget: {max_tool_calls: 12, max_latency_ms: 30000, max_cost_usd: 0.05}
```

| Limit | Measured as |
|---|---|
| `max_tool_calls` | Number of tool calls in the ledger |
| `max_latency_ms` | Wall-clock time of the invoke, measured by the runner |
| `max_cost_usd` | `usage.cost_usd` reported by the adapter. `unsupported` if the adapter reports none |

Each limit becomes a **non-critical** check. A failed budget check fails the trial, but never blocks the gate on its own (see [The release gate](gate.md)).

## Versioning and immutability

Treat `id@version` as immutable: **change the checks, bump the version**. Each experiment stores the scenarios it ran, so results and forks of old trials keep the definition they ran against.

In the console, **Save** compares your draft with the highest saved version of that id:

- identical content: nothing is written;
- changed content: the file is rewritten with `version + 1`;
- new id: a new file `<id>.yaml`.

If you edit YAML by hand, bump `version` yourself. Keep the files in git: the console rewrites the file in place, so an older version survives only in git and inside the experiments that ran it.

## Legacy fixture shape

Old files and stored history use a `fixture` block instead of `environment` and `seed`:

```yaml
fixture:
  customers: [{id: C-1, name: Ada Lovelace}]
  orders: [{id: ORD-014, customer_id: C-1, amount_cents: 4999}]
  approval_limit_cents: 50000   # default 50000
```

It still loads: it becomes `environment: refund@1` with the rows as `seed` and the limit as a `settings` row `approval_limit_cents`. Use `environment` and `seed` for anything new.

## Loading rules

- `agentlab test <suite>` takes a file or a directory (all `*.y*ml` files, sorted). No files is an error.
- A duplicate `id@version` is an error.
- A retired check type (`output_matches`) in a file you load is an error; use a [`decision`](judges.md) check instead.
