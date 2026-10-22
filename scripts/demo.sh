#!/usr/bin/env bash
# End-to-end demo with real LLM agents: Postgres via docker compose, agents via OpenRouter (key from Doppler).
set -uo pipefail
cd "$(dirname "$0")/.."
export AGENTLAB_DATABASE_URL=${AGENTLAB_DATABASE_URL:-postgresql://agentlab:agentlab@127.0.0.1:55432/agentlab}
docker compose up -d --wait postgres >/dev/null
RUN=${DOPPLER_RUN:-doppler run -p infra -c prd --}

$RUN ./scripts/agents.sh & agents=$!
trap 'kill $agents 2>/dev/null; wait $agents 2>/dev/null' EXIT
for port in 7301 7302 7401 7402 7501 7502 7601; do
  for _ in $(seq 150); do curl -s -o /dev/null "http://127.0.0.1:$port/" && break; sleep 0.2; done
done

run() { echo; echo "=== $* ==="; uv run agentlab test scenarios --repeats 3 --concurrency 8 "$@"; echo "exit code: $?"; }
uv run agentlab conformance vercel-careful openai-careful langgraph-careful http-careful otel-only
run --candidate vercel-careful --baseline vercel-naive-nano
run --candidate openai-careful --baseline openai-naive-llama
run --candidate langgraph-careful --baseline langgraph-naive
run --candidate http-careful     # black box: process evidence unavailable -> INSUFFICIENT_EVIDENCE
echo; echo "console: uv run agentlab serve  ->  http://127.0.0.1:8800"
