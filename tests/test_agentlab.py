import importlib.util
import socket
from pathlib import Path

import httpx
import pytest

from agentlab.client import HarnessClient, Target
from agentlab.fixture import Fault, Fixture, Seed, create_app, serve_in_thread
from agentlab.gate import decide, wilson
from agentlab.otel import parse_otlp
from agentlab.protocol import AgentLabError, ErrorCode, Manifest
from agentlab.runner import RunConfig, run_experiment
from agentlab.scenario import load_suite
from agentlab.store import Store

ROOT = Path(__file__).parent.parent
HOSTS = ["127.0.0.1"]
SEED = Seed(customers=[{"id": "C-1", "name": "Ada"}], orders=[{"id": "ORD-1", "customer_id": "C-1", "amount_cents": 500}])


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def env():
    fx, port = Fixture(), free_port()
    server = serve_in_thread(create_app(fx), port)
    yield fx, f"http://127.0.0.1:{port}"
    server.should_exit = True


def start_python_agent(variant: str) -> str:
    """Load the reference agent from examples/ (not a package) and serve one variant in-process."""
    spec = importlib.util.spec_from_file_location(f"agent_{variant}", ROOT / "examples/python_agent/agent.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.VARIANT = variant
    from agentlab.adapter import create_app as adapter_app
    from agentlab.protocol import Capabilities

    port = free_port()
    manifest = Manifest(adapter_id=f"py-{variant}", language="python", capabilities=Capabilities(observe="native_events"))
    serve_in_thread(adapter_app(manifest, mod.handle), port)
    return f"http://127.0.0.1:{port}"


@pytest.fixture(scope="module")
def agents():
    return {v: start_python_agent(v) for v in ("buggy", "fixed")}


def test_timeout_after_commit_commits_then_fails(env):
    fx, url = env
    fx.reset(SEED, [Fault(tool="issue_refund", action="timeout_after_commit")])
    body = {"order_id": "ORD-1", "amount_cents": 500}
    assert httpx.post(f"{url}/refunds", json=body).status_code == 504
    assert httpx.post(f"{url}/refunds", json=body).status_code == 201
    assert fx.query("SELECT COUNT(*) FROM refunds") == [(2,)]
    assert [e["status"] for e in fx.ledger()] == [504, 201]


def test_idempotency_key_dedupes(env):
    fx, url = env
    fx.reset(SEED)
    for _ in range(2):
        httpx.post(f"{url}/refunds", json={"order_id": "ORD-1", "amount_cents": 500}, headers={"Idempotency-Key": "k"})
    assert fx.query("SELECT COUNT(*) FROM refunds") == [(1,)]


def test_assertion_queries_are_read_only(env):
    fx, _ = env
    fx.reset(SEED)
    with pytest.raises(Exception):
        fx.query("DELETE FROM orders")
    assert fx.query("SELECT COUNT(*) FROM orders") == [(1,)]


def test_reset_restores_identical_state(env):
    fx, url = env
    fx.reset(SEED)
    before = fx.state()
    httpx.delete(f"{url}/customers/C-1")
    fx.reset(SEED)
    assert fx.state() == before and fx.ledger() == []


def test_unsafe_target_rejected():
    with pytest.raises(AgentLabError) as e:
        HarnessClient(Target(name="prod", mode="http", url="https://api.example.com/chat"), HOSTS)
    assert e.value.code == ErrorCode.UNSAFE_TARGET


def test_otel_target_cannot_be_invoked():
    m = HarnessClient(Target(name="o", mode="otel"), HOSTS).manifest()
    assert not m.capabilities.invoke and m.capabilities.observe == "otel_partial"


def test_wilson_bounds():
    assert wilson(0, 0) == (0.0, 1.0)
    lo, hi = wilson(9, 10)
    assert 0.55 < lo < 0.6 and 0.98 < hi <= 1.0


def test_otel_parse():
    doc = {"resourceSpans": [{"scopeSpans": [{"spans": [
        {"name": "tool", "spanId": "b", "startTimeUnixNano": "2", "status": {"code": 2},
         "attributes": [{"key": "gen_ai.tool.name", "value": {"stringValue": "issue_refund"}}]},
        {"name": "chat", "spanId": "a", "startTimeUnixNano": "1",
         "attributes": [{"key": "gen_ai.operation.name", "value": {"stringValue": "chat"}}]},
    ]}]}]}
    assert [(e.seq, e.type, e.name) for e in parse_otlp(doc)] == [(1, "model_call", None), (2, "tool_failed", "issue_refund")]


def run(env, tmp_path, targets, candidate, baseline=None):
    fx, url = env
    scenarios = load_suite(ROOT / "scenarios")
    store = Store(tmp_path / "t.db")
    exp = run_experiment(store, fx, scenarios, targets, HOSTS, RunConfig(fixture_url=url, repeats=2))
    trials = store.trials(exp)
    return decide(trials, [s.key for s in scenarios], candidate, baseline), trials


def test_e2e_buggy_blocked_fixed_passes(env, agents, tmp_path):
    targets = [Target(name=v, mode="native", url=u) for v, u in agents.items()]
    d, trials = run(env, tmp_path, targets, candidate="fixed", baseline="buggy")
    assert d["status"] == "PASS", d
    assert d["paired"]["fixes"] > 0 and d["paired"]["regressions"] == 0
    assert all(t["status"] != "running" for t in trials)

    d_buggy = decide(trials, sorted({t["scenario"] for t in trials}), "buggy")
    assert d_buggy["status"] == "BLOCK"
    assert any("no duplicate side effect" in r for r in d_buggy["block_reasons"])
    assert any("approval" in r for r in d_buggy["block_reasons"])
    dup = next(t for t in trials if t["target"] == "buggy" and t["scenario"] == "refund.timeout@1")
    assert len(dup["record"]["state_diff"]["refunds"]["added"]) == 2
    assert dup["record"]["agent_status"] == "completed"  # persuasive reply, wrong state


def test_e2e_blackbox_without_events_is_insufficient_evidence(env, agents, tmp_path, monkeypatch):
    # Same fixed agent, declared as black-box HTTP-style: no native events, so the critical process check can't run.
    t = Target(name="fixed-opaque", mode="native", url=agents["fixed"])
    client = HarnessClient(t, HOSTS)
    client.manifest = lambda: Manifest(adapter_id="opaque", language="python")  # observe="none"
    monkeypatch.setattr("agentlab.runner.HarnessClient", lambda target, hosts: client)
    d, _ = run(env, tmp_path, [t], candidate="fixed-opaque")
    assert d["status"] == "INSUFFICIENT_EVIDENCE", d
    assert any("unsupported" in r for r in d["insufficient_reasons"])


def test_unreachable_target_is_error_not_pass(env, tmp_path):
    t = Target(name="down", mode="native", url=f"http://127.0.0.1:{free_port()}")
    d, trials = run(env, tmp_path, [t], candidate="down")
    assert d["status"] == "INSUFFICIENT_EVIDENCE"
    assert {tr["status"] for tr in trials} == {"error"}


def test_crashing_grader_is_unsupported_not_fail(env):
    from agentlab.assertions import Evidence, Sql, grade, Budget
    from agentlab.protocol import Capabilities, Usage

    fx, _ = env
    fx.reset(SEED)
    ev = Evidence(fixture=fx, ledger=[], events=[], output="", capabilities=Capabilities(), latency_ms=1, usage=Usage())
    [r] = grade([Sql(type="sql", query="DELETE FROM orders", equals=0, critical=True)], Budget(), ev)
    assert r.status == "unsupported" and "grader error" in r.detail


def test_cli_usage_errors_exit_3():
    from agentlab.cli import main

    assert main(["test", "scenarios"]) == 3  # missing --candidate
    assert main(["test", "scenarios", "--candidate", "x", "--repeats", "0"]) == 3


def test_persisted_records_are_redacted(tmp_path):
    store = Store(tmp_path / "r.db")
    store.create_experiment("e", {"url": "http://user:pw@127.0.0.1:1/x?api_key=abc123&page=2"})
    store.start_trial("t", "e", "a", "s", 0)
    store.finish_trial("t", "error", {"error": {"message": "HTTP 401 Bearer eyJhbGciOi.x.y sk-live_ABCDEFGHIJKLMNOPQRST"},
                                      "headers": {"Authorization": "Bearer z"}})
    meta, rec = store.experiment("e")["meta"], store.trials("e")[0]["record"]
    assert meta["url"] == "http://[REDACTED]@127.0.0.1:1/x?api_key=[REDACTED]&page=2"
    assert "eyJ" not in rec["error"]["message"] and "sk-live" not in rec["error"]["message"]
    assert rec["headers"]["Authorization"] == "[REDACTED]"


def test_redaction_is_linear_on_hostile_input():
    import time
    from agentlab.store import redact

    started = time.perf_counter()
    redact("?" * 50_000 + "token" + "&" * 50_000)
    assert time.perf_counter() - started < 0.5


@pytest.mark.parametrize("raw, leaked", [
    ("http://h/x?a=1?token=s3cr3t", "s3cr3t"),          # benign value must not swallow the next param
    ("http://h/x?api%5Fkey=s3cr3t&p=2", "s3cr3t"),      # URL-encoded name
    ("http://h/x?auth[token]=s3cr3t#frag", "s3cr3t"),   # bracketed name
    ("http://h/x?q=1&Signature=s3cr3t", "s3cr3t"),
])
def test_query_secrets_redacted(raw, leaked):
    from agentlab.store import redact

    assert leaked not in redact(raw)


def test_benign_query_params_untouched():
    from agentlab.store import redact

    assert redact("http://h/x?page=2&sort=asc#top") == "http://h/x?page=2&sort=asc#top"
