# Docker and the Node CLI

Three ways to use Docker with AgentLab: Compose for Postgres (and optionally the console), the image for a runner without Python, and a Node wrapper that runs the image for you.

## Docker Compose

`docker-compose.yml` has two services.

| Service | What | Published on |
|---|---|---|
| `postgres` | `postgres:17-alpine`, user, password and database all `agentlab`, a `pgdata` volume, a health check | `127.0.0.1:55432` |
| `console` | Built from the `Dockerfile`; runs `serve --bind 0.0.0.0 --port 8800 --allow-no-token`; waits for a healthy Postgres | `127.0.0.1:8800` |

```bash
docker compose up -d --wait postgres      # what most people need
docker compose up -d console              # the console from the image, no frontend build needed
```

Both ports are published on host loopback only. That is why the console is allowed to run without a token inside the container: nothing outside the host can reach it. The Postgres password is a local-dev value; set a real one for shared deployments.

!!! note "What the Compose console is for"
    As shipped it is for **browsing results**. It publishes only port 8800, so agents on your host cannot reach its environment service (port 8900), it receives no `OPENROUTER_API_KEY`, and saved scenarios or target edits are written inside the container's filesystem (no volume), so they disappear when the container is recreated. To start runs from it you would also publish 8900, pass the key, point `targets.yaml` at `host.docker.internal`, and start agents with `HOST=0.0.0.0`.

## The image

```bash
docker build -t agentlab .        # from the repo root
```

Two stages: the first builds the console with bun; the second is `ghcr.io/astral-sh/uv:python3.13-bookworm-slim`, installs the locked dependencies with `--no-default-groups` (no dev, agents or docs), copies `src/`, the built console, `protocol/`, `scenarios/`, `environments/` and `targets.yaml`, and runs as an unprivileged user (uid 10001) with `agentlab` as the entrypoint (default command `--help`).

The image contains the runner and the shipped suite. It does **not** contain the example agents, which run on the host.

## The Node CLI (no Python)

`packages/cli` is a wrapper that runs the image against your current directory. It needs Docker (or OrbStack) and Node 20+.

```bash
docker build -t agentlab .                       # once, from the repo root
npm i -g ./packages/cli                          # or call the script directly
node packages/cli/bin/agentlab.mjs test scenarios --candidate my-agent --targets targets.yaml
```

Exit codes match the Python CLI (0 PASS, 1 BLOCK, 2 INSUFFICIENT_EVIDENCE, 3 usage error). If Docker is missing, it prints how to build the image and exits `3`.

What the wrapper does:

- Mounts the current directory at `/work` and runs there, so `scenarios`, `environments` and `targets.yaml` are **the ones in your directory**, not the ones baked into the image. Reports are written back to your directory.
- Runs as your uid and gid, so files it writes belong to you.
- Publishes the environment service port (8900, or `--fixture-port` / `AGENTLAB_FIXTURE_PORT`) and, for `serve`, the console port, on `127.0.0.1` only.
- Maps `host.docker.internal` to the host.
- Makes `serve` and `fixture` bind `0.0.0.0` unless you pass `--bind`, so the published ports work.
- For `serve` without a token on a loopback publish, sets `AGENTLAB_ALLOW_NO_TOKEN=1`.

Environment variables:

| Variable | Effect |
|---|---|
| `AGENTLAB_DATABASE_URL` | Passed by name. A `localhost`, `127.0.0.1` or `[::1]` host is rewritten to `host.docker.internal` |
| `OPENROUTER_API_KEY`, `AGENTLAB_CONSOLE_TOKEN` | Passed by name; the value never goes into the command line |
| `AGENTLAB_IMAGE` | Image to run (default `agentlab:latest`) |
| `AGENTLAB_PUBLISH_HOST` | Host interface for published ports (default `127.0.0.1`) |
| `AGENTLAB_FIXTURE_PORT` | Environment service port to publish (default 8900) |
| `AGENTLAB_FIXTURE_BIND` | Default `0.0.0.0` |
| `AGENTLAB_FIXTURE_URL` | Default `http://127.0.0.1:<fixture port>/` |

!!! warning
    The environment service and the console are **unauthenticated by default** (the console supports a bearer token). Widen `AGENTLAB_PUBLISH_HOST` only on trusted networks. See [Security](../operations/security.md).

## Because the runner is inside a container

- **Database:** `127.0.0.1` in the URL means the container, so the wrapper rewrites it. A Postgres reachable another way needs a URL that works from inside the container.
- **Agents on the host** must bind `HOST=0.0.0.0` to be reachable from the container, and `targets.yaml` must use `http://host.docker.internal:<port>`. The sample `allowed_hosts` already lists `host.docker.internal`.
- **Agents reach the environment service** at the published port. `AGENTLAB_FIXTURE_URL` defaults to `http://127.0.0.1:<fixture port>/`, which suits agents on the host.

More in `packages/cli/README.md`.
