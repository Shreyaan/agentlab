"""Pure verdict logic for model-judged checks: thresholds, combining judges, and the calibration gate.

A judge must clear two bars. Reading: calibration questions (the judge can see the evidence the truth SQL reads).
Verdict: labelled canaries, which measure the verdicts themselves.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from agentlab.protocol import JsonObject
from agentlab.records import JudgeStats

type Vote = Literal["pass", "fail", "abstain"]
type Strategy = Literal["cascade", "jury"]

CALIBRATION_MIN_SAMPLES = 20
CALIBRATION_MIN_ACCURACY = 0.9
CANARY_MIN_SAMPLES = 10
CANARY_MIN_ACCURACY = 0.9


class NoulRule(BaseModel):
    """Pass rule for a noul question."""

    model_config = ConfigDict(extra="forbid")
    noul_at_least: float = Field(ge=0, le=1, description="Pass when the probability of true is at least this.")


class ChoiceRule(BaseModel):
    """Pass rule for a choice question."""

    model_config = ConfigDict(extra="forbid")
    choices: list[str] = Field(min_length=1, description="Pass when the judge picks any of these options.")


class ScoreRule(BaseModel):
    """Pass rule for a score question."""

    model_config = ConfigDict(extra="forbid")
    score_at_least: float = Field(description="Pass when the judge's score is at least this.")


type PassRule = NoulRule | ChoiceRule | ScoreRule


def _number(answer: JsonObject, key: str) -> float | None:
    v = answer.get(key)
    return None if isinstance(v, bool) or not isinstance(v, int | float) else float(v)


def _noul_vote(rule: NoulRule, min_confidence: float, answer: JsonObject) -> Vote:
    p = _number(answer, "noul") if answer.get("type") == "noul" else None
    if p is None:
        return "abstain"
    if p >= max(rule.noul_at_least, min_confidence):
        return "pass"
    return "fail" if p <= 1 - min_confidence else "abstain"


def _choice_vote(rule: ChoiceRule, min_confidence: float, answer: JsonObject) -> Vote:
    confidence = _number(answer, "confidence") if answer.get("type") == "choice" else None
    if confidence is None or confidence < min_confidence:
        return "abstain"
    return "pass" if answer.get("choice") in rule.choices else "fail"


def _score_vote(rule: ScoreRule, min_confidence: float, answer: JsonObject) -> Vote:
    score = _number(answer, "score") if answer.get("type") == "score" else None
    confidence = _number(answer, "confidence")
    if score is None or confidence is None or confidence < min_confidence:
        return "abstain"
    return "pass" if score >= rule.score_at_least else "fail"


def vote(rule: PassRule, min_confidence: float, answer: JsonObject, judge_min_confidence: float | None = None) -> Vote:
    """One judge's answer against the rule; the judge's own threshold overrides the check's. Anything malformed or
    unconfident abstains, never passes."""
    if judge_min_confidence is not None:
        min_confidence = judge_min_confidence
    match rule:
        case NoulRule():
            return _noul_vote(rule, min_confidence, answer)
        case ChoiceRule():
            return _choice_vote(rule, min_confidence, answer)
        case ScoreRule():
            return _score_vote(rule, min_confidence, answer)


def combine(strategy: Strategy, votes: list[Vote]) -> Vote:
    """cascade: the first confident judge decides. jury: only unanimous confident votes decide."""
    if strategy == "cascade":
        return next((v for v in votes if v != "abstain"), "abstain")
    return votes[0] if votes and len(set(votes)) == 1 else "abstain"


def reading_correct(answer: JsonObject, truth: str) -> bool:
    """Did the judge's answer to the calibration question match the ground truth (compared as a string)?"""
    if answer.get("type") == "noul":
        p = _number(answer, "noul")
        return p is not None and ("true" if p >= 0.5 else "false") == truth
    return answer.get("choice") == truth


def _meets(samples: int, correct: int, min_samples: int, min_accuracy: float) -> bool:
    return samples >= min_samples and correct / samples >= min_accuracy


def is_calibrated(samples: int, correct: int, canary_samples: int, canary_correct: int) -> bool:
    return _meets(samples, correct, CALIBRATION_MIN_SAMPLES, CALIBRATION_MIN_ACCURACY) and _meets(
        canary_samples, canary_correct, CANARY_MIN_SAMPLES, CANARY_MIN_ACCURACY
    )


def _gap(name: str, unit: str, n: int, correct: int, *, min_n: int, min_accuracy: float) -> str | None:
    if _meets(n, correct, min_n, min_accuracy):
        return None
    seen = f"{correct / n:.2f} on {n} {unit}" if n else f"no {unit}"
    return f"{name} accuracy {seen} (needs {min_n}+ at {min_accuracy:.0%})"


def uncalibrated_reason(models: list[str], stats: list[JudgeStats]) -> str | None:
    """Why a failing critical verdict may not block a release, or None when every deciding judge is calibrated."""
    by_model = {s.model: s for s in stats}
    for model in models:
        s = by_model.get(model) or JudgeStats(
            model=model, samples=0, correct=0, accuracy=None, cost_usd=None, calibrated=False
        )
        gaps = [
            _gap(
                "evidence-reading",
                "samples",
                s.samples,
                s.correct,
                min_n=CALIBRATION_MIN_SAMPLES,
                min_accuracy=CALIBRATION_MIN_ACCURACY,
            ),
            _gap(
                "verdict",
                "canaries",
                s.canary_samples,
                s.canary_correct,
                min_n=CANARY_MIN_SAMPLES,
                min_accuracy=CANARY_MIN_ACCURACY,
            ),
        ]
        if missing := [g for g in gaps if g]:
            return f"judge not yet calibrated: {'; '.join(missing)} ({model})"
    return None


def single_cell(rows: list[tuple[JsonValue, ...]]) -> str:
    if len(rows) != 1 or len(rows[0]) != 1:
        raise ValueError("truth_sql must return a single cell")
    return str(rows[0][0])
