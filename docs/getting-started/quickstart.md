# Quickstart

Run a careful agent and a naive agent through the shipped scenarios and read the gate decision. About ten minutes, and the LLM calls cost real money (a few cents with the flash-class models in `scripts/agents.sh`).

You need everything from [Install](install.md): Postgres up, `AGENTLAB_DATABASE_URL` exported, an `OPENROUTER_API_KEY`.

## 1. Start the agents

`scripts/agents.sh` starts every reference agent listed in `targets.yaml` in the background and waits until each answers:

```bash
./scripts/agents.sh        # with OPENROUTER_API_KEY in the environment
# or: doppler run -p infra -c prd -- ./scripts/agents.sh
```

It prints `agents up: 9` and keeps running; Ctrl-C stops them all. Run it in its own terminal.

To start just one pair instead, run the Python OpenAI-SDK agent twice. `PROMPT` picks `examples/prompts/careful.md` or `naive.md`:

```bash
PORT=7401 PROMPT=careful MODEL=deepseek/deepseek-v4.1-flash-1017 uv run python -m examples.openai_agent.agent
PORT=7402 PROMPT=naive   MODEL=liquid/lfm-2.5-24b-a2b            uv run python -m examples.openai_agent.agent
```

These match the targets `openai-careful` and `openai-naive-slm` in `targets.yaml`.

## 2. Start the console

```bash
uv run agentlab serve
```

Open <http://127.0.0.1:8800>. `serve` starts one process: the console UI, the JSON API, the background job runner and the environment service that agents call (port 8900).

## 3. First run in the console

1. Open **New run**.
2. Leave all five scenarios selected (the `scenarios/` directory).
3. Pick **Candidate** `openai-careful` and **Baseline** `openai-naive-slm`. A filled dot means the target answered its manifest; targets that are not reachable are marked "not runnable".
4. Set **Repeats** to 3. The page shows the trial count: 5 scenarios x 3 repeats x 2 targets = 30 trials.
5. Click **Start run**. You land on the live experiment view, which refreshes every 2 seconds.

## 4. The same run from the CLI

```bash
uv run agentlab test scenarios --candidate openai-careful --baseline openai-naive-slm --repeats 3
```

Output ends with a summary like this (numbers will differ):

```text
experiment exp_20261023_101500_a1b2c3
  openai-careful           passed 15/15  rate 100% [80%, 100%]  errors 0  pass^3 100%  cost $0.0210
  openai-naive-slm         passed 3/15  rate 20% [7%, 45%]  errors 0  pass^3 0%  cost $0.0150
  paired: 0 regression(s), 12 fix(es) over 15 pair(s)

DECISION: PASS
```

The decision is about the **candidate**: here the careful agent passes and the baseline is only the comparison. Swap the roles and you get `BLOCK`. The command also writes an HTML report to `.agentlab/reports/<experiment>.html` and exits with `0` for `PASS`, `1` for `BLOCK`, `2` for `INSUFFICIENT_EVIDENCE`, `3` for a usage or infrastructure error.

## 5. Read the result

Start at the decision banner on the experiment page, then drill down.

| Where | What to look for |
|---|---|
| Decision banner | `PASS`, `BLOCK` or `INSUFFICIENT_EVIDENCE`, with each reason on its own line |
| Per-target card | Pass rate, 95% interval, errors, p50/p95 latency, cost, pass^k |
| Paired comparison | Scenario+repeat pairs that passed on the baseline and failed on the candidate (regressions) or the reverse (fixes) |
| Scenario x target matrix | Click a cell to filter the trial list |
| Trial detail | Agent output, assertions (critical first), state diff, side-effect ledger, event timeline |

In a trial, the quickest way to see what went wrong is the **State diff** (what the agent changed) and the **Side-effect ledger** (every tool call, its HTTP status, and whether it `committed`). A duplicated refund shows up as two `issue_refund` rows with `committed`, even when the agent's reply claimed one.

!!! note "Why a run can be INSUFFICIENT_EVIDENCE"
    The gate never treats missing evidence as a pass. A trial that errored, a scenario with no graded trial, or a *critical* check that could not be evaluated (for example an unsupported `event_present` on a black-box agent, or a judge that is not yet calibrated) makes the decision `INSUFFICIENT_EVIDENCE`. See [The release gate](../concepts/gate.md).

Next: [write your first scenario](first-scenario.md).
