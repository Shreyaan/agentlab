import asyncio
import json
import shutil
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from mcp.client.client import Client

from agentlab.environment import load_environments
from agentlab.fixture import FixturePool
from agentlab.models import ExperimentMeta
from agentlab.protocol import ToolFault
from agentlab.records import Row
from agentlab.runner import RunConfig, Runner
from agentlab.scenario import Scenario
from agentlab.store import Store

from .conftest import HOSTS, REFUND_ENV, ROOT, free_port
from .test_console import CSRF, make_client

SEED: dict[str, list[Row]] = {
    "customers": [{"id": "C-1", "name": "Ada"}],
    "orders": [{"id": "ORD-1", "customer_id": "C-1", "amount_cents": 500}],
    "settings": [{"key": "approval_limit_cents", "value": 1000}],
}
LEGACY = {
    "id": "legacy.refund",
    "version": 2,
    "fixture": {"customers": [{"id": "C-1", "name": "Ada"}], "orders": [], "approval_limit_cents": 123},
    "input": {"message": "hi"},
    "assertions": [],
}


def test_mcp_lists_and_calls_tools_through_the_same_executor(envs: FixturePool, fixture_url: str) -> None:
    fx = envs.create("t_mcp", REFUND_ENV, SEED, [ToolFault(tool="issue_refund", action="timeout_after_commit")])

    async def session() -> tuple[list[str], list[tuple[bool, str]]]:
        async with Client(f"{fixture_url}/env/t_mcp/mcp") as client:
            tools = [t.name for t in (await client.list_tools()).tools]
            refund = {"order_id": "ORD-1", "amount_cents": 500, "idempotency_key": "k"}
            calls = [
                await client.call_tool("get_order", {"order_id": "ORD-1"}),
                await client.call_tool("get_order", {"order_id": "nope"}),
                await client.call_tool("issue_refund", refund),
                await client.call_tool("issue_refund", refund),
                await client.call_tool("issue_refund", {"order_id": 5}),
            ]
            return tools, [(c.is_error, c.content[0].text) for c in calls]  # ty: ignore[unresolved-attribute]

    try:
        tools, calls = asyncio.run(session())
        assert tools == [t.name for t in REFUND_ENV.tools]
        assert json.loads(calls[0][1])["id"] == "ORD-1"
        assert calls[1:3] == [(True, '{"error": "order not found"}'), (True, '{"error": "upstream timeout"}')]
        assert not calls[3][0]
        assert json.loads(calls[3][1])["id"] == 1  # replayed by key, not refunded twice
        assert calls[4][0]
        assert fx.query("SELECT COUNT(*) FROM refunds") == [(1,)]
        assert [(e.tool, e.status) for e in fx.ledger()] == [
            ("get_order", 200),
            ("get_order", 404),
            ("issue_refund", 504),
            ("issue_refund", 201),
        ]
    finally:
        envs.drop("t_mcp")


def test_mcp_unknown_environment_is_404(fixture_url: str) -> None:
    import httpx

    assert httpx.post(f"{fixture_url}/env/nope/mcp", json={}).status_code == 404


def test_legacy_fixture_converts_to_refund_seed() -> None:
    s = Scenario.model_validate(LEGACY)
    assert s.environment == "refund@1"
    assert s.seed == {
        "customers": [{"id": "C-1", "name": "Ada"}],
        "orders": [],
        "settings": [{"key": "approval_limit_cents", "value": 123}],
    }
    assert Scenario.model_validate({**LEGACY, "fixture": {}}).seed["settings"][0]["value"] == 50_000
    assert "fixture" not in s.model_dump()


def test_legacy_history_loads_and_forks_fall_back_to_the_registry(runner: Runner, store: Store) -> None:
    meta = ExperimentMeta.model_validate(
        {"targets": {}, "scenarios": {"legacy.refund@2": LEGACY}, "repeats": 1, "fixture_url": "http://127.0.0.1:1"}
    )
    assert meta.environments == {}
    scenario = meta.scenarios["legacy.refund@2"]
    assert runner.environments_for([scenario], meta.environments) == {"refund@1": REFUND_ENV}
    with pytest.raises(ValueError, match="unknown environment"):
        runner.environments_for([scenario.model_copy(update={"environment": "ghost@1"})])


def test_experiments_pin_the_environment_spec(runner: Runner, store: Store) -> None:
    scenario = Scenario.model_validate({**LEGACY, "id": "pin.me"})
    from agentlab.client import Target

    exp = runner.run_experiment([scenario], [Target(name="down", mode="native", url=f"http://127.0.0.1:{free_port()}")])
    assert store.experiment(exp).meta.environments == {"refund@1": REFUND_ENV}


def test_runner_rejects_unknown_environment(runner: Runner) -> None:
    scenario = Scenario.model_validate(
        {"id": "g", "version": 1, "environment": "ghost@1", "input": {}, "assertions": []}
    )
    with pytest.raises(ValueError, match="ghost@1"):
        runner.plan_experiment([scenario], [])


def test_duplicate_environment_keys_are_rejected(tmp_path: Path) -> None:
    for name in ("a.yaml", "b.yaml"):
        shutil.copy(ROOT / "environments" / "refund.yaml", tmp_path / name)
    with pytest.raises(ValueError, match="duplicate"):
        load_environments(tmp_path)
    assert set(load_environments(ROOT / "environments")) == {"refund@1", "travel@1"}


@pytest.fixture
def env_client(store: Store, envs: FixturePool, fixture_url: str, tmp_path: Path, paths: tuple[str, str]) -> TestClient:
    env_dir = tmp_path / "environments"
    shutil.copytree(ROOT / "environments", env_dir)
    cfg = RunConfig(fixture_url=fixture_url, environments=str(env_dir))
    return make_client(Runner(store, envs, HOSTS, cfg), paths)


def env_draft(**overrides: object) -> dict:
    raw = yaml.safe_load((ROOT / "environments" / "travel.yaml").read_text())
    return {"environment": {**raw, "id": "trips", **overrides}}


def test_list_environments(env_client: TestClient) -> None:
    assert [e["key"] for e in env_client.get("/v1/environments").json()] == ["refund@1", "travel@1"]


def test_validate_environment(env_client: TestClient) -> None:
    ok = env_client.post("/v1/environments/validate", json=env_draft(), headers=CSRF).json()
    assert (ok["valid"], ok["key"]) == (True, "trips@1")
    assert yaml.safe_load(ok["yaml"])["id"] == "trips"

    tools = env_draft()["environment"]["tools"]
    bad_sql = [{**tools[0], "sql": "SELECT nope FROM flights"}, {**tools[1], "sql": "SELECT 1; SELECT 2"}, tools[2]]
    errors = env_client.post("/v1/environments/validate", json=env_draft(tools=bad_sql), headers=CSRF).json()["errors"]
    assert [e.split(".sql")[0] for e in errors] == [f"tools.{tools[0]['name']}", f"tools.{tools[1]['name']}"]

    ledger_peek = [{**tools[0], "sql": "SELECT * FROM ledger"}]
    peek = env_client.post("/v1/environments/validate", json=env_draft(tools=ledger_peek), headers=CSRF).json()
    assert peek["valid"] is False

    bad_ref = env_draft()
    bad_ref["environment"]["tables"][1]["columns"][1]["references"] = "ghost.id"
    assert env_client.post("/v1/environments/validate", json=bad_ref, headers=CSRF).json()["valid"] is False

    secret = env_draft(description=None, tools=[{"name": "hunter2"}])
    r = env_client.post("/v1/environments/validate", json=secret, headers=CSRF)
    assert r.json()["valid"] is False
    assert "hunter2" not in r.text
    assert env_client.post("/v1/environments/validate", content=b"{nope", headers=CSRF).json()["errors"] == [
        "body: invalid JSON"
    ]


def test_save_environment_versions_and_is_atomic(env_client: TestClient, tmp_path: Path) -> None:
    first = env_client.post("/v1/environments", json=env_draft(), headers=CSRF).json()
    assert (first["key"], first["created"]) == ("trips@1", True)
    assert first["path"] == str((tmp_path / "environments" / "trips.yaml").resolve())
    again = env_client.post("/v1/environments", json=env_draft(), headers=CSRF).json()
    assert (again["key"], again["created"]) == ("trips@1", False)
    changed = env_client.post("/v1/environments", json=env_draft(description="changed"), headers=CSRF).json()
    assert (changed["key"], changed["created"]) == ("trips@2", False)
    assert "trips@2" in [e["key"] for e in env_client.get("/v1/environments").json()]
    assert not list((tmp_path / "environments").glob("*.tmp"))
    assert env_client.post("/v1/environments", json=env_draft(id="../evil"), headers=CSRF).status_code == 422
    broken = env_draft(tools=[{**env_draft()["environment"]["tools"][0], "sql": "SELECT nope"}])
    assert env_client.post("/v1/environments", json=broken, headers=CSRF).status_code == 422
    assert env_client.post("/v1/environments", json=env_draft()).status_code == 403
    assert env_client.post("/v1/environments/validate", json=env_draft()).status_code == 403


def test_scenarios_are_validated_against_their_environment(env_client: TestClient) -> None:
    raw = yaml.safe_load((ROOT / "scenarios" / "travel_payment_timeout.yaml").read_text())
    ok = env_client.post("/v1/scenarios/validate", json={"scenario": raw}, headers=CSRF).json()
    assert (ok["valid"], ok["key"]) == (True, "travel.payment_timeout@1"), ok
    wrong = {**raw, "environment": "refund@1"}
    errors = env_client.post("/v1/scenarios/validate", json={"scenario": wrong}, headers=CSRF).json()["errors"]
    assert any("unknown tool" in e for e in errors)
    ghost = env_client.post("/v1/scenarios/validate", json={"scenario": {**raw, "environment": "x@1"}}, headers=CSRF)
    assert ghost.json()["errors"] == ["environment: unknown environment 'x@1'"]
    seed = {**raw, "seed": {"flights": [{"id": "F", "bogus": 1}]}}
    assert env_client.post("/v1/scenarios/validate", json={"scenario": seed}, headers=CSRF).json()["valid"] is False
    query = {"environment": "travel@1", "seed": raw["seed"], "query": "SELECT seats_left FROM flights"}
    assert env_client.post("/v1/scenarios/test-query", json=query, headers=CSRF).json()["value"] == 5
    dry = env_client.post(
        "/v1/scenarios/dry-run", json={"scenario": {**raw, "environment": "x@1"}, "target": "blackbox"}, headers=CSRF
    )
    assert dry.status_code == 422
