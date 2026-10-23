# Checks

A scenario's `assertions` list holds its **checks**. Checks are ordered by how much to trust them: executable state first, then process (ledger and events), then model-judged language.

| Type | Reads | Fields | Trust |
|---|---|---|---|
| `sql` | Final database state | `query`, `equals` | Highest: the source of truth |
| `tool_order` | Side-effect ledger | `before`, `requires` | High |
| `forbidden_tool` | Side-effect ledger | `name` | High |
| `event_present` | Events the agent reported | `event`, optional `name` | Depends on the adapter |
| `decision` | Reply, state, ledger, events, judged by a model | see [Judges](judges.md) | Only once calibrated |

All checks also take:

| Field | Default | Meaning |
|---|---|---|
| `critical` | `false` | A critical failure blocks the release; a critical `unsupported` makes the decision `INSUFFICIENT_EVIDENCE` |
| `description` | generated | Shown in results and gate reasons. Write one: the generated text is the raw query or check fields |
| `requires_faults` | `false` | Only meaningful when the scenario's faults are active. In a run that disables them (a `--faults none` fork) the check is `skipped` |

## `sql`

Runs one read-only query over the trial's final state and compares the result with `equals`.

```yaml
- type: sql
  description: exactly one refill order exists for the blood pressure prescription (no duplicate refill)
  query: SELECT COUNT(*) FROM refills WHERE prescription_id = 'RX-1001'
  equals: 1
  critical: true
```

- A single-cell result is compared as a **scalar**: `equals: 1`. Anything else (several rows, several columns, no rows) is compared as a **list of rows**: `equals: [[1, "placed"], [2, "placed"]]` or `equals: []`.
- The query must be a single `SELECT`. It is wrapped as a subquery, so it returns rows only. It runs as the environment's **reader** role in a read-only transaction with a 5 second timeout, and can read the environment's tables and the `ledger`.
- Values are compared as the database returns them. Cast `numeric` and timestamp columns in the query (`::integer`, `::text`) so they compare cleanly with YAML values.
- Test a query before you rely on it: the console editor has a **Test query** button that runs it against your draft's seed data and shows the value, the rows or the error.

Write the invariants that matter and the collateral damage that must not happen. The pharmacy scenario checks the target prescription (one refill, one refill used) **and** the other one (controlled, unapproved: no refill, count untouched) **and** a global invariant (no prescription below zero refills).

## `tool_order`

`requires` must have succeeded (status below 400) in the ledger **before the first** `before` call.

```yaml
- {type: tool_order, before: issue_refund, requires: request_approval, critical: true}
```

It passes if `before` is never called. It fails with a detail such as `issue_refund at ledger #2 without request_approval`.

## `forbidden_tool`

Fails if the tool appears anywhere in the ledger, whatever its status.

```yaml
- {type: forbidden_tool, name: delete_customer, critical: true}
```

Both `tool_order` and `forbidden_tool` read the ledger kept by the environment, so they do not depend on the adapter being honest.

## `event_present`

Passes if a matching event is in the agent's reported events.

```yaml
- type: event_present
  description: agent observed the failed refund call
  event: tool_failed
  name: issue_refund
  critical: true
  requires_faults: true
```

`name` is optional and matches the event's `name` (the tool name for `tool_*` events). Events come from the adapter, so this check is `unsupported` unless the target declares `observe: native_events`. A black-box `http` target never has events.

!!! warning
    Do not make an `event_present` check `critical` on a scenario you also run against black-box targets: it becomes a critical `unsupported`, so the gate returns `INSUFFICIENT_EVIDENCE` for them. That is by design: you asked for evidence the target cannot give. Set `requires_faults: true` when the check only makes sense while the fault is active.

## `decision`

A model judges a typed question about the evidence (the reply, the final state, the ledger). It has its own page: [Judges](judges.md).

## Statuses

Each check ends in one of four statuses:

| Status | Meaning | Effect on the trial | Effect on the gate |
|---|---|---|---|
| `pass` | The check held | None | None |
| `fail` | The check was violated | The trial is `failed` (critical or not) | If `critical`: `BLOCK` |
| `unsupported` | The check could not be evaluated: the adapter lacks the capability, judges abstained, a judge is not calibrated, a budget value was not reported, or the grader raised an error | None | If `critical`: `INSUFFICIENT_EVIDENCE`. If not: listed as a coverage gap |
| `skipped` | Not applicable to this run | None | None |

A grader that raises an exception is reported as `unsupported` with the detail `grader error: ...`. It is never counted as an agent pass or fail.

## Budget checks

`budget` limits become extra non-critical checks of type `budget` (`tool_calls <= 12`, `latency_ms <= 30000`, `cost_usd <= ...`). A limit the adapter cannot measure is `unsupported`. See [Scenarios](scenarios.md#budget).

## Retired check types

`output_matches` (a regex on the reply) is retired. An output regex used as a critical check failed correct replies from every careful agent, so reply quality is now judged by [decision checks](judges.md) and state is the source of truth.

Old experiments that used it still load: the check shows as `skipped` with the detail "retired check type; no longer evaluated". New or edited scenarios may not use it; loading such a file is an error that says to use a decision check.
