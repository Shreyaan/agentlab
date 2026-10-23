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


class JudgeStats(BaseModel):
    """Per-model track record. Calibration is evidence-reading accuracy: necessary, not verdict accuracy."""

    model: str
    samples: int  # calibration answers seen
    correct: int
    accuracy: float | None
    cost_usd: float | None
    calibrated: bool  # meets the bar to make critical decision checks block releases


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
