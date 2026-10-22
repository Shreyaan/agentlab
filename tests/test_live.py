"""End-to-end against real LLM agents over OpenRouter. Run: doppler run -p infra -c prd -- uv run pytest -m live

LLM behaviour is stochastic, so these assert the system's guarantees (every trial graded with evidence, capability
limits enforced, forks resume in a restored environment), not any particular model's pass rate.
"""

import os
import subprocess
from collections.abc import Generator

import pytest

from agentlab.client import Target
from agentlab.gate import decide
from agentlab.protocol import Manifest
from agentlab.runner import Runner
from agentlab.scenario import load_suite

from .conftest import ROOT, free_port, python_module, start_process

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.environ.get("OPENROUTER_API_KEY"), reason="needs OPENROUTER_API_KEY"),
]
SUITE = load_suite(ROOT / "scenarios")
MODEL = "openai/gpt-4.1-mini"
AGENTS = {  # name -> (mode, argv)
    "openai": ("native", python_module("examples.openai_agent.agent")),
    "langgraph": ("native", python_module("examples.langgraph_agent.agent")),
    "vercel": ("native", ["bun", "examples/vercel_agent/agent.ts"]),
    "http": ("http", ["bun", "examples/http_agent/agent.ts"]),
}


@pytest.fixture(scope="module")
def targets(fixture_url: str) -> Generator[dict[str, Target]]:
    procs: list[subprocess.Popen[bytes]] = []
    out: dict[str, Target] = {}
    try:
        for name, (mode, argv) in AGENTS.items():
            port = free_port()
            env = {"PROMPT": "careful", "MODEL": MODEL, "FIXTURE_URL": f"{fixture_url}/env/shared"}
            procs.append(start_process(argv, port, env))
            url = f"http://127.0.0.1:{port}" + ("/chat" if mode == "http" else "")
            manifest = Manifest(adapter_id=name, language="typescript") if mode == "http" else None
            out[name] = Target(name=name, mode="native" if mode == "native" else "http", url=url, manifest=manifest)
        yield out
    finally:
        for p in procs:
            p.terminate()
            p.wait(timeout=10)


def test_suite_runs_across_languages_and_frameworks(runner: Runner, targets: dict[str, Target]) -> None:
    exp = runner.run_experiment(SUITE, list(targets.values()))
    trials = runner.store.trials(exp)
    assert len(trials) == len(SUITE) * len(targets)
    assert all(t.graded for t in trials), [(t.id, t.record.error) for t in trials if not t.graded]
    for t in trials:
        assert t.record.ledger, f"{t.id}: agent made no tool calls"
        if t.target != "http":
            assert any(e.type == "model_call" for e in t.record.events), t.id
            assert t.record.usage.input_tokens, t.id
    # the black box can't report process evidence, so the critical event check can never pass silently
    assert decide(trials, list(runner.store.experiment(exp).meta.scenarios), "http").status != "PASS"


def test_langgraph_fork_resumes_in_restored_environment(runner: Runner, targets: dict[str, Target]) -> None:
    timeout = [s for s in SUITE if s.id == "refund.timeout"]
    source = runner.store.trials(runner.run_experiment(timeout, [targets["langgraph"]]))[0]
    assert source.graded
    # fork right after approval was granted, before any refund attempt
    events = source.record.events
    approval = next(e.seq for e in events if e.type == "tool_completed" and e.name == "request_approval")
    checkpoint = next(e for e in events if e.type == "checkpoint_saved" and e.seq > approval)
    checkpoint_id = str(checkpoint.data["checkpoint_id"])

    exp = runner.fork(source, runner.store.experiment(source.experiment_id), targets["langgraph"], checkpoint_id)
    [fork] = runner.store.trials(exp)
    assert fork.graded, fork.record.error
    assert fork.record.resumed_from is not None
    assert fork.record.resumed_from.checkpoint_id == checkpoint_id
    # the restored environment already holds the source's approval, and no refund yet
    assert len(fork.record.initial_state["approvals"]) == 1
    assert fork.record.initial_state["refunds"] == []
    # counterfactual without the timeout: exactly one refund
    assert len(fork.record.final_state["refunds"]) == 1


def test_harness_faults_inject_inside_ts_and_python_adapters(runner: Runner, targets: dict[str, Target]) -> None:
    timeout = next(s for s in SUITE if s.id == "refund.timeout")
    # Same scenario, but the timeout is injected by the adapter inside the agent process instead of the service.
    harness = timeout.model_copy(
        update={"faults": [f.model_copy(update={"boundary": "harness"}) for f in timeout.faults]}
    )
    exp = runner.run_experiment([harness], [targets["vercel"], targets["openai"]])
    for t in runner.store.trials(exp):
        assert t.graded, (t.id, t.record.error)
        injected = [e for e in t.record.events if e.type == "tool_failed" and e.data.get("injected")]
        assert injected, f"{t.id}: adapter did not inject the fault"
        assert injected[0].data.get("committed") is True
        # timeout_after_commit: the first issue_refund really reached the environment and was committed
        first = next(e for e in t.record.ledger if e.tool == "issue_refund")
        assert first.committed
        assert first.status < 400
