# Install

AgentLab is a Python control plane (FastAPI, Postgres) with an optional React console and TypeScript examples. You run it from a checkout of the repository.

## Requirements

| Tool | Why | Needed for |
|---|---|---|
| Python 3.13+ and [uv](https://docs.astral.sh/uv/) | `requires-python = ">=3.13"`; uv installs Python and the dependencies | Everything |
| Docker | Runs Postgres through `docker-compose.yml` | Everything (or bring your own Postgres) |
| [bun](https://bun.sh) | Builds the console frontend, runs the TypeScript example agents | Console from source, TS agents |
| `OPENROUTER_API_KEY` | OpenRouter key | The example agents, decision judges, plain-English authoring |

AgentLab needs the key only for features that call a model: `decision` checks and the authoring page. Checks of type `sql`, `tool_order`, `forbidden_tool` and `event_present` need no key.

## 1. Install the Python dependencies

```bash
uv sync
```

`uv sync` installs the default dependency groups: `dev` (pytest, ruff, ty, testcontainers) and `agents` (LangGraph, OpenAI SDKs for the example agents). The Docker image installs neither.

## 2. Start Postgres

```bash
docker compose up -d --wait postgres
export AGENTLAB_DATABASE_URL=postgresql://agentlab:agentlab@127.0.0.1:55432/agentlab
```

The compose file publishes Postgres on `127.0.0.1:55432` only, with the local-dev password `agentlab`.

If you use your own Postgres, `AGENTLAB_DATABASE_URL` (or `--database-url` on each command) must point at a role that can create schemas and roles. Each trial creates a schema plus two `LOGIN` roles and drops them afterwards. Results are stored in the schema `agentlab`, created on first use.

## 3. Provide an OpenRouter key

Any environment that exports `OPENROUTER_API_KEY` works:

```bash
export OPENROUTER_API_KEY=sk-or-...
```

The maintainers wrap commands in Doppler instead, which needs access to the `infra` project, `prd` config:

```bash
doppler run -p infra -c prd -- ./scripts/agents.sh
```

`scripts/demo.sh` runs agents under `doppler run -p infra -c prd --` by default. Set `DOPPLER_RUN=env` to skip Doppler and use the key already in your environment.

## 4. Build the console (optional)

The compiled console (`src/agentlab/console_dist/`) is not committed. Without it, `agentlab serve` still serves the API and shows a "frontend is not built" page at `/`. Build it once:

```bash
cd console && bun install && bun run build
```

Or skip the build and run the console from the Docker image: `docker compose up -d console` (see [Docker and the Node CLI](../guides/docker.md)).

## 5. Install TypeScript agent dependencies (optional)

Only if you run the TypeScript example agents:

```bash
(cd examples/vercel_agent && bun install)
(cd examples/http_agent && bun install)
```

## Check the install

```bash
uv run agentlab --help
```

You should see the subcommands `test`, `fork`, `conformance`, `fixture`, `serve`, `openapi`, `schema` and `import-otel`.

## Build these docs

The documentation tools live in their own dependency group:

```bash
uv run --group docs mkdocs serve
```

!!! tip
    Next: the [Quickstart](quickstart.md).
