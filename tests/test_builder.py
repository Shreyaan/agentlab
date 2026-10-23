from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from agentlab.runner import Runner

from .conftest import ROOT
from .test_console import CSRF, make_client, wait_complete


@pytest.fixture
def client(runner: Runner, paths: tuple[str, str]) -> TestClient:
    return make_client(runner, paths)


def draft(scenario_id: str = "builder.demo", **overrides: object) -> dict:
    raw = yaml.safe_load((ROOT / "scenarios" / "refund_happy.yaml").read_text())
    return {"scenario": {**raw, "id": scenario_id, **overrides}}


def test_builder_info(client: TestClient) -> None:
    info = client.get("/v1/builder").json()
    assert "issue_refund" in info["tools"]
    assert info["seed_columns"]["orders"] == ["id", "customer_id", "amount_cents"]
    assert {"sql", "decision", "tool_order"} <= set(info["assertion_types"])
    assert "output_matches" not in info["assertion_types"]
    assert info["judge_models"] == ["typesafe/jev-1.14", "openai/gpt-6-luna-decisions"]


def test_validate_reports_errors_without_echoing_input(client: TestClient) -> None:
    body = draft(input={"message": "hunter2"}, assertions=[{"type": "bogus", "query": "hunter2"}, {"type": "sql"}])
    r = client.post("/v1/scenarios/validate", json=body, headers=CSRF)
    assert r.status_code == 200
    out = r.json()
    assert out["valid"] is False
    assert out["errors"]
    assert "hunter2" not in r.text
    assert all(": " in e for e in out["errors"])
    assert client.post("/v1/scenarios/validate", content=b"{nope", headers=CSRF).json()["errors"] == [
        "body: invalid JSON"
    ]


def test_validate_semantic_errors(client: TestClient) -> None:
    body = draft(
        faults=[{"tool": "nope", "action": "timeout_after_commit"}],
        assertions=[
            {"type": "sql", "query": "SELECT * FROM missing_table", "equals": 1},
            {"type": "forbidden_tool", "name": "ghost"},
            {"type": "sql", "query": "DELETE FROM orders", "equals": 1},
        ],
    )
    errors = client.post("/v1/scenarios/validate", json=body, headers=CSRF).json()["errors"]
    assert any(e.startswith("faults.0.tool") for e in errors)
    assert any(e.startswith("assertions.1.name") for e in errors)
    body["scenario"]["faults"] = []
    body["scenario"]["assertions"] = body["scenario"]["assertions"][::2]
    errors = client.post("/v1/scenarios/validate", json=body, headers=CSRF).json()["errors"]
    assert len(errors) == 2
    assert all(e.startswith("assertions.") for e in errors)
    bad_seed = draft(fixture={"orders": [{"id": "O", "bogus": 1}]})
    assert client.post("/v1/scenarios/validate", json=bad_seed, headers=CSRF).json()["valid"] is False


def test_validate_ok_with_calibration_sql(client: TestClient) -> None:
    out = client.post("/v1/scenarios/validate", json=draft(), headers=CSRF).json()
    assert out["valid"] is True
    assert out["key"] == "builder.demo@3"
    normalized = yaml.safe_load(out["yaml"])
    assert normalized["assertions"][1]["type"] == "decision"
    assert "slices" in normalized
    assert "source" not in normalized  # unset defaults are omitted


def test_save_new_bump_and_identical_noop(client: TestClient, paths: tuple[str, str]) -> None:
    first = client.post("/v1/scenarios", json=draft(), headers=CSRF)
    assert first.status_code == 200
    assert first.json() == {
        "key": "builder.demo@3",
        "path": str(Path(paths[1]).resolve() / "builder.demo.yaml"),
        "created": True,
    }
    again = client.post("/v1/scenarios", json=draft(), headers=CSRF).json()
    assert (again["key"], again["created"]) == ("builder.demo@3", False)
    changed = client.post("/v1/scenarios", json=draft(risk_tier="critical"), headers=CSRF).json()
    assert (changed["key"], changed["created"]) == ("builder.demo@4", False)
    assert "builder.demo@4" in [s["key"] for s in client.get("/v1/scenarios").json()]
    assert not list(Path(paths[1]).glob("*.tmp"))
    # an existing hand-written file is updated in place, not duplicated under another name
    bumped = client.post("/v1/scenarios", json=draft("refund.happy", risk_tier="high"), headers=CSRF).json()
    assert bumped["key"] == "refund.happy@4"
    assert bumped["path"].endswith("refund_happy.yaml")


def test_save_rejects_bad_ids_and_semantics(client: TestClient, paths: tuple[str, str]) -> None:
    for bad in ("../evil", "a/b", "Upper", "", "x" * 65, ".hidden"):
        assert client.post("/v1/scenarios", json=draft(bad), headers=CSRF).status_code == 422, bad
    assert not (Path(paths[1]).parent / "evil.yaml").exists()
    broken = draft(assertions=[{"type": "forbidden_tool", "name": "ghost"}])
    assert client.post("/v1/scenarios", json=broken, headers=CSRF).status_code == 422


def test_test_query(client: TestClient) -> None:
    seed = {"orders": [{"id": "O-1", "customer_id": "C", "amount_cents": 5}]}
    ok = client.post(
        "/v1/scenarios/test-query", json={"seed": seed, "query": "SELECT COUNT(*) FROM orders"}, headers=CSRF
    )
    assert ok.json() == {"ok": True, "rows": [[1]], "value": 1, "error": None}
    rows = client.post(
        "/v1/scenarios/test-query", json={"seed": seed, "query": "SELECT id, amount_cents FROM orders"}, headers=CSRF
    ).json()
    assert rows["rows"] == [["O-1", 5]]
    assert rows["value"] is None
    for query in ("DELETE FROM orders", "SELEKT 1"):
        bad = client.post("/v1/scenarios/test-query", json={"seed": seed, "query": query}, headers=CSRF).json()
        assert bad["ok"] is False
        assert bad["error"]


def test_dry_run_is_accepted_for_unsaved_scenario(client: TestClient) -> None:
    r = client.post("/v1/scenarios/dry-run", json={**draft("builder.unsaved"), "target": "blackbox"}, headers=CSRF)
    assert r.status_code == 202
    detail = wait_complete(client, r.json()["experiment_id"])
    assert list(detail["experiment"]["meta"]["scenarios"]) == ["builder.unsaved@3"]
    assert client.post("/v1/scenarios/dry-run", json={**draft(), "target": "ghost"}, headers=CSRF).status_code == 422


def test_target_test_put_delete(client: TestClient, paths: tuple[str, str]) -> None:
    spec = {"mode": "http", "url": "http://127.0.0.1:9/chat", "version": "v2"}
    health = client.post("/v1/targets/test", json={"name": "new", "spec": spec}, headers=CSRF).json()
    assert health["reachable"] is True  # http targets declare their manifest
    assert "new" not in [t["name"] for t in client.get("/v1/targets").json()]
    blocked = client.post(
        "/v1/targets/test",
        json={"name": "x", "spec": {**spec, "url": "http://user:hunter2@evil.example/"}},
        headers=CSRF,
    )
    assert blocked.json()["reachable"] is False
    assert "hunter2" not in blocked.text

    saved = client.put("/v1/targets/new", json={"name": "new", "spec": spec}, headers=CSRF)
    assert saved.json() == {"name": "new", "created": True}
    assert client.put("/v1/targets/new", json={"name": "new", "spec": spec}, headers=CSRF).json()["created"] is False
    assert {"down", "blackbox", "new"} <= {t["name"] for t in client.get("/v1/targets").json()}

    assert client.put("/v1/targets/other", json={"name": "new", "spec": spec}, headers=CSRF).status_code == 422
    evil = {"name": "evil", "spec": {"mode": "http", "url": "http://example.com/chat"}}
    assert client.put("/v1/targets/evil", json=evil, headers=CSRF).status_code == 422

    assert client.delete("/v1/targets/new", headers=CSRF).status_code == 204
    assert client.delete("/v1/targets/new", headers=CSRF).status_code == 404
    kept = yaml.safe_load(Path(paths[0]).read_text())
    assert set(kept["targets"]) == {"down", "blackbox"}


def test_put_preserves_allowed_hosts(client: TestClient, paths: tuple[str, str]) -> None:
    path = Path(paths[0])
    data = yaml.safe_load(path.read_text())
    path.write_text(yaml.safe_dump({"allowed_hosts": ["127.0.0.1", "agent.internal"], **data}))
    spec = {"mode": "http", "url": "http://agent.internal/chat"}
    assert client.put("/v1/targets/internal", json={"name": "internal", "spec": spec}, headers=CSRF).status_code == 200
    saved = yaml.safe_load(path.read_text())
    assert saved["allowed_hosts"] == ["127.0.0.1", "agent.internal"]
    assert {"down", "blackbox", "internal"} == set(saved["targets"])


def test_writes_need_csrf_header_and_token(client: TestClient, runner: Runner, paths: tuple[str, str]) -> None:
    spec = {"name": "t", "spec": {"mode": "otel"}}
    assert client.put("/v1/targets/t", json=spec).status_code == 403
    assert client.delete("/v1/targets/down").status_code == 403
    for path in (
        "/v1/scenarios",
        "/v1/scenarios/validate",
        "/v1/scenarios/test-query",
        "/v1/scenarios/dry-run",
        "/v1/targets/test",
    ):
        assert client.post(path, json={}).status_code == 403, path
    secured = make_client(runner, paths, token="s3cret")
    assert secured.put("/v1/targets/t", json=spec, headers=CSRF).status_code == 401
    assert secured.delete("/v1/targets/down", headers=CSRF).status_code == 401
    assert secured.get("/v1/judges").status_code == 401


def test_judges_endpoint(client: TestClient) -> None:
    assert isinstance(client.get("/v1/judges").json(), list)


def test_put_keeps_leading_comment_block(client: TestClient, paths: tuple[str, str]) -> None:
    path = Path(paths[0])
    path.write_text("# Harnesses under test.\n# Only allowed hosts may be mutated.\n" + path.read_text())
    spec = {"mode": "http", "url": "http://127.0.0.1:1/chat"}
    assert client.put("/v1/targets/extra", json={"name": "extra", "spec": spec}, headers=CSRF).status_code == 200
    assert path.read_text().startswith("# Harnesses under test.\n# Only allowed hosts may be mutated.\n")
