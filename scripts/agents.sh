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
  "7301 careful z-ai/glm-5.3-flash                bun examples/vercel_agent/agent.ts"
  "7302 naive   inclusionai/ling-3.1-flash        bun examples/vercel_agent/agent.ts"
  "7401 careful deepseek/deepseek-v4.1-flash-1017 uv run python -m examples.openai_agent.agent"
  "7402 naive   liquid/lfm-2.5-24b-a2b            uv run python -m examples.openai_agent.agent"
  "7501 careful anthropic/claude-haiku-5.5        uv run python -m examples.langgraph_agent.agent"
  "7502 naive   xiaomi/mimo-v2.6-flash            uv run python -m examples.langgraph_agent.agent"
  "7601 careful minimax/minimax-m3.1-flash        bun examples/http_agent/agent.ts"
  "7701 careful qwen/qwen3.8-omni-flash           uv run python -m examples.agents_sdk_agent.agent"
  "7702 naive   z-ai/glm-5.3-flash                uv run python -m examples.agents_sdk_agent.agent"
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
