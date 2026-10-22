from typing import Literal

from agentlab.gate import decide, wilson
from agentlab.models import Trial, TrialError, TrialRecord, TrialStatus
from agentlab.protocol import ErrorCode
from agentlab.records import AssertionResult

S = "s@1"
type Check = tuple[Literal["pass", "fail", "unsupported"], bool]  # (status, critical)


def trial(target: str, status: TrialStatus, *checks: Check, repeat: int = 0) -> Trial:
    results = [
        AssertionResult(type="sql", description=f"check {i}", critical=critical, status=s)
        for i, (s, critical) in enumerate(checks)
    ]
    record = TrialRecord(assertions=results, latency_ms=10.0)
    if status == "error":
        record = TrialRecord(error=TrialError(code=ErrorCode.ADAPTER_TIMEOUT, message="slow"))
    return Trial(
        id=f"{target}{repeat}",
        experiment_id="e",
        target=target,
        scenario=S,
        repeat=repeat,
        status=status,
        record=record,
    )


def test_wilson_bounds() -> None:
    assert wilson(0, 0) == (0.0, 1.0)
    lo, hi = wilson(9, 10)
    assert 0.55 < lo < 0.6
    assert 0.98 < hi <= 1.0


def test_pass() -> None:
    assert decide([trial("c", "passed", ("pass", True))], [S], "c").status == "PASS"


def test_critical_failure_blocks_even_if_others_pass() -> None:
    d = decide([trial("c", "failed", ("pass", False), ("fail", True))], [S], "c")
    assert d.status == "BLOCK"
    assert d.block_reasons == ["critical check failed: s@1: check 1"]


def test_unsupported_critical_is_insufficient_not_pass() -> None:
    assert decide([trial("c", "passed", ("unsupported", True))], [S], "c").status == "INSUFFICIENT_EVIDENCE"


def test_noncritical_unsupported_is_a_coverage_gap() -> None:
    d = decide([trial("c", "passed", ("pass", True), ("unsupported", False))], [S], "c")
    assert d.status == "PASS"
    assert d.coverage_gaps


def test_errors_and_missing_coverage_are_insufficient() -> None:
    d = decide([trial("c", "error")], [S, "other@1"], "c")
    assert d.status == "INSUFFICIENT_EVIDENCE"
    assert any("ADAPTER_TIMEOUT" in r for r in d.insufficient_reasons)
    assert "no graded trial for other@1" in d.insufficient_reasons


def test_paired_regression_blocks() -> None:
    trials = [trial("b", "passed", ("pass", False)), trial("c", "failed", ("fail", False))]
    d = decide(trials, [S], "c", baseline="b")
    assert d.status == "BLOCK"
    assert d.paired is not None
    assert d.paired.regressions == 1
