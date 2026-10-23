# AgentLab

Reliability testing for AI agents. AgentLab runs your agent against an isolated, realistic environment, injects the
failures that break agents in production (a payment API that times out *after* charging, say), and grades **what the
agent actually did to the world**, the final database state and every side effect, not how its reply sounds.
Replies are judged by calibrated decision models. Every release gets a clear answer: `PASS`, `BLOCK` or
`INSUFFICIENT_EVIDENCE`.

**Documentation:** run `uv run --group docs mkdocs serve` and open http://127.0.0.1:8000, or read [`docs/`](docs/index.md).

## What it does

- **Free-form environments.** Describe any system as YAML: tables plus tools (one SQL statement each, with typed
  params, preconditions and idempotency). Each trial gets its own Postgres schema; agents discover tools at runtime
  over HTTP or **MCP**.
- **Plain-English authoring.** Describe a scenario in the console; a model drafts the environment, seed data, faults,
  state checks, honesty judge and labelled canaries, validates them against a real temporary environment, and hands
  you a draft to review.
- **Grounded grading.** SQL checks on the final state and the side-effect ledger are the source of truth; decision
  models (Jev → GPT-6 Luna Decisions cascade) judge reply honesty, are scored on evidence reading and on canaries,
  and may only block a release once calibrated.
- **Any agent, any language.** Python and TypeScript adapters, plain HTTP, or MCP. Reference agents on current
  models across the OpenAI SDK, OpenAI Agents SDK (MCP), LangGraph, Vercel AI SDK and a raw HTTP black box.
- **Operator console.** Start runs and watch them live, inspect state diffs, ledgers and judge verdicts, fork a
  trial from a checkpoint to test a counterfactual, edit environments and scenarios visually.

## Quickstart

```bash
uv sync && (cd console && bun install && bun run build)
docker compose up -d postgres
export AGENTLAB_DATABASE_URL=postgresql://agentlab:agentlab@127.0.0.1:55432/agentlab
doppler run -p infra -c prd -- ./scripts/agents.sh &        # reference agents (any OPENROUTER_API_KEY works)
doppler run -p infra -c prd -- uv run agentlab serve        # console at http://127.0.0.1:8800
```

Or from the command line, gating a candidate against a baseline (exit code 0 / 1 / 2 for CI):

```bash
uv run agentlab test scenarios --candidate openai-careful --baseline openai-naive-slm --repeats 3
```

See [Quickstart](docs/getting-started/quickstart.md) and [Your first scenario](docs/getting-started/first-scenario.md).

## What a run looks like

One stochastic run on 23 Oct 2026: a scenario authored in plain English (`pharmacy.refill_timeout@2`) plus
`refund.timeout@6`, 3 repeats, real models through OpenRouter.

| Framework | Careful agent | Naive agent | What the naive agent did |
|---|---|---|---|
| OpenAI SDK | deepseek-v4.1-flash: 6/6 | lfm-2.5-24b-a2b: **0/6** | duplicated the refill or refund after the timeout every time, and hid it |
| Agents SDK + MCP | qwen3.8-omni-flash: 6/6 | glm-5.3-flash: **2/6** | duplicated 3 of 6 times |
| LangGraph | claude-haiku-5.5: 6/6 | mimo-v2.6-flash: **3/6** | duplicated 3 of 6 times but told the customer, so the state check failed it and the honesty judge passed the reply |

The biggest lesson so far: **never let the environment coach the agent.** Early tool descriptions said "pass an
idempotency_key so a retry never refunds twice"; every naive agent followed it and looked safe. With neutral,
API-reference-style descriptions the same agents duplicate side effects. See
[Environments](docs/concepts/environments.md).

## Development

```bash
uv run ruff format . && uv run ruff check . && uv run ty check
uv run pytest -q                                            # real Postgres via Testcontainers
doppler run -p infra -c prd -- uv run pytest -m live -q     # real agents and judges; costs a little
uv run python scripts/gen_reference.py                      # regenerate docs/reference from the code
uv run --group docs mkdocs build --strict                   # docs site
(cd console && bun run typecheck)
```

Known limits are kept honest in [Limits](docs/operations/limits.md); security design in
[Security](docs/operations/security.md).
