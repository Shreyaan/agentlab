FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

# Dependencies first so the layer caches until the lock file changes.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ ./src/
COPY protocol/ ./protocol/
COPY scenarios/ ./scenarios/
COPY targets.yaml ./
RUN uv sync --frozen --no-dev

# Runs as an unprivileged user; .agentlab/ (db and reports) must be writable by it.
RUN useradd --system --uid 10001 --no-create-home agentlab \
 && mkdir -p /app/.agentlab \
 && chown agentlab /app/.agentlab

ENV PATH="/app/.venv/bin:$PATH"
USER agentlab

ENTRYPOINT ["agentlab"]
CMD ["--help"]
