# Stage 1: build the operator console (static files).
FROM oven/bun:1.3.14 AS console
WORKDIR /build/console
COPY console/package.json console/bun.lock ./
RUN bun install --frozen-lockfile
COPY console/ ./
RUN bun run build  # writes to ../src/agentlab/console_dist

# Stage 2: the runner + console server.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

# Dependencies first so the layer caches until the lock file changes.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-default-groups --no-install-project

COPY src/ ./src/
COPY --from=console /build/src/agentlab/console_dist/ ./src/agentlab/console_dist/
COPY protocol/ ./protocol/
COPY scenarios/ ./scenarios/
COPY environments/ ./environments/
COPY targets.yaml ./
RUN uv sync --frozen --no-default-groups

# Runs as an unprivileged user; .agentlab/ (reports) must be writable by it. Results live in Postgres.
RUN useradd --system --uid 10001 --no-create-home agentlab \
 && mkdir -p /app/.agentlab \
 && chown agentlab /app/.agentlab

ENV PATH="/app/.venv/bin:$PATH"
USER agentlab

ENTRYPOINT ["agentlab"]
CMD ["--help"]
