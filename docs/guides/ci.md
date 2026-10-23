# Run in CI

`agentlab test` is a release gate: it runs a suite, decides, prints the reasons and exits with a code your CI can act on.

```bash
uv run agentlab test scenarios --candidate my-agent --baseline my-agent-main --repeats 5
```

## Exit codes

| Code | Meaning |
|---|---|
| `0` | `PASS` |
| `1` | `BLOCK` (`conformance` also uses `1` for a failed target) |
| `2` | `INSUFFICIENT_EVIDENCE` |
| `3` | Usage, configuration or infrastructure error |

Argparse errors are mapped to `3`, so a typo in a flag never reads as `2`. Unknown targets, a missing database URL, an unreadable suite and similar problems print `error: ...` to stderr and exit `3`.

The default CI behaviour is right for most teams: any non-zero exit fails the job, so both `BLOCK` and `INSUFFICIENT_EVIDENCE` stop the release. To treat them differently, inspect `$?` yourself (below).

## What `test` needs

| Need | How |
|---|---|
| Postgres | `AGENTLAB_DATABASE_URL` (or `--database-url`) |
| The agent running | Start it before the step, and list it in `targets.yaml` |
| `OPENROUTER_API_KEY` | Only if the suite has `decision` checks |
| A baseline (optional) | Another target, for a paired comparison. Pass `--max-regression` for the allowed pass-rate drop (0 to 1) |

Useful flags: `--repeats N` (default 1, use at least 3 to 5 in CI), `--concurrency N` (default 4), `--deadline-ms` (default 120000), `--report-dir` (default `.agentlab/reports`). See the [CLI reference](../reference/cli.md).

The command also writes `.agentlab/reports/<experiment>.html`, a self-contained report you can keep as a build artifact.

## GitHub Actions

This mirrors the setup of the repo's own `.github/workflows/ci.yml` (checkout, `astral-sh/setup-uv`, `uv sync --frozen`); the gate step is yours.

```yaml
name: agent-gate
on: [pull_request]
jobs:
  gate:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:17-alpine
        env: {POSTGRES_USER: agentlab, POSTGRES_PASSWORD: agentlab, POSTGRES_DB: agentlab}
        ports: ["5432:5432"]
        options: --health-cmd "pg_isready -U agentlab" --health-interval 2s --health-retries 30
    env:
      AGENTLAB_DATABASE_URL: postgresql://agentlab:agentlab@127.0.0.1:5432/agentlab
      OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --frozen
      # start your agent here, listed in targets.yaml
      - run: uv run agentlab conformance my-agent
      - run: uv run agentlab test scenarios --candidate my-agent --baseline my-agent-main --repeats 5
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: agentlab-report
          path: .agentlab/reports/
```

Notes:

- The Postgres service user is the container's superuser, which is what AgentLab needs to create schemas and roles.
- Start the agent in the background before the gate (for example `uv run python -m my_agent &`) and wait until it answers `GET /manifest`. `agentlab conformance` is a cheap check that it does.
- Remember that your agent's own model calls cost money on every run.

### Treat `INSUFFICIENT_EVIDENCE` differently

```yaml
      - run: |
          set +e
          uv run agentlab test scenarios --candidate my-agent --repeats 5
          code=$?
          if [ "$code" -eq 2 ]; then echo "::warning::insufficient evidence"; exit 0; fi
          exit "$code"
```

Be careful: `INSUFFICIENT_EVIDENCE` means something needed to decide is missing (an errored trial, an unsupported critical check, an uncalibrated judge). Waving it through ships changes you could not verify.

## The repo's own CI

`.github/workflows/ci.yml` runs on every push and pull request:

| Job | Steps |
|---|---|
| `python` | `uv sync --frozen`, `ruff format --check .`, `ruff check .`, `ty check`, `pytest` (Testcontainers starts Postgres through the runner's Docker) |
| `typescript` | For `packages/adapter-ts`, `examples/vercel_agent`, `examples/http_agent`: `bun install --frozen-lockfile` and `bunx tsc --noEmit`; then `node --test` in `packages/cli` |

`pytest` deselects tests marked `live` by default (`-m 'not live'`). Live tests call real LLM agents and cost money; run them with `uv run pytest -m live` and an `OPENROUTER_API_KEY`.
