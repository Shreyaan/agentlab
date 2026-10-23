# Trials

A **trial** is one run of one scenario against one target. An **experiment** is a set of trials (scenarios x repeats x targets) that ends in one gate decision.

Trial ids look like `<experiment>:<target>:<scenario>@<version>:<repeat>`, for example `exp_20261023_101500_a1b2c3:openai-careful:refund.timeout@6:0`. Repeats are numbered from 0. A fork's trial ends in `:fork`.

## One trial, step by step

1. **Plan.** The runner expands scenarios x repeats x targets into trials. The experiment **pins** what it used: each scenario, each environment spec, each target's manifest. Results stay interpretable after you edit files.
2. **Record `running`.** The trial row is written *before* the agent is invoked, so a crash leaves an inspectable unfinished trial.
3. **Connect.** The runner reads the target's manifest (and refuses a protocol version other than `0.3`). A host outside `allowed_hosts` fails here with `UNSAFE_TARGET`. An observe-only target fails with `CAPABILITY_UNSUPPORTED`. A scenario with harness faults against a target with `intercept_tools: none` also fails with `CAPABILITY_UNSUPPORTED`.
4. **Create the environment.** A fresh Postgres schema `env_<id>`, tables from the spec, rows from the seed, two login roles, and the scenario's `fixture` faults. See [Environments](environments.md#isolation-per-trial).
5. **Snapshot** the initial state.
6. **Invoke the agent.** `POST /invoke` with the scenario `input`, the environment's `base_url`, a deadline and any harness faults. The agent works by calling tools on that URL, over HTTP or MCP. Faults fire at the service boundary; every call lands in the ledger.
7. **Collect evidence.** The ledger, the final state, and the diff between initial and final state, plus the agent's output, events, usage and measured latency.
8. **Grade.** Every check runs, then the budget checks. See [Checks](checks.md). Decision checks call the [judges](judges.md).
9. **Persist.** The trial becomes `passed` if no check has status `fail`, otherwise `failed`. The record is [redacted](../operations/security.md#redaction) and written to Postgres.
10. **Drop** the schema and the roles.

Once per experiment and scenario, in parallel with the trials, the runner also runs the **canaries** of every decision check. When all trials are done the gate decides: see [The release gate](gate.md).

Trials run concurrently (`--concurrency`, default 4), each in its own schema. The exception is a generic `http` target: its trials share one environment and run one at a time.

## Trial statuses

| Status | Meaning |
|---|---|
| `running` | Started, not finished. If it stays this way, the process died: the gate treats it as an error (`INCOMPLETE`) |
| `passed` | Graded, no check failed |
| `failed` | Graded, at least one check failed (critical or not) |
| `error` | Never graded: an infrastructure or protocol problem. The record carries an error `code` and `message` |

## Errors vs failures

!!! warning "The distinction matters"
    A **failure** is evidence about the agent. An **error** is a problem in the harness, the adapter or the infrastructure, and says nothing about the agent. Errors are never counted as an agent pass or fail; they are excluded from pass rates and make the gate return `INSUFFICIENT_EVIDENCE`.

| Error code | When |
|---|---|
| `UNSAFE_TARGET` | The target host is not in `allowed_hosts` |
| `PROTOCOL_VERSION_MISMATCH` | The adapter does not speak protocol `0.3` |
| `CAPABILITY_UNSUPPORTED` | Observe-only target, harness faults without `intercept_tools`, or a `resume_from` sent to an adapter without `resume` |
| `ADAPTER_TIMEOUT` | The adapter did not answer within the deadline |
| `ADAPTER_ERROR` | Connection failure, non-2xx from the adapter, non-JSON body, or a response that does not match the protocol |
| `TRACE_INCOMPLETE` | Raised by `agentlab conformance` when event `seq` is not strictly increasing |

`ENVIRONMENT_NOT_RESETTABLE` exists in the protocol's error enum but nothing in the runner raises it today.

An agent that **crashes inside its handler** is a failure, not an error: the adapter reports `status: failed` with a `run_failed` event, and the trial is still graded on the state it left behind. The trial's pass or fail comes from the checks alone. A generic `http` target that answers non-2xx is recorded the same way (a failed run, graded normally).

## Persistence

Results live in Postgres, schema `agentlab`, created on first use:

| Table | Holds |
|---|---|
| `experiments` | Id, creation time, pinned `meta` (scenarios, environments, targets, repeats), the `decision`, and an `error` if the job died |
| `trials` | One row per trial, with the full record as JSON (output, events, ledger, states, diff, check results, usage) |
| `canary_results` | One row per judge x canary |

Everything is redacted on the way in. The experiment status in the console is `complete` (has a decision), `running` (its job is alive) or `incomplete` (the job died before a decision; the reason is stored in `error`).

`agentlab test` and `agentlab fork` also write a self-contained HTML report to `.agentlab/reports/<experiment>.html` (`--report-dir` to change).

## Fork and counterfactual

A **fork** resumes a stored trial from one of its checkpoints, in an environment restored to exactly that point. It answers "what would this agent have done if the failure had not happened?" The restore replays the **committed prefix of the stored ledger**: the runner counts the environment calls made before the checkpoint, takes that many ledger entries, creates a fresh schema and re-applies each committed call. The agent then receives `resume_from` and continues, and the fork is graded like any trial against the same scenario.

Details and requirements: [Fork a trial](../guides/fork.md).
