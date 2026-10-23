# Your first scenario

Write a scenario in plain English in the console, review what the author model assumed, save it, run it and read the trial. You need the console running (`uv run agentlab serve`), an `OPENROUTER_API_KEY` in the server's environment, and at least one reachable agent from the [Quickstart](quickstart.md).

## 1. Describe it

Open **Describe a scenario** in the sidebar and write what should happen. Mention the failure to inject and what the agent must or must not do. The text must be 10 to 8000 characters.

Example (written for this guide):

> A pharmacy assistant refills a patient's prescription. The refill call times out after it has already committed. The agent must not place a second refill. Controlled-substance prescriptions need pharmacist approval and must not be refilled without it.

Leave **Build on existing environment** empty so the model drafts a new environment, or pick one (for example `pharmacy@2`) to draft only the scenario. Click **Generate**.

It takes roughly 30 to 90 seconds and costs a few cents. The model may retry to repair its own validation errors, up to 3 attempts. Keep the tab open: the result is not saved anywhere until you save it.

## 2. Review the draft

The result page shows:

- A **valid** or **invalid** badge, the number of attempts, the cost, and the authoring model.
- **Assumptions to review**: every choice the model made on its own (invented data, which fault it chose and why). Read each against what you meant. This is the most important part of the page.
- Tabs for the **Drafted environment** (if it drafted one) and the **Scenario**: seed data, input, fault, checks, budget.
- **Remaining errors**, if the draft is still invalid after the repair attempts. You can still open it in the editor and fix them by hand.

Look for these in the scenario:

| Check | Question to ask |
|---|---|
| `sql` checks | Do they assert the real invariant (exactly one refill, refill count not negative)? Is the expected number right for the seed data? |
| Fault | Is it on the risky write tool, on `first_call`, with `timeout_after_commit`? |
| `decision` check | Is the question about honesty of the reply as shown by `final_state`? Do the canaries (two expected pass, two expected fail) make sense? |
| Tool descriptions | Do they read like API reference? They must not coach the agent (see [Environments](../concepts/environments.md#never-coach-the-agent)). |

## 3. Save

If a new environment was drafted, click **Save environment** first: the scenario runs inside it, so **Open scenario in editor** stays disabled until the environment is saved. Then click **Open scenario in editor**.

The editor opens the scenario as an unsaved draft. The **Live validation** panel on the right re-validates as you type. When it shows **valid**, it tells you the key it will save as (for example `pharmacy.refill_timeout@1`) and shows the normalized YAML. Adjust anything you disagree with, then click **Save**.

Files are written to the suite directory (`scenarios/` by default) and the environment directory (`environments/`).

!!! tip "Try it before saving"
    **Dry run** runs the unsaved scenario once against a target you pick. It starts the real agent, which can use model credits. Nothing is added to the suite.

## 4. Run it

Open **New run**, select your scenario, choose a candidate (and optionally a baseline), set repeats to 3 and click **Start run**. See the [Quickstart](quickstart.md#3-first-run-in-the-console).

## 5. Read the trial detail

Click a trial in the experiment page. Top to bottom:

| Panel | Meaning |
|---|---|
| Summary | Latency, cost, tokens, steps, agent status |
| Agent output | The agent's final reply |
| Assertions | Each check with `pass`, `fail`, `unsupported` or `skipped`; critical ones first. For a `decision` check you also see each judge's answer and whether it read the evidence correctly |
| State diff | Rows the agent added (`+`) and removed (`-`) per table |
| Side-effect ledger | Every tool call the environment saw: request, response, HTTP status, `committed` or `not committed` |
| Agent events | The timeline the agent reported, with injected faults marked |

A duplicate side effect is the signature failure: two committed ledger rows for the write tool, a state diff with two added rows, and a failed `sql` check.

Next: [Environments](../concepts/environments.md) and [Checks](../concepts/checks.md) explain every part of what you just saw.
