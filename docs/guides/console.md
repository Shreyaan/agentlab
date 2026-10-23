# The console

`uv run agentlab serve` starts one process with the web console, the JSON API under `/v1`, the background job runner and the environment service that agents call. Open <http://127.0.0.1:8800> (`--port` to change).

The sidebar has seven pages, plus the pages you reach from them. The top bar shows the protocol and console versions.

```bash
uv run agentlab serve [--port 8800] [--bind 127.0.0.1] [--token T] [--suite scenarios] [--targets targets.yaml] [--environments environments]
```

If the server was started with a token, the console asks for it once in a dialog ("API token required") and keeps it for that browser tab only (`sessionStorage`). See [Security](../operations/security.md).

## Experiments

The home page lists every experiment, newest first (up to 50): status, decision, candidate, baseline, age, error count, cost and id. A running experiment shows a progress bar and refreshes every 2 seconds. A `fork` badge marks experiments created by forking. Click a row to open it. **New run** is in the header.

Status is `running` (its job is alive), `complete` (it has a decision) or `incomplete` (the job died before a decision).

## New run

Pick what to run and click **Start run**; it starts in the background and opens the live view.

| Control | Meaning |
|---|---|
| Scenarios | A checklist of the suite with each scenario's risk tier, slices and fault summary. **Select all** toggles everything |
| Candidate | The target the gate decides on. Each option shows a filled dot when reachable. Capability badges show what the target supports |
| Baseline (optional) | A target to compare against |
| Repeats | 1 to 20 |
| Max regression % | The allowed pass-rate drop against the baseline |

The page shows the trial count (`scenarios x repeats x targets`). A target that cannot be invoked (for example an `otel` target) blocks the run.

## Experiment detail

| Section | Content |
|---|---|
| Header | Experiment id, status, repeats, **Export report** (the self-contained HTML report) |
| Notices | A fork banner linking to the source trial, or "The job stopped before a decision" with the reason |
| Decision banner | `PASS`, `BLOCK` or `INSUFFICIENT_EVIDENCE`, each reason, coverage gaps, and the reminder that an offline gate is evidence, not proof |
| Target cards | Pass rate with a 95% interval bar, errors, p50/p95 latency, cost, pass^k. One card per target, labelled candidate or baseline |
| Paired comparison | Regressions and fixes against the baseline |
| Scenario x target matrix | One cell per pair, `passed/graded` plus errors. Click a cell to filter the trial list |
| Trials | Filter by target, scenario and status. Each row links to the trial |
| Judge canaries | Per-model results of this experiment's canaries: label, expected, verdict, correct, probability, cost |

## Trial detail

Reached from a trial row. Summary (latency, cost, tokens, steps, agent status), then:

| Panel | Content |
|---|---|
| Agent output | The final reply |
| Assertions | Critical first. Each shows status, detail and, for decision checks, every judge's answer and calibration result |
| State diff | Rows added (`+`) and removed (`-`) per table |
| Side-effect ledger | Every tool call: sequence, tool, HTTP status, `committed` or `not committed`, request and response |
| Agent events | The event timeline. Injected faults are marked, checkpoints are highlighted |

If the target can fork (`fork` and `resume`), each `checkpoint_saved` event shows a **Fork from here** button. See [Fork a trial](fork.md). An error trial shows its error code and a reminder that infrastructure errors are never an agent pass or fail.

## Targets

One card per target in `targets.yaml`, with live reachability (probed with a 3 second timeout), version, URL, adapter details and a capability matrix. **Refresh** re-probes. **Add target** and **Edit** open a form: name, version, mode (`native`, `http`, `otel`), URL, and for `http` and `otel` a declared manifest (adapter id, language, framework, observe, intercept tools, invoke, checkpoint, resume, fork), with **Test connection**. **Delete** removes the target from `targets.yaml`; past experiments keep their results. A **Connect your agent** panel below shows snippets for each mode.

A host must be in `allowed_hosts` for the save to be accepted.

## Scenarios

A list of the suite (filterable by environment) and a read-only detail view: identity badges (risk tier, source, slices, environment), input, seed rows, faults, assertions (critical first, decision checks with question, rule, judges, calibration and canaries) and budget. Actions: **Describe a scenario**, **New scenario**, and per scenario **Edit** and **Duplicate**.

### Scenario editor

Sections: Identity, Environment, Seed data, Input, Faults, Assertions, Budget. The **Live validation** side panel re-validates 400 ms after each edit and shows the errors, the key it will save as and the normalized YAML. **Test query** on a `sql` check runs it against your draft's seed data. **Dry run** (enabled when valid) runs the unsaved scenario once against a reachable target; it starts the real agent. **Save** is enabled when valid and changed; editing a saved scenario creates the next version. Leaving with unsaved changes asks for confirmation.

## Describe a scenario

The plain-English authoring page. See [Author scenarios in plain English](author-scenarios.md).

## Environments

A list with table and tool counts, and a detail view of tables, tools, rules and SQL. The **How agents connect** box shows the catalog and MCP URL patterns. Actions: **New environment**, **Edit**, **Duplicate**.

### Environment editor

Identity (id, description), Tables (columns with type, primary key, unique, nullable, serial, references) and Tools (description, parameters with type and enum, rules with status and error, effect SQL, returns, success status, mutates, idempotent). The **Live validation** panel dry-runs every tool's SQL. See [Write an environment by hand](write-environments.md).

## Judges

Each judge model's track record on the two accuracy bars (evidence reading, verdict accuracy), with sample counts, accuracy and 95% interval against the 90% bar, cost, and a `calibrated` or `not calibrated` badge. Only calibrated judges can make a critical decision check block a release. See [Judges](../concepts/judges.md).

## When the frontend is not built

If `src/agentlab/console_dist/` is missing, `serve` still runs the API and `/` shows instructions: `cd console && bun install && bun run build`. For development, `cd console && bun run dev` serves the UI with hot reload and proxies `/v1` to port 8800. The frontend's types are generated from the API: `bun run gen:api`.
