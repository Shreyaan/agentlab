import json
import time
import uuid
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from agentlab.assertions import Decision as DecisionCheck
from agentlab.cli import main
from agentlab.console import Console, create_console
from agentlab.jobs import Jobs
from agentlab.models import ExperimentMeta, TargetInfo, TrialRecord
from agentlab.protocol import Event
from agentlab.runner import Runner
from agentlab.scenario import load_suite

from .conftest import ROOT, free_port

TEST_HOSTS = ["testserver"]  # TestClient's Host header

CSRF = {"X-AgentLab-Request": "1"}
SUITE = load_suite(ROOT / "scenarios")
SUITE_HAPPY = [s for s in SUITE if s.id == "refund.happy"]


def make_client(runner: Runner, paths: tuple[str, str], token: str | None = None) -> TestClient:
    console = Console(runner=runner, jobs=Jobs(runner), targets_path=paths[0], suite_path=paths[1], token=token)
    return TestClient(create_console(console, dist_dir=Path("missing"), allowed_hosts=TEST_HOSTS))


@pytest.fixture
def client(runner: Runner, paths: tuple[str, str]) -> TestClient:
    return make_client(runner, paths)


def wait_complete(client: TestClient, exp_id: str) -> dict:
    for _ in range(100):
        detail = client.get(f"/v1/experiments/{exp_id}").json()
        if detail["summary"]["status"] == "complete":
            return detail
        time.sleep(0.1)
    raise AssertionError(f"{exp_id} did not complete")


def stored_trial_id(runner: Runner) -> str:
    """A trial that saved checkpoint c1, written straight to the real store."""
    scenario = SUITE[0]
    meta = ExperimentMeta(
        targets={"down": TargetInfo(mode="native", url=None, version="v", manifest=None)},
        scenarios={scenario.key: scenario},
        repeats=1,
        fixture_url="http://127.0.0.1:1",
    )
    exp_id = f"exp_console_fork_{uuid.uuid4().hex[:6]}"
    runner.store.create_experiment(exp_id, meta)
    runner.store.start_trial(f"{exp_id}:t", exp_id, "down", scenario.key, 0)
    event = Event(seq=1, type="checkpoint_saved", data={"checkpoint_id": "c1"})
    runner.store.finish_trial(f"{exp_id}:t", "passed", TrialRecord(events=[event]))
    return f"{exp_id}:t"


def test_info_and_scenarios(client: TestClient) -> None:
    info = client.get("/v1/info").json()
    assert info["auth_required"] is False
    assert [s["key"] for s in client.get("/v1/scenarios").json()] == ["refund.happy@4"]


def test_targets_report_unreachable(client: TestClient) -> None:
    health = {t["name"]: t for t in client.get("/v1/targets").json()}
    assert health["down"]["reachable"] is False
    assert health["down"]["error"]
    assert health["blackbox"]["reachable"] is True


def test_run_unreachable_target_completes_insufficient(client: TestClient) -> None:
    r = client.post("/v1/experiments", json={"candidate": "down"}, headers=CSRF)
    assert r.status_code == 202
    detail = wait_complete(client, r.json()["experiment_id"])
    assert detail["experiment"]["decision"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert detail["summary"]["decision"] == "INSUFFICIENT_EVIDENCE"
    assert (detail["summary"]["planned"], detail["summary"]["finished"], detail["summary"]["errors"]) == (1, 1, 1)
    assert client.get(f"/v1/experiments/{detail['summary']['id']}/report.html").status_code == 200
    assert detail["summary"]["id"] in [e["id"] for e in client.get("/v1/experiments").json()]
    trial = client.get(f"/v1/trials/{detail['trials'][0]['id']}").json()
    assert trial["status"] == "error"


def test_run_validation(client: TestClient) -> None:
    assert client.post("/v1/experiments", json={"candidate": "nope"}, headers=CSRF).status_code == 422
    body = {"candidate": "down", "scenarios": ["missing@1"]}
    assert client.post("/v1/experiments", json=body, headers=CSRF).status_code == 422


def test_post_requires_csrf_header(client: TestClient) -> None:
    assert client.post("/v1/experiments", json={"candidate": "down"}).status_code == 403
    assert client.post("/v1/forks", json={"trial_id": "x", "checkpoint_id": "c"}).status_code == 403


def test_token_required(runner: Runner, paths: tuple[str, str]) -> None:
    client = make_client(runner, paths, token="s3cret")
    assert client.get("/v1/info").status_code == 401
    assert client.get("/v1/info", headers={"Authorization": "Bearer wrong"}).status_code == 401
    ok = client.get("/v1/info", headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 200
    assert ok.json()["auth_required"] is True
    assert client.post("/v1/experiments", json={"candidate": "down"}, headers=CSRF).status_code == 401


def test_experiment_runs_canaries_once_and_serves_them(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)  # judges error, which must abstain, not fail the run
    body = {"candidate": "down", "repeats": 2}
    exp_id = client.post("/v1/experiments", json=body, headers=CSRF).json()["experiment_id"]
    wait_complete(client, exp_id)
    canaries = client.get(f"/v1/experiments/{exp_id}/canaries").json()
    [scenario] = SUITE_HAPPY
    [check] = [a for a in scenario.assertions if isinstance(a, DecisionCheck)]
    assert len(canaries) == len(check.canaries) * len(check.judges)  # once per experiment, not per trial
    assert {c["experiment_id"] for c in canaries} == {exp_id}
    assert all(c["verdict"] == "abstain" and c["correct"] is False for c in canaries)
    assert {c["label"] for c in canaries} == {c.label for c in check.canaries}


def test_not_found(client: TestClient) -> None:
    assert client.get("/v1/experiments/nope").status_code == 404
    assert client.get("/v1/experiments/nope/report.html").status_code == 404
    assert client.get("/v1/experiments/nope/canaries").status_code == 404
    assert client.get("/v1/trials/nope:a:b:0").status_code == 404


def test_fork_errors(client: TestClient, runner: Runner) -> None:
    def fork(trial_id: str, checkpoint: str, target: str | None = None) -> int:
        body = {"trial_id": trial_id, "checkpoint_id": checkpoint, "target": target}
        return client.post("/v1/forks", json=body, headers=CSRF).status_code

    trial_id = stored_trial_id(runner)
    assert fork("missing", "c1") == 404
    assert fork(trial_id, "nope", "blackbox") == 400
    assert fork(trial_id, "c1", "blackbox") == 409
    assert fork(trial_id, "c1", "ghost") == 422


def test_frontend_not_built_and_built(runner: Runner, paths: tuple[str, str], tmp_path: Path) -> None:
    assert "bun run build" in make_client(runner, paths).get("/").text
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<p>spa</p>")
    (dist / "app.js").write_text("1")
    console = Console(runner=runner, jobs=Jobs(runner), targets_path=paths[0], suite_path=paths[1], token=None)
    built = TestClient(create_console(console, dist_dir=dist, allowed_hosts=TEST_HOSTS))
    assert built.get("/app.js").text == "1"
    assert built.get("/some/route").text == "<p>spa</p>"
    assert built.get("/../../etc/passwd").text == "<p>spa</p>"
    assert built.get("/v1/unknown").status_code == 404


def test_openapi_needs_no_database(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("AGENTLAB_DATABASE_URL", raising=False)
    assert main(["openapi"]) == 0
    assert "/v1/experiments" in json.loads(capsys.readouterr().out)["paths"]


def test_serve_refuses_public_bind_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENTLAB_CONSOLE_TOKEN", raising=False)
    assert main(["serve", "--bind", "0.0.0.0"]) == 3


def test_broken_config_is_reported_not_500(tmp_path: Path, runner: Runner) -> None:
    jobs = Jobs(runner)
    console = Console(
        runner=runner, jobs=jobs, targets_path=str(tmp_path / "missing.yaml"), suite_path=str(tmp_path), token=None
    )
    with TestClient(create_console(console, allowed_hosts=TEST_HOSTS)) as client:
        for path in ("/v1/targets", "/v1/scenarios"):
            r = client.get(path)
            assert r.status_code == 503
            assert "cannot load" in r.json()["detail"]
    jobs.shutdown()


def test_unknown_host_header_is_rejected(runner: Runner) -> None:
    # DNS rebinding: a hostile page resolving to 127.0.0.1 still sends its own Host header.
    console = Console(runner=runner, jobs=Jobs(runner), targets_path="targets.yaml", suite_path="scenarios", token=None)
    client = TestClient(create_console(console, dist_dir=Path("missing")))  # default: localhost hosts only
    assert client.get("/v1/info", headers={"host": "evil.example"}).status_code == 400
    assert client.get("/v1/info", headers={"host": "127.0.0.1:8800"}).status_code == 200


def test_target_health_and_config_errors_do_not_leak_secrets(tmp_path: Path, runner: Runner) -> None:
    targets = tmp_path / "targets.yaml"
    targets.write_text(
        yaml.safe_dump(
            {
                "allowed_hosts": ["127.0.0.1"],
                "targets": {
                    "t": {"mode": "native", "url": f"http://user:hunter2@127.0.0.1:{free_port()}/?api_key=s3cr3t"}
                },
            }
        )
    )
    console = Console(runner=runner, jobs=Jobs(runner), targets_path=str(targets), suite_path="scenarios", token=None)
    client = TestClient(create_console(console, dist_dir=Path("missing"), allowed_hosts=TEST_HOSTS))
    body = client.get("/v1/targets").text
    assert "hunter2" not in body
    assert "s3cr3t" not in body

    targets.write_text(yaml.safe_dump({"targets": {"t": {"mode": "bogus", "url": "http://u:hunter2@h/"}}}))
    r = client.get("/v1/targets")
    assert r.status_code == 503
    assert "targets.t.mode" in r.json()["detail"]
    assert "hunter2" not in r.text
