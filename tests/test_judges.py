import uuid

import pytest

from agentlab.assertions import Budget, Decision, Evidence, cap_state, grade, judge_state
from agentlab.fixture import FixturePool, Seed
from agentlab.judges import ChoiceQuestion, NoulQuestion
from agentlab.models import ExperimentMeta, TrialRecord
from agentlab.protocol import Capabilities, JsonObject, Usage
from agentlab.records import AssertionResult, JudgeAnswer, JudgeStats, JudgeVerdict
from agentlab.store import Store
from agentlab.verdicts import ChoiceRule, NoulRule, ScoreRule, combine, is_calibrated, uncalibrated_reason, vote

# Shapes as returned by the Decisions API
NOUL_YES: JsonObject = {"type": "noul", "noul": 0.97}
NOUL_NO: JsonObject = {"type": "noul", "noul": 0.03}
NOUL_MID: JsonObject = {"type": "noul", "noul": 0.5}
CHOICE: JsonObject = {"type": "choice", "choice": "duplicated", "confidence": 1.0, "probabilities": {"duplicated": 1.0}}
SCORE: JsonObject = {"type": "score", "score": 2, "confidence": 0.95, "legend": {"0": "rude", "2": "polite"}}


def test_noul_thresholds_and_min_confidence() -> None:
    rule = NoulRule(noul_at_least=0.5)
    assert vote(rule, 0.8, NOUL_YES) == "pass"
    assert vote(rule, 0.8, NOUL_NO) == "fail"
    assert vote(rule, 0.8, NOUL_MID) == "abstain"
    assert vote(rule, 0.8, {"type": "noul", "noul": 0.85}) == "pass"
    assert vote(rule, 0.9, {"type": "noul", "noul": 0.85}) == "abstain"
    assert vote(NoulRule(noul_at_least=0.95), 0.8, {"type": "noul", "noul": 0.9}) == "abstain"


def test_choice_and_score_rules() -> None:
    rule = ChoiceRule(choices=["refunded_once"])
    assert vote(rule, 0.8, CHOICE) == "fail"
    assert vote(ChoiceRule(choices=["duplicated"]), 0.8, CHOICE) == "pass"
    assert vote(rule, 0.8, {**CHOICE, "confidence": 0.5}) == "abstain"
    assert vote(ScoreRule(score_at_least=2), 0.8, SCORE) == "pass"
    assert vote(ScoreRule(score_at_least=3), 0.8, SCORE) == "fail"
    assert vote(ScoreRule(score_at_least=2), 0.99, SCORE) == "abstain"


def test_malformed_or_error_answers_abstain() -> None:
    assert vote(NoulRule(noul_at_least=0.5), 0.8, {"type": "error", "error": "HTTP 500"}) == "abstain"
    assert vote(NoulRule(noul_at_least=0.5), 0.8, CHOICE) == "abstain"
    assert vote(ChoiceRule(choices=["a"]), 0.8, {"type": "choice", "choice": "a"}) == "abstain"


def test_cascade_escalates_on_abstain_and_jury_needs_unanimity() -> None:
    assert combine("cascade", ["abstain", "pass"]) == "pass"
    assert combine("cascade", ["fail", "pass"]) == "fail"
    assert combine("cascade", ["abstain", "abstain"]) == "abstain"
    assert combine("jury", ["pass", "pass"]) == "pass"
    assert combine("jury", ["pass", "fail"]) == "abstain"
    assert combine("jury", ["pass", "abstain"]) == "abstain"


def stats(model: str, samples: int, correct: int) -> JudgeStats:
    return JudgeStats(
        model=model,
        samples=samples,
        correct=correct,
        accuracy=correct / samples if samples else None,
        cost_usd=None,
        calibrated=is_calibrated(samples, correct),
    )


def test_calibration_gate_downgrade() -> None:
    assert uncalibrated_reason(["m"], [stats("m", 20, 18)]) is None
    reason = uncalibrated_reason(["m"], [stats("m", 12, 10)])
    assert reason is not None
    assert "judge not yet calibrated: 0.83 on 12 samples" in reason
    assert "evidence-reading" in reason
    assert uncalibrated_reason(["m"], [stats("m", 40, 30)]) is not None  # 75%
    assert uncalibrated_reason(["unseen"], []) is not None
    assert uncalibrated_reason(["a", "b"], [stats("a", 30, 30), stats("b", 5, 5)]) is not None


def evidence(fixture, judge_stats: list[JudgeStats]) -> Evidence:
    return Evidence(
        fixture=fixture,
        ledger=[],
        events=[],
        output="Your refund was issued once.",
        capabilities=Capabilities(),
        latency_ms=1,
        usage=Usage(),
        input={"message": "refund ORD-1"},
        judge_stats=judge_stats,
    )


def decision(**kw) -> Decision:
    return Decision(
        question=NoulQuestion(instructions="Is the reply honest?", criteria={"true": "honest", "false": "dishonest"}),
        pass_rule=NoulRule(noul_at_least=0.5),
        calibration={
            "question": ChoiceQuestion(instructions="Refund count?", criteria={"none": "0", "one": "1"}),
            "truth_sql": "SELECT 'none'",
        },
        **kw,
    )


def test_missing_key_abstains_and_never_crashes(envs: FixturePool, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    env_id = f"judge_{uuid.uuid4().hex[:8]}"
    fx = envs.create(env_id, Seed())
    try:
        d = decision(critical=True)
        [result] = grade([d], Budget(), evidence(fx, []), faults_active=False)
    finally:
        envs.drop(env_id)
    assert result.status == "unsupported"
    assert result.judge is not None
    assert result.judge.verdict == "abstain"
    assert [j.model for j in result.judge.judges] == [
        "typesafe/jev-1.14",
        "openai/gpt-6-luna-decisions",
    ]  # cascade asked both
    assert result.judge.judges[0].answer["type"] == "error"
    assert result.judge.calibration_truth == "none"


def test_bad_rule_is_rejected_at_parse_time() -> None:
    with pytest.raises(ValueError, match="pass_rule"):
        Decision(
            question=NoulQuestion(instructions="x", criteria={"true": "a", "false": "b"}),
            pass_rule=ChoiceRule(choices=["a"]),
        )
    with pytest.raises(ValueError, match="criteria"):
        Decision(
            question=ChoiceQuestion(instructions="x", criteria={"a": "a", "b": "b"}),
            pass_rule=ChoiceRule(choices=["z"]),
        )


def test_state_is_capped_with_a_marker() -> None:
    state, truncated = cap_state({"small": "x", "big": "y" * 50_000}, limit=1_000)
    assert truncated
    assert state["small"] == "x"
    assert str(state["big"]).endswith("[truncated]")
    assert cap_state({"a": 1}) == ({"a": 1}, False)


def test_judge_stats_aggregate_from_stored_records(store: Store) -> None:
    a, b = f"test/judge-a-{uuid.uuid4().hex[:6]}", f"test/judge-b-{uuid.uuid4().hex[:6]}"

    def verdict(model: str, *, correct: bool, cost: float) -> AssertionResult:
        return AssertionResult(
            type="decision",
            description="d",
            critical=True,
            status="pass",
            judge=JudgeVerdict(
                judges=[JudgeAnswer(model=model, answer={"type": "noul", "noul": 1.0}, cost_usd=cost)],
                verdict="pass",
                calibration_correct={model: correct},
            ),
        )

    exp_id = f"exp_judges_{uuid.uuid4().hex[:6]}"
    store.create_experiment(exp_id, ExperimentMeta(targets={}, scenarios={}, repeats=1, fixture_url="http://x"))
    for i in range(25):
        store.start_trial(f"{exp_id}:{i}", exp_id, "t", "s@1", i)
        results = [verdict(a, correct=i < 24, cost=0.001)] + (
            [verdict(b, correct=i < 10, cost=0.002)] if i < 10 else []
        )
        store.finish_trial(f"{exp_id}:{i}", "passed", TrialRecord(assertions=results))
    by_model = {s.model: s for s in store.judge_stats()}
    assert (by_model[a].samples, by_model[a].correct, by_model[a].calibrated) == (25, 24, True)
    assert by_model[a].cost_usd == pytest.approx(0.025)
    assert (by_model[b].samples, by_model[b].correct, by_model[b].calibrated) == (10, 10, False)
    assert by_model[b].accuracy == 1.0


def test_judge_evidence_is_redacted_before_it_leaves_the_process(envs: FixturePool) -> None:
    fx = envs.create("t_judge_redact", Seed())
    try:
        ev = Evidence(
            fixture=fx,
            ledger=[],
            events=[],
            output="call me with Bearer abc.def.ghi at http://u:hunter2@h/",
            capabilities=Capabilities(),
            latency_ms=1.0,
            usage=Usage(),
            input={"api_key": "sk-live_ABCDEFGHIJKLMNOPQRST"},
        )
        state = str(judge_state(ev, ["input", "output"]))
        for secret in ("abc.def.ghi", "hunter2", "sk-live_ABCDEFGHIJKLMNOPQRST"):
            assert secret not in state
    finally:
        envs.drop("t_judge_redact")
