# Fork a trial

A **fork** resumes a stored trial from one of its checkpoints, in an environment restored to exactly that point. Use it for counterfactuals: *what would this agent have done if the timeout had never happened?*, or *does a fixed agent recover from the same half-finished state?*

## Run a fork

```bash
uv run agentlab fork <trial_id> --checkpoint <checkpoint_id> [--target NAME] [--faults none|scenario] [run flags]
```

| Argument | Meaning |
|---|---|
| `trial_id` | `<experiment>:<target>:<scenario>@<version>:<repeat>`, shown in the console |
| `--checkpoint` | A checkpoint id from the trial's `checkpoint_saved` events (`data.checkpoint_id`) |
| `--target` | Defaults to the source trial's target. It must declare `fork` and `resume` |
| `--faults` | `none` (default): rerun **without** the scenario's faults, the counterfactual. `scenario`: keep them |

The run flags are the same as for `test` (`--targets`, `--database-url`, `--concurrency`, `--deadline-ms`, `--fixture-port`, `--report-dir` and so on). The command prints the usual summary and decision for the fork and exits with the same codes.

In the console, open a trial of a fork-capable target. Every `checkpoint_saved` event in **Agent events** has a **Fork from here** button. The dialog asks for the target and the fault mode (`none`: "Counterfactual: replay without the scenario's faults"; `scenario`: "Keep the scenario's faults active after the checkpoint"), then starts the fork and opens it.

Over the API: `POST /v1/forks` with `{trial_id, checkpoint_id, target, faults}` (needs the `X-AgentLab-Request: 1` header). A checkpoint that is not in the trial's events returns `400`; a target that cannot fork returns `409`.

## How the restore works

1. The runner counts the environment calls that happened **before** the checkpoint in the source trial's events: every `tool_completed` and `tool_failed` event, except harness-injected failures marked `committed: false` (those never reached the environment).
2. It takes that many entries from the stored side-effect ledger.
3. It creates a fresh isolated schema from the scenario's seed, using the environment spec the experiment pinned.
4. It **replays the committed calls**: each entry whose `committed` is true is re-executed, in order, so the database ends up exactly as it was. Uncommitted entries (failed calls) are logged but not applied. Fault call counters continue from where the source left off, so a `when: first_call` fault that already fired does not fire again.
5. The agent receives `resume_from: {trial_id, checkpoint_id}` and continues. The fork is graded like any trial against the same scenario and gets its own experiment with one trial (id ending in `:fork`).

Checks marked `requires_faults: true` are `skipped` in a `--faults none` fork, because there is no failure to observe. That is what the flag is for.

!!! note
    Restore re-executes the committed calls, so it reproduces the state exactly when the tool SQL is deterministic. Serial ids are deterministic by design; SQL that uses the clock or randomness can produce different values on replay.

## What your adapter must do

A target can be forked when its manifest declares `fork` **and** `resume`, and its adapter:

- emits `checkpoint_saved` events with `data.checkpoint_id` (declare `checkpoint`);
- emits **exactly one** tool event per environment call, so the runner can count calls before a checkpoint. Wrap every call in `Recorder.tool`, or emit the events yourself when using MCP;
- accepts `resume_from` in `/invoke` and continues from that checkpoint. An adapter without `resume` answers `400 CAPABILITY_UNSUPPORTED`.

A target that cannot fork is rejected up front (`CAPABILITY_UNSUPPORTED`).

## Example: LangGraph

`examples/langgraph_agent/` implements all of it:

- `thread_id` is the trial id; every streamed LangGraph checkpoint becomes a `checkpoint_saved` event, emitted once its superstep and tool calls have finished so events stay ordered.
- On `resume_from`, the graph continues that thread from that checkpoint with no new input.
- Its checkpoints live in an in-memory saver, so **the agent process must stay up** between the original run and the fork. Restart it and the checkpoints are gone.

Its manifest: `observe: native_events`, `intercept_tools: declared_only`, `checkpoint`, `resume` and `fork` all true.
