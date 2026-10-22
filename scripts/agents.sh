#!/usr/bin/env bash
# Start every real LLM agent from targets.yaml in the background. OPENROUTER_API_KEY must be in the environment,
# e.g. `doppler run -p infra -c prd -- ./scripts/agents.sh`. Ctrl-C stops them all.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${OPENROUTER_API_KEY:?set OPENROUTER_API_KEY (e.g. via doppler run)}"
FIXTURE_URL=${FIXTURE_URL:-http://127.0.0.1:${AGENTLAB_FIXTURE_PORT:-8900}/env/shared}
pids=()
trap 'kill "${pids[@]}" 2>/dev/null' EXIT INT TERM

#      port prompt  model                              command
AGENTS=(
  "7301 careful openai/gpt-4.1-mini               bun examples/vercel_agent/agent.ts"
  "7302 naive   openai/gpt-4.1-nano               bun examples/vercel_agent/agent.ts"
  "7401 careful openai/gpt-4.1-mini               uv run python -m examples.openai_agent.agent"
  "7402 naive   meta-llama/llama-3.1-8b-instruct  uv run python -m examples.openai_agent.agent"
  "7501 careful anthropic/claude-haiku-4.5        uv run python -m examples.langgraph_agent.agent"
  "7502 naive   openai/gpt-4.1-nano               uv run python -m examples.langgraph_agent.agent"
  "7601 careful openai/gpt-4.1-mini               bun examples/http_agent/agent.ts"
)
for spec in "${AGENTS[@]}"; do
  read -r port prompt model cmd <<<"$spec"
  PORT=$port PROMPT=$prompt MODEL=$model FIXTURE_URL=$FIXTURE_URL $cmd &
  pids+=($!)
done
for spec in "${AGENTS[@]}"; do  # wait until every agent answers
  port=${spec%% *}
  for _ in $(seq 150); do curl -s -o /dev/null "http://127.0.0.1:$port/" && break; sleep 0.2; done
done
echo "agents up: ${#AGENTS[@]}"
wait
