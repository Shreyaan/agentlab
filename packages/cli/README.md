# @agentlab/cli

Node wrapper for the `agentlab` Docker image; no Python needed. Requires Docker (or OrbStack) and Node 20+.

```bash
npm i -g ./packages/cli
docker build -t agentlab .   # once, from the repo root
agentlab test scenarios --candidate my-agent --targets targets.yaml
```

The current directory is mounted at `/work`. Exit codes match the Python CLI (0 PASS, 1 BLOCK, 2 INSUFFICIENT_EVIDENCE, 3 usage error).
- `AGENTLAB_DATABASE_URL`: passed by name; a localhost/127.0.0.1/[::1] host is rewritten to `host.docker.internal`
- `AGENTLAB_IMAGE`: image to run (default `agentlab:latest`)
- `AGENTLAB_PUBLISH_HOST`: host interface for published ports (default `127.0.0.1`; the fixture and console are unauthenticated, so widen only on trusted networks)
- `AGENTLAB_FIXTURE_PORT`: fixture port to publish (default 8900)
- `AGENTLAB_FIXTURE_BIND` (default `0.0.0.0`), `AGENTLAB_FIXTURE_URL` (default `http://127.0.0.1:<fixture port>/`)
- `OPENROUTER_API_KEY`: passed by name; the value never goes into argv
- `serve` and `fixture` get `--bind 0.0.0.0` unless you pass `--bind`; `serve` also publishes `--port` (default 8800)
- Agents on the host must bind `HOST=0.0.0.0` and be listed in targets as `host.docker.internal`
