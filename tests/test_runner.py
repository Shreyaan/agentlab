from pathlib import Path

import pytest

from agentlab.cli import main
from agentlab.client import HarnessClient, Target
from agentlab.otel import parse_otlp
from agentlab.protocol import AgentLabError, ErrorCode, Event
from agentlab.runner import Runner, ledger_calls_before
from agentlab.scenario import Scenario, load_suite

from .conftest import HOSTS, ROOT, free_port

SUITE = load_suite(ROOT / "scenarios")


def test_scenarios_load() -> None:
    assert {s.id for s in SUITE} >= {"refund.timeout", "refund.happy", "refund.over_limit"}


def test_unreachable_target_is_error_not_pass(runner: Runner) -> None:
    exp = runner.run_experiment(SUITE, [Target(name="down", mode="native", url=f"http://127.0.0.1:{free_port()}")])
    trials = runner.store.trials(exp)
    assert {t.status for t in trials} == {"error"}
    assert all(t.record.error and t.record.error.code == ErrorCode.ADAPTER_ERROR for t in trials)


def test_harness_faults_need_interception(runner: Runner) -> None:
    timeout = next(s for s in SUITE if s.id == "refund.timeout")
    harness = Scenario.model_validate(
        {
            **timeout.model_dump(),
            "faults": [{"tool": "issue_refund", "action": "timeout_after_commit", "boundary": "harness"}],
        }
    )
    # A black-box HTTP target can't intercept tools; the trial must error before the agent is ever invoked.
    target = Target(name="blackbox", mode="http", url=f"http://127.0.0.1:{free_port()}/chat")
    [trial] = runner.store.trials(runner.run_experiment([harness], [target]))
    assert trial.status == "error"
    assert trial.record.error is not None
    assert trial.record.error.code == ErrorCode.CAPABILITY_UNSUPPORTED


def test_unsafe_and_observe_only_targets() -> None:
    with pytest.raises(AgentLabError) as e:
        HarnessClient(Target(name="prod", mode="http", url="https://api.example.com/chat"), HOSTS)
    assert e.value.code == ErrorCode.UNSAFE_TARGET
    m = HarnessClient(Target(name="o", mode="otel"), HOSTS).manifest()
    assert not m.capabilities.invoke


def test_ledger_calls_before_checkpoint() -> None:
    events = [
        Event(seq=1, type="tool_completed", name="get_order"),
        Event(seq=2, type="tool_failed", name="issue_refund", data={"injected": True, "committed": False}),
        Event(seq=3, type="tool_failed", name="issue_refund", data={"injected": True, "committed": True}),
        Event(seq=4, type="checkpoint_saved", data={"checkpoint_id": "c1"}),
    ]
    assert ledger_calls_before(events, "c1") == 2
    with pytest.raises(ValueError, match="not found"):
        ledger_calls_before(events, "missing")


def test_otel_parse() -> None:
    doc = {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "name": "tool",
                                "spanId": "b",
                                "startTimeUnixNano": "2",
                                "status": {"code": 2},
                                "attributes": [{"key": "gen_ai.tool.name", "value": {"stringValue": "issue_refund"}}],
                            },
                            {
                                "name": "chat",
                                "spanId": "a",
                                "startTimeUnixNano": "1",
                                "attributes": [{"key": "gen_ai.operation.name", "value": {"stringValue": "chat"}}],
                            },
                        ]
                    }
                ]
            }
        ]
    }
    assert [(e.seq, e.type, e.name) for e in parse_otlp(doc)] == [
        (1, "model_call", None),
        (2, "tool_failed", "issue_refund"),
    ]


def test_cli_usage_errors_exit_3(tmp_path: Path) -> None:
    assert main(["test", "scenarios"]) == 3  # missing --candidate
    assert main(["test", "scenarios", "--candidate", "x", "--repeats", "0"]) == 3
    assert main(["test", str(tmp_path), "--candidate", "x"]) == 3  # empty suite dir
