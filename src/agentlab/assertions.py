"""Graders, in precedence order: executable environment state first, then process (ledger/events), then model-judged
language and intent (decision checks), calibrated against the recorded facts."""

import json
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from agentlab.fixture import Fixture
from agentlab.judges import JUDGE_MODELS, ChoiceQuestion, JudgeError, JudgeSpec, NoulQuestion, Question, ask
from agentlab.protocol import Capabilities, Event, JsonObject, Usage
from agentlab.records import (
    AssertionResult,
    Canary,
    CanaryResult,
    JudgeAnswer,
    JudgeStats,
    JudgeVerdict,
    LedgerEntry,
    State,
    TableDiff,
)
from agentlab.redaction import redact
from agentlab.verdicts import (
    ChoiceRule,
    NoulRule,
    PassRule,
    ScoreRule,
    Strategy,
    Vote,
    combine,
    reading_correct,
    single_cell,
    uncalibrated_reason,
    vote,
)

type Status = Literal["pass", "fail", "unsupported", "skipped"]


@dataclass(frozen=True)
class Evidence:
    fixture: Fixture
    ledger: list[LedgerEntry]
    events: list[Event]
    output: JsonValue
    capabilities: Capabilities
    latency_ms: float
    usage: Usage
    input: JsonObject = field(default_factory=dict)
    final_state: State = field(default_factory=dict)
    state_diff: dict[str, TableDiff] = field(default_factory=dict)
    judge_stats: list[JudgeStats] = field(default_factory=list)  # loaded once per experiment


class _Check(BaseModel, ABC):
    critical: bool = False
    requires_faults: bool = False  # only meaningful when the scenario's faults are active (skipped in clean forks)
    description: str = ""

    @property
    @abstractmethod
    def default_description(self) -> str: ...

    @abstractmethod
    def check(self, ev: Evidence) -> AssertionResult: ...

    def result(self, status: Status, detail: str = "", judge: JudgeVerdict | None = None) -> AssertionResult:
        kind = type(self).model_fields["type"].default
        return AssertionResult(
            type=str(kind),
            description=self.description or self.default_description,
            critical=self.critical,
            status=status,
            detail=detail,
            judge=judge,
        )


class Sql(_Check):
    """Read-only SQL over the environment's final state; a single-cell result is compared as a scalar."""

    type: Literal["sql"] = "sql"
    query: str
    equals: JsonValue

    @property
    def default_description(self) -> str:
        return f"{self.query} == {self.equals!r}"

    def check(self, ev: Evidence) -> AssertionResult:
        rows = ev.fixture.query(self.query)
        value: JsonValue = rows[0][0] if len(rows) == 1 and len(rows[0]) == 1 else [list(r) for r in rows]
        return self.result("pass" if value == self.equals else "fail", f"got {value!r}")


class ToolOrder(_Check):
    """`requires` must succeed (2xx) in the side-effect ledger before the first `before` call."""

    type: Literal["tool_order"] = "tool_order"
    before: str
    requires: str

    @property
    def default_description(self) -> str:
        return f"{self.requires} succeeds before {self.before}"

    def check(self, ev: Evidence) -> AssertionResult:
        first = next((i for i, e in enumerate(ev.ledger) if e.tool == self.before), None)
        if first is None:
            return self.result("pass", f"{self.before} never called")
        if any(e.tool == self.requires and e.status < 400 for e in ev.ledger[:first]):
            return self.result("pass")
        return self.result("fail", f"{self.before} at ledger #{first + 1} without {self.requires}")


class ForbiddenTool(_Check):
    type: Literal["forbidden_tool"] = "forbidden_tool"
    name: str

    @property
    def default_description(self) -> str:
        return f"{self.name} is never called"

    def check(self, ev: Evidence) -> AssertionResult:
        n = sum(e.tool == self.name for e in ev.ledger)
        return self.result("fail", f"called {n}x") if n else self.result("pass")


class EventPresent(_Check):
    """Process evidence from inside the harness; unsupported unless the adapter streams native events."""

    type: Literal["event_present"] = "event_present"
    event: str
    name: str | None = None

    @property
    def default_description(self) -> str:
        return f"agent reports {self.event}" + (f" for {self.name}" if self.name else "")

    def check(self, ev: Evidence) -> AssertionResult:
        if ev.capabilities.observe != "native_events":
            return self.result("unsupported", f"adapter observe={ev.capabilities.observe}")
        hit = any(e.type == self.event and (self.name is None or e.name == self.name) for e in ev.events)
        return self.result("pass" if hit else "fail")


STATE_LIMIT_BYTES = 24_000
TRUNCATED = " [truncated]"
QUESTION, CALIBRATION = "check", "calibration"
type EvidenceKind = Literal["input", "output", "final_state", "state_diff", "ledger", "events"]


class Calibration(BaseModel):
    """Asked in the same judge call; the truth comes from the environment, so it scores evidence-reading accuracy."""

    question: ChoiceQuestion | NoulQuestion = Field(discriminator="type")
    truth_sql: str  # read-only, scoped to the trial schema, single cell, compared as a string


def _size(value: JsonValue) -> int:
    return len(json.dumps(value, separators=(",", ":")))


def cap_state(state: dict[str, JsonValue], limit: int = STATE_LIMIT_BYTES) -> tuple[dict[str, JsonValue], bool]:
    """Halve the largest field until the serialized state fits, marking what was cut."""
    truncated = False
    while _size(state) > limit:
        key = max(state, key=lambda k: _size(state[k]))
        value = state[key]
        text = value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))
        state = {**state, key: text[: len(text) // 2] + TRUNCATED}
        truncated = True
    return state, truncated


def judge_state(ev: Evidence, kinds: list[EvidenceKind]) -> dict[str, JsonValue]:
    available: dict[str, Callable[[], JsonValue]] = {
        "input": lambda: ev.input,
        "output": lambda: ev.output,
        "final_state": lambda: {t: [dict(r) for r in rows] for t, rows in ev.final_state.items()},
        "state_diff": lambda: {t: d.model_dump(mode="json") for t, d in ev.state_diff.items()},
        "ledger": lambda: [
            e.model_dump(mode="json", include={"seq", "tool", "status", "committed"}) for e in ev.ledger
        ],
        "events": lambda: [e.model_dump(mode="json", exclude_none=True) for e in ev.events],
    }
    return {k: redact(available[k]()) for k in kinds}  # evidence leaves the process: scrub it like persisted data


class Decision(_Check):
    """A model-judged check: typed question about the evidence, thresholded into pass / fail / abstain (unsupported).

    A critical fail only blocks when the judges that decided it are calibrated (see verdicts.uncalibrated_reason).
    """

    type: Literal["decision"] = "decision"
    question: Question
    pass_rule: PassRule
    min_confidence: float = Field(default=0.8, ge=0, le=1)
    evidence: list[EvidenceKind] = Field(default=["input", "output", "final_state"], min_length=1)
    judges: list[JudgeSpec] = Field(default_factory=lambda: [JudgeSpec(model=m) for m in JUDGE_MODELS], min_length=1)
    strategy: Strategy = "cascade"
    calibration: Calibration | None = None
    canaries: list[Canary] = []

    @model_validator(mode="after")
    def _canaries_cover_both_verdicts(self) -> Self:
        labels = [c.label for c in self.canaries]
        if len(labels) != len(set(labels)):
            raise ValueError("canary labels must be unique")
        if self.canaries and {c.expected for c in self.canaries} != {"pass", "fail"}:
            raise ValueError('canaries need at least one "pass" and one "fail" example')
        return self

    @model_validator(mode="after")
    def _rule_fits_question(self) -> Self:
        rules = {"noul": NoulRule, "choice": ChoiceRule, "score": ScoreRule}
        if not isinstance(self.pass_rule, rules[self.question.type]):
            raise ValueError(f"pass_rule does not fit a {self.question.type} question")
        if (
            isinstance(self.pass_rule, ChoiceRule)
            and isinstance(self.question, ChoiceQuestion)
            and (unknown := set(self.pass_rule.choices) - set(self.question.criteria))
        ):
            raise ValueError(f"choices not in the question's criteria: {sorted(unknown)}")
        # Measured live: a chat judge (gpt-4.1-nano) followed an instruction injected into the agent's reply and
        # passed a lie at P=1.0, while decision models did not. So a chat judge may only sit on a critical check's
        # jury next to a decision model, where its vote alone can never pass anything.
        chat = any(j.api == "chat" for j in self.judges)
        decision_model = any(j.api == "decisions" for j in self.judges)
        if self.critical and chat and not (self.strategy == "jury" and decision_model):
            raise ValueError("critical checks may use chat judges only in a jury that includes a decision model")
        return self

    @property
    def default_description(self) -> str:
        return self.question.instructions

    def check(self, ev: Evidence) -> AssertionResult:
        state, truncated = cap_state(judge_state(ev, self.evidence))
        questions: dict[str, Question] = {QUESTION: self.question}
        truth = None
        if self.calibration:
            questions[CALIBRATION] = self.calibration.question
            truth = single_cell(ev.fixture.query(self.calibration.truth_sql))
        asked: list[JudgeAnswer] = []
        votes: list[Vote] = []
        for spec in self.judges:
            asked.append(_ask_judge(spec, questions, state))
            votes.append(self._vote(spec, asked[-1]))
            if self.strategy == "cascade" and votes[-1] != "abstain":
                break
        verdict = combine(self.strategy, votes)
        reason = "; ".join(f"{a.model}: {v}" for a, v in zip(asked, votes, strict=True))
        judge = JudgeVerdict(
            judges=asked,
            verdict=verdict,
            reason=reason,
            calibration_truth=truth,
            calibration_correct={
                a.model: reading_correct(a.calibration_answer, truth)
                for a in asked
                if truth is not None and a.calibration_answer is not None
            },
        )
        note = "; evidence truncated to fit the judge" if truncated else ""
        if verdict == "abstain":
            return self.result("unsupported", f"judges abstained ({reason}){note}", judge)
        if verdict == "pass":
            return self.result("pass", reason + note, judge)
        blockers = [a.model for a, v in zip(asked, votes, strict=True) if v == "fail"]
        if self.critical and (why := uncalibrated_reason(blockers, ev.judge_stats)):
            return self.result("unsupported", f"{why}; {reason}{note}", judge)
        return self.result("fail", reason + note, judge)

    def _vote(self, spec: JudgeSpec, answer: JudgeAnswer) -> Vote:
        return vote(self.pass_rule, self.min_confidence, answer.answer, spec.min_confidence)

    def canary_results(self, exp_id: str, scenario: str) -> list[CanaryResult]:
        """Every judge answers every canary on its own: per-model verdict accuracy, never a cascade."""
        return [self.canary_result(exp_id, scenario, c, spec) for c in self.canaries for spec in self.judges]

    def canary_result(self, exp_id: str, scenario: str, canary: Canary, spec: JudgeSpec) -> CanaryResult:
        state, _ = cap_state({k: redact(v) for k, v in canary.evidence.items()})
        answer = _ask_judge(spec, {QUESTION: self.question}, state)
        verdict = self._vote(spec, answer)
        return CanaryResult(
            experiment_id=exp_id,
            scenario=scenario,
            check=self.description or self.default_description,
            label=canary.label,
            model=spec.model,
            expected=canary.expected,
            verdict=verdict,
            correct=verdict == canary.expected,
            answer=answer.answer,
            cost_usd=answer.cost_usd,
        )


def _ask_judge(spec: JudgeSpec, questions: dict[str, Question], state: dict[str, JsonValue]) -> JudgeAnswer:
    try:
        reply = ask(spec, questions, state)
    except JudgeError as exc:
        return JudgeAnswer(model=spec.model, answer={"type": "error", "error": str(exc)})
    return JudgeAnswer(
        model=spec.model,
        answer=reply.answers[QUESTION],
        calibration_answer=reply.answers.get(CALIBRATION),
        cost_usd=reply.cost_usd,
    )


class RetiredCheck(_Check):
    """A removed check type. Experiments recorded with it must stay readable, so it still parses (its old fields
    are kept as-is), but it never runs: always `skipped`. New scenarios may not use it (see scenario.retired)."""

    model_config = ConfigDict(extra="allow")
    type: Literal["output_matches"] = "output_matches"  # regex on the reply; replaced by `decision`

    @property
    def default_description(self) -> str:
        return f"retired check ({self.type})"

    def check(self, ev: Evidence) -> AssertionResult:
        return self.result("skipped", "retired check type; no longer evaluated")


type Assertion = Annotated[
    Sql | ToolOrder | ForbiddenTool | EventPresent | Decision | RetiredCheck, Field(discriminator="type")
]


class Budget(BaseModel):
    max_tool_calls: int | None = None
    max_latency_ms: int | None = None
    max_cost_usd: float | None = None


def _limit(name: str, actual: float | None, cap: float | None) -> AssertionResult | None:
    if cap is None:
        return None
    description = f"{name} <= {cap:g}"
    if actual is None:
        return AssertionResult(
            type="budget",
            description=description,
            critical=False,
            status="unsupported",
            detail="not reported by adapter",
        )
    return AssertionResult(
        type="budget",
        description=description,
        critical=False,
        status="pass" if actual <= cap else "fail",
        detail=f"actual {actual:g}",
    )


def check_budget(budget: Budget, ev: Evidence) -> list[AssertionResult]:
    checks = [
        _limit("tool_calls", len(ev.ledger), budget.max_tool_calls),
        _limit("latency_ms", ev.latency_ms, budget.max_latency_ms),
        _limit("cost_usd", ev.usage.cost_usd, budget.max_cost_usd),
    ]
    return [c for c in checks if c]


def _safe_check(a: _Check, ev: Evidence, *, faults_active: bool) -> AssertionResult:
    if a.requires_faults and not faults_active:
        return a.result("skipped", "scenario faults are disabled in this run")
    try:
        return a.check(ev)
    except Exception as exc:  # noqa: BLE001 - a broken grader is a grader defect, never an agent result
        return a.result("unsupported", f"grader error: {exc}")


def grade(assertions: list[Assertion], budget: Budget, ev: Evidence, *, faults_active: bool) -> list[AssertionResult]:
    return [_safe_check(a, ev, faults_active=faults_active) for a in assertions] + check_budget(budget, ev)
