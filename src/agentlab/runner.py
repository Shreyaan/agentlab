"""Runs scenarios against harnesses: reset fixture -> invoke -> collect evidence -> grade -> persist."""

import time
import uuid
from dataclasses import dataclass

from agentlab.assertions import Evidence, grade
from agentlab.client import HarnessClient, Target
from agentlab.fixture import Fixture
from agentlab.protocol import AgentLabError, ErrorCode, Environment, InvokeRequest, Manifest, new_traceparent
from agentlab.scenario import Scenario
from agentlab.store import Store

Connection = tuple[HarnessClient, Manifest] | AgentLabError


@dataclass
class RunConfig:
    fixture_url: str
    repeats: int = 1
    deadline_ms: int = 60_000


def state_diff(before: dict[str, list[dict]], after: dict[str, list[dict]]) -> dict[str, dict]:
    diff = {}
    for table in after:
        old, new = [str(r) for r in before.get(table, [])], [str(r) for r in after[table]]
        added = [r for r, s in zip(after[table], new) if s not in old]
        removed = [r for r, s in zip(before.get(table, []), old) if s not in new]
        if added or removed:
            diff[table] = {"added": added, "removed": removed}
    return diff


def _manifest_json(conn: Connection) -> dict | None:
    return None if isinstance(conn, AgentLabError) else conn[1].model_dump(mode="json")


def run_experiment(store: Store, fixture: Fixture, scenarios: list[Scenario], targets: list[Target],
                   allowed_hosts: list[str], cfg: RunConfig) -> str:
    exp_id = f"exp_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    conns: dict[str, Connection] = {}
    for t in targets:
        try:
            client = HarnessClient(t, allowed_hosts)
            m = client.manifest()
            if not m.capabilities.invoke:
                raise AgentLabError(ErrorCode.CAPABILITY_UNSUPPORTED, f"{t.name} is observe-only; it cannot be invoked")
            conns[t.name] = (client, m)
        except AgentLabError as exc:
            conns[t.name] = exc
    store.create_experiment(exp_id, {
        "targets": {t.name: {"mode": t.mode, "url": t.url, "version": t.version, "manifest": _manifest_json(conns[t.name])} for t in targets},
        "scenarios": [s.key for s in scenarios], "repeats": cfg.repeats, "fixture_url": cfg.fixture_url,
    })
    # Same scenario+repeat runs back-to-back across targets so paired comparisons share identical initial state.
    for scenario in scenarios:
        for repeat in range(cfg.repeats):
            for t in targets:
                run_trial(store, fixture, exp_id, scenario, repeat, t, conns[t.name], cfg)
    return exp_id


def run_trial(store: Store, fixture: Fixture, exp_id: str, scenario: Scenario, repeat: int, target: Target,
              conn: Connection, cfg: RunConfig) -> None:
    trial_id = f"{exp_id}:{target.name}:{scenario.key}:{repeat}"
    store.start_trial(trial_id, exp_id, target.name, scenario.key, repeat)
    if isinstance(conn, AgentLabError):
        store.finish_trial(trial_id, "error", {"error": {"code": conn.code, "message": conn.message}})
        return
    client, manifest = conn

    fixture.reset(scenario.fixture, scenario.faults)
    initial = fixture.state()
    req = InvokeRequest(
        trial_id=trial_id, scenario_version=scenario.key, system_version=target.version,
        environment=Environment(id=f"fixture:{trial_id}", base_url=cfg.fixture_url),
        idempotency_key=f"{trial_id}:invoke", input=scenario.input, deadline_ms=cfg.deadline_ms,
        traceparent=new_traceparent(),
    )
    started = time.perf_counter()
    try:
        resp = client.invoke(req)
    except AgentLabError as exc:
        store.finish_trial(trial_id, "error", {"error": {"code": exc.code, "message": exc.message},
                                               "ledger": fixture.ledger(), "initial_state": initial})
        return
    latency_ms = (time.perf_counter() - started) * 1000

    ledger, final = fixture.ledger(), fixture.state()
    ev = Evidence(fixture=fixture, ledger=ledger, events=resp.events, output=resp.output,
                  capabilities=manifest.capabilities, latency_ms=latency_ms, usage=resp.usage)
    results = grade(scenario.assertions, scenario.budget, ev)
    status = "failed" if any(r.status == "fail" for r in results) else "passed"
    store.finish_trial(trial_id, status, {
        "run_id": resp.run_id, "agent_status": resp.status, "output": resp.output,
        "events": [e.model_dump(mode="json") for e in resp.events], "ledger": ledger,
        "initial_state": initial, "final_state": final, "state_diff": state_diff(initial, final),
        "assertions": [r.model_dump() for r in results], "latency_ms": latency_ms, "usage": resp.usage.model_dump(),
    })
