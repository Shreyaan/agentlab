#!/usr/bin/env bash
# Cross-language demo: same scenarios against TypeScript, Python and a black-box HTTP agent.
set -uo pipefail
cd "$(dirname "$0")/.."
FIXTURE_PORT=${FIXTURE_PORT:-8900}
pids=()
cleanup() { kill "${pids[@]}" 2>/dev/null; }
trap cleanup EXIT

start() { env "$@" >/dev/null 2>&1 & pids+=($!); }
start AGENT_VARIANT=buggy PORT=7101 bun examples/ts_agent/agent.ts
start AGENT_VARIANT=fixed PORT=7111 bun examples/ts_agent/agent.ts
start AGENT_VARIANT=buggy PORT=7102 uv run python examples/python_agent/agent.py
start AGENT_VARIANT=fixed PORT=7112 uv run python examples/python_agent/agent.py
start AGENT_VARIANT=fixed PORT=7201 FIXTURE_URL=http://127.0.0.1:$FIXTURE_PORT bun examples/http_agent/agent.ts

for port in 7101 7111 7102 7112 7201; do  # wait for every agent to listen
  for _ in $(seq 50); do curl -s -o /dev/null "http://127.0.0.1:$port" && break; sleep 0.2; done
done

run() { echo; echo "=== $* ==="; uv run agentlab test scenarios --fixture-port "$FIXTURE_PORT" --repeats 3 "$@"; echo "exit code: $?"; }
uv run agentlab conformance ts-buggy ts-fixed py-buggy py-fixed http-fixed otel-only
run --candidate ts-fixed --baseline ts-buggy      # expect PASS
run --candidate py-buggy                          # expect BLOCK
run --candidate http-fixed                        # expect INSUFFICIENT_EVIDENCE (no native events)
