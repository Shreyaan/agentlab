"""Shared test infrastructure: a real Postgres (Testcontainers) and a real fixture service. Nothing is mocked."""

import os
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Generator
from pathlib import Path

import httpx
import pytest
import yaml
from testcontainers.community.postgres import PostgresContainer

from agentlab.db import Pool, open_pool
from agentlab.environment import load_environments
from agentlab.fixture import FixturePool, create_app, serve_in_thread
from agentlab.runner import RunConfig, Runner
from agentlab.store import Store

ROOT = Path(__file__).parent.parent
HOSTS = ["127.0.0.1"]
ENVIRONMENTS = load_environments(ROOT / "environments")
REFUND_ENV, TRAVEL_ENV = ENVIRONMENTS["refund@1"], ENVIRONMENTS["travel@1"]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def database_url() -> Generator[str]:
    if url := os.environ.get("AGENTLAB_TEST_DATABASE_URL"):  # reuse an existing Postgres in CI if provided
        yield url
        return
    with PostgresContainer("postgres:17-alpine", driver=None) as pg:
        yield pg.get_connection_url()


@pytest.fixture(scope="session")
def db(database_url: str) -> Generator[Pool]:
    pool = open_pool(database_url, max_size=30)
    yield pool
    pool.close()


@pytest.fixture(scope="session")
def envs(db: Pool) -> FixturePool:
    return FixturePool(db)


@pytest.fixture(scope="session")
def fixture_url(envs: FixturePool) -> Generator[str]:
    port = free_port()
    server = serve_in_thread(create_app(envs), port)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True


@pytest.fixture(scope="session")
def store(db: Pool) -> Store:
    return Store(db)


@pytest.fixture
def runner(store: Store, envs: FixturePool, fixture_url: str) -> Runner:
    return Runner(
        store, envs, HOSTS, RunConfig(fixture_url=fixture_url, concurrency=4, environments=str(ROOT / "environments"))
    )


@pytest.fixture
def paths(tmp_path: Path) -> tuple[str, str]:
    suite = tmp_path / "suite"
    suite.mkdir()
    shutil.copy(ROOT / "scenarios" / "refund_happy.yaml", suite)
    targets = tmp_path / "targets.yaml"
    targets.write_text(
        yaml.dump(
            {
                "targets": {
                    "down": {"mode": "native", "url": f"http://127.0.0.1:{free_port()}"},
                    "blackbox": {"mode": "http", "url": f"http://127.0.0.1:{free_port()}/chat"},
                }
            }
        )
    )
    return str(targets), str(suite)


def start_process(args: list[str], port: int, env: dict[str, str]) -> subprocess.Popen[bytes]:
    """Start a real agent process and wait until its port answers HTTP."""
    proc = subprocess.Popen(args, cwd=ROOT, env={**os.environ, **env, "PORT": str(port)})
    deadline = time.time() + 60
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"{args} exited with {proc.returncode}")
        try:
            httpx.get(f"http://127.0.0.1:{port}/", timeout=1)
            return proc
        except httpx.HTTPError:
            time.sleep(0.3)
    proc.kill()
    raise RuntimeError(f"{args} did not start on port {port}")


def python_module(module: str) -> list[str]:
    return [sys.executable, "-m", module]
