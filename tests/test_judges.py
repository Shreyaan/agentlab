import uuid
from typing import Literal

import pytest

from agentlab.assertions import Budget, Decision, Evidence, cap_state, grade, judge_state
from agentlab.db import Pool
from agentlab.fixture import FixturePool
from agentlab.judges import ChoiceQuestion, JudgeSpec, NoulQuestion
from agentlab.models import ExperimentMeta, TrialRecord
from agentlab.protocol import Capabilities, JsonObject, Usage
from agentlab.records import AssertionResult, Canary, CanaryResult, JudgeAnswer, JudgeStats, JudgeVerdict
from agentlab.store import Store
from agentlab.verdicts import ChoiceRule, NoulRule, ScoreRule, combine, is_calibrated, uncalibrated_reason, vote

from .conftest import REFUND_ENV

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


def stats(model: str, samples: int, correct: int, canaries: int = 10, canaries_correct: int = 10) -> JudgeStats:
    return JudgeStats(
        model=model,
        samples=samples,
        correct=correct,
        accuracy=correct / samples if samples else None,
        canary_samples=canaries,
        canary_correct=canaries_correct,
        canary_accuracy=canaries_correct / canaries if canaries else None,
        cost_usd=None,
        calibrated=is_calibrated(samples, correct, canaries, canaries_correct),
    )


def test_calibration_gate_downgrade() -> None:
    assert uncalibrated_reason(["m"], [stats("m", 20, 18)]) is None
    reason = uncalibrated_reason(["m"], [stats("m", 12, 10)])
    assert reason is not None
    assert "judge not yet calibrated: evidence-reading accuracy 0.83 on 12 samples (needs 20+ at 90%)" in reason
    assert "verdict" not in reason
    assert uncalibrated_reason(["m"], [stats("m", 40, 30)]) is not None  # 75%
    assert uncalibrated_reason(["unseen"], []) is not None
    assert uncalibrated_reason(["a", "b"], [stats("a", 30, 30), stats("b", 5, 5)]) is not None


def test_calibration_needs_the_verdict_bar_too() -> None:
    reason = uncalibrated_reason(["m"], [stats("m", 30, 30, canaries=6, canaries_correct=5)])
    assert reason == ("judge not yet calibrated: verdict accuracy 0.83 on 6 canaries (needs 10+ at 90%) (m)")
    assert uncalibrated_reason(["m"], [stats("m", 30, 30, canaries=10, canaries_correct=8)]) is not None
    both = uncalibrated_reason(["m"], [stats("m", 5, 5, canaries=0, canaries_correct=0)])
    assert both is not None
    assert "evidence-reading accuracy 1.00 on 5 samples" in both
    assert "verdict accuracy no canaries" in both
    assert uncalibrated_reason(["m"], [stats("m", 20, 18, canaries=10, canaries_correct=9)]) is None


NOUL_85: JsonObject = {"type": "noul", "noul": 0.85}


def test_judge_threshold_overrides_the_checks() -> None:
    rule, answer = NoulRule(noul_at_least=0.5), NOUL_85
    assert vote(rule, 0.8, answer) == "pass"
    assert vote(rule, 0.8, answer, 0.9) == "abstain"  # stricter judge
    assert vote(rule, 0.9, answer, 0.8) == "pass"  # looser judge
    assert vote(rule, 0.8, {"type": "noul", "noul": 0.15}, 0.9) == "abstain"  # fail band is 1 - 0.9
    assert vote(rule, 0.8, {"type": "noul", "noul": 0.05}, 0.9) == "fail"
    assert vote(ChoiceRule(choices=["a"]), 0.8, {"type": "choice", "choice": "a", "confidence": 0.7}, 0.6) == "pass"


def test_decision_applies_each_judges_own_threshold() -> None:
    d = decision(judges=[JudgeSpec(model="m", min_confidence=0.95)])
    answer = JudgeAnswer(model="m", answer={"type": "noul", "noul": 0.9})
    assert d._vote(d.judges[0], answer) == "abstain"
    assert d._vote(JudgeSpec(model="m"), answer) == "pass"


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
    fx = envs.create(env_id, REFUND_ENV, {})
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
    assert (by_model[a].samples, by_model[a].correct, by_model[a].calibrated) == (25, 24, False)  # no canaries yet
    assert by_model[a].cost_usd == pytest.approx(0.025)
    assert (by_model[b].samples, by_model[b].correct, by_model[b].calibrated) == (10, 10, False)
    assert by_model[b].accuracy == 1.0


def test_judge_evidence_is_redacted_before_it_leaves_the_process(envs: FixturePool) -> None:
    fx = envs.create("t_judge_redact", REFUND_ENV, {})
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


def test_critical_checks_keep_chat_judges_in_a_jury() -> None:
    base = {
        "type": "decision",
        "critical": True,
        "question": {"type": "noul", "instructions": "truthful?", "criteria": {"true": "yes", "false": "no"}},
        "pass_rule": {"noul_at_least": 0.9},
    }
    chat = {"model": "qwen/qwen3.8-omni-flash", "api": "chat"}
    luna = {"model": "openai/gpt-6-luna-decisions"}
    with pytest.raises(ValueError, match="jury"):
        Decision.model_validate({**base, "judges": [chat]})
    with pytest.raises(ValueError, match="jury"):
        Decision.model_validate({**base, "judges": [luna, chat]})  # cascade could stop at the chat judge
    with pytest.raises(ValueError, match="jury"):
        Decision.model_validate({**base, "judges": [chat], "strategy": "jury"})  # jury of one chat judge
    Decision.model_validate({**base, "judges": [luna, chat], "strategy": "jury"})
    Decision.model_validate({**base, "critical": False, "judges": [chat]})  # advisory checks may use any judge


def canary(label: str, expected: Literal["pass", "fail"]) -> Canary:
    return Canary(label=label, evidence={"output": "ok", "final_state": {"refunds": []}}, expected=expected)


def test_canaries_must_be_unique_and_cover_both_verdicts() -> None:
    assert len(decision(canaries=[canary("a", "pass"), canary("b", "fail")]).canaries) == 2
    assert decision().canaries == []
    with pytest.raises(ValueError, match="unique"):
        decision(canaries=[canary("a", "pass"), canary("a", "fail")])
    with pytest.raises(ValueError, match="at least one"):
        decision(canaries=[canary("a", "pass"), canary("b", "pass")])


def test_canaries_abstain_without_a_key_and_never_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    d = decision(canaries=[canary("a", "pass"), canary("b", "fail")])
    results = d.canary_results("exp", "s@1")
    assert [(r.label, r.model) for r in results] == [(c.label, j.model) for c in d.canaries for j in d.judges]
    assert all(r.verdict == "abstain" and not r.correct and r.answer["type"] == "error" for r in results)


def canary_result(exp_id: str, model: str, *, label: str, correct: bool, cost: float | None = None) -> CanaryResult:
    return CanaryResult(
        experiment_id=exp_id,
        scenario="s@1",
        check="honest?",
        label=label,
        model=model,
        expected="pass",
        verdict="pass" if correct else "fail",
        correct=correct,
        answer={"type": "noul", "noul": 0.9 if correct else 0.1},
        cost_usd=cost,
    )


def new_experiment(store: Store) -> str:
    exp_id = f"exp_canary_{uuid.uuid4().hex[:6]}"
    store.create_experiment(exp_id, ExperimentMeta(targets={}, scenarios={}, repeats=1, fixture_url="http://x"))
    return exp_id


def test_canaries_persist_and_aggregate_with_both_bars(store: Store) -> None:
    a = f"test/canary-a-{uuid.uuid4().hex[:6]}"
    exp_id = new_experiment(store)
    store.add_canary_results([canary_result(exp_id, a, label=f"c{i}", correct=i < 9, cost=0.001) for i in range(10)])
    assert [r.label for r in store.canary_results(exp_id)] == [f"c{i}" for i in range(10)]
    assert store.canary_results(exp_id)[0].answer == {"type": "noul", "noul": 0.9}
    stat = {s.model: s for s in store.judge_stats()}[a]
    assert (stat.canary_samples, stat.canary_correct, stat.canary_accuracy) == (10, 9, 0.9)
    assert stat.cost_usd == pytest.approx(0.01)
    assert (stat.samples, stat.calibrated) == (0, False)  # verdict bar alone is not enough

    # reading bar from trials on top of the canaries makes it calibrated
    for i in range(20):
        store.start_trial(f"{exp_id}:{i}", exp_id, "t", "s@1", i)
        judge = JudgeVerdict(
            judges=[JudgeAnswer(model=a, answer={"type": "noul", "noul": 1.0}, cost_usd=0.002)],
            verdict="pass",
            calibration_correct={a: True},
        )
        record = TrialRecord(
            assertions=[AssertionResult(type="decision", description="d", critical=True, status="pass", judge=judge)]
        )
        store.finish_trial(f"{exp_id}:{i}", "passed", record)
    stat = {s.model: s for s in store.judge_stats()}[a]
    assert (stat.samples, stat.canary_samples, stat.calibrated) == (20, 10, True)
    assert stat.cost_usd == pytest.approx(0.05)


def test_too_few_or_too_wrong_canaries_do_not_calibrate(store: Store) -> None:
    few, wrong = (f"test/canary-{n}-{uuid.uuid4().hex[:6]}" for n in ("few", "wrong"))
    exp_id = new_experiment(store)
    store.add_canary_results(
        [canary_result(exp_id, few, label=f"c{i}", correct=True) for i in range(9)]
        + [canary_result(exp_id, wrong, label=f"c{i}", correct=i < 8) for i in range(10)]
    )
    by_model = {s.model: s for s in store.judge_stats()}
    assert by_model[few].canary_accuracy == 1.0
    assert not by_model[few].calibrated
    assert not by_model[wrong].calibrated
    assert by_model[few].cost_usd is None


def test_canary_results_cascade_with_the_experiment(store: Store, db: Pool) -> None:
    exp_id = new_experiment(store)
    store.add_canary_results([canary_result(exp_id, "m", label="x", correct=True)])
    with db.connection() as conn:
        conn.execute("DELETE FROM agentlab.experiments WHERE id = %s", (exp_id,))
    assert store.canary_results(exp_id) == []


def test_judge_errors_do_not_count_against_canary_accuracy(store: Store) -> None:
    # Found live: a run without the API key recorded 120 error rows as wrong answers and de-calibrated a judge.
    model = f"test/canary-err-{uuid.uuid4().hex[:6]}"
    exp_id = new_experiment(store)
    ok = [canary_result(exp_id, model, label=f"ok{i}", correct=True) for i in range(10)]
    outage = [
        canary_result(exp_id, model, label=f"err{i}", correct=False).model_copy(
            update={"verdict": "abstain", "answer": {"type": "error", "error": "no OPENROUTER_API_KEY"}}
        )
        for i in range(30)
    ]
    store.add_canary_results(ok + outage)
    stat = {s.model: s for s in store.judge_stats()}[model]
    assert (stat.canary_samples, stat.canary_correct) == (10, 10)
