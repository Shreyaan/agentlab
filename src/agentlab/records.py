"""Evidence records shared by the fixture and the graders."""

from typing import Literal

from pydantic import BaseModel, JsonValue

from agentlab.protocol import JsonObject

type Row = dict[str, JsonValue]
type State = dict[str, list[Row]]


class LedgerEntry(BaseModel):
    """One tool call as the environment saw it.

    `committed` means its side effect persisted, even if the caller saw an error.
    """

    seq: int
    tool: str
    request: JsonObject
    status: int
    response: JsonValue
    committed: bool
    ts: float


class TableDiff(BaseModel):
    added: list[Row] = []
    removed: list[Row] = []


class JudgeAnswer(BaseModel):
    """One decision model's typed answer (Decisions API), kept verbatim for audit."""

    model: str
    answer: JsonObject  # e.g. {"type": "noul", "noul": 0.02} or {"type": "choice", "choice": ..., "confidence": ...}
    calibration_answer: JsonObject | None = None  # the judge's answer to the calibration question, if any
    cost_usd: float | None = None


class JudgeVerdict(BaseModel):
    judges: list[JudgeAnswer]
    verdict: Literal["pass", "fail", "abstain"]  # abstain: low confidence, judges disagree, or uncalibrated
    reason: str = ""
    calibration_truth: str | None = None  # ground truth from SQL for the calibration question
    calibration_correct: dict[str, bool] = {}  # model -> did its calibration answer match the truth


class Canary(BaseModel):
    """A labelled example for a decision check: evidence exactly as a judge would see it, and the right verdict.
    Canaries measure verdict accuracy, which calibration questions (evidence reading) cannot."""

    label: str
    evidence: JsonObject  # e.g. {"output": "...", "final_state": {"refunds": [...]}}
    expected: Literal["pass", "fail"]


class CanaryResult(BaseModel):
    experiment_id: str
    scenario: str  # id@version
    check: str  # the decision check's description
    label: str
    model: str
    expected: Literal["pass", "fail"]
    verdict: Literal["pass", "fail", "abstain"]
    correct: bool  # verdict == expected; an abstain is not correct
    answer: JsonObject
    cost_usd: float | None = None


class JudgeStats(BaseModel):
    """Per-model track record on two bars: evidence reading (calibration questions answered alongside real
    verdicts) and verdict accuracy (labelled canaries). Both must pass before a critical check may block."""

    model: str
    samples: int  # calibration answers seen
    correct: int
    accuracy: float | None
    canary_samples: int = 0
    canary_correct: int = 0
    canary_accuracy: float | None = None
    cost_usd: float | None
    calibrated: bool  # meets both bars, so critical decision checks may block releases


class AssertionResult(BaseModel):
    type: str
    description: str
    critical: bool
    status: Literal["pass", "fail", "unsupported", "skipped"]  # skipped: not applicable to this run
    detail: str = ""
    judge: JudgeVerdict | None = None  # present for `decision` assertions


def state_diff(before: State, after: State) -> dict[str, TableDiff]:
    diff: dict[str, TableDiff] = {}
    for table, rows in after.items():
        old = before.get(table, [])
        added, removed = [r for r in rows if r not in old], [r for r in old if r not in rows]
        if added or removed:
            diff[table] = TableDiff(added=added, removed=removed)
    return diff
