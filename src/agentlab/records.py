"""Evidence records shared by the fixture and the graders."""

from typing import Literal

from pydantic import BaseModel, Field, JsonValue

from agentlab.protocol import JsonObject

type Row = dict[str, JsonValue]
type State = dict[str, list[Row]]


class LedgerEntry(BaseModel):
    """One tool call as the environment saw it.

    `committed` means its side effect persisted, even if the caller saw an error.
    """

    seq: int = Field(description="Order of the call within the trial's ledger.")
    tool: str = Field(description="Tool that was called.")
    request: JsonObject = Field(description="Arguments the agent sent.")
    status: int = Field(description="HTTP status the caller saw.")
    response: JsonValue = Field(description="Response body the caller saw.")
    committed: bool = Field(description="Whether the call's side effect persisted, even if the caller saw an error.")
    ts: float = Field(description="Unix time in seconds when the call was recorded.")


class TableDiff(BaseModel):
    """Rows that differ in one table between the start and end of a trial."""

    added: list[Row] = Field(default=[], description="Rows present at the end but not at the start.")
    removed: list[Row] = Field(default=[], description="Rows present at the start but not at the end.")


class JudgeAnswer(BaseModel):
    """One decision model's typed answer (Decisions API), kept verbatim for audit."""

    model: str = Field(description="Judge model id.")
    answer: JsonObject = Field(
        description='The answer as returned, e.g. `{"type": "noul", "noul": 0.02}` or '
        '`{"type": "choice", "choice": "...", "confidence": 0.9}`; `{"type": "error", ...}` if the call failed.'
    )
    calibration_answer: JsonObject | None = Field(
        default=None, description="The judge's answer to the calibration question, if the check has one."
    )
    cost_usd: float | None = Field(default=None, description="Cost of this judge call in US dollars, if reported.")


class JudgeVerdict(BaseModel):
    """What the judges decided for one decision check, and why."""

    judges: list[JudgeAnswer] = Field(description="Answers from the judges that were asked, in order.")
    verdict: Literal["pass", "fail", "abstain"] = Field(
        description="Combined outcome. `abstain` means low confidence, judges disagreed, or an error."
    )
    reason: str = Field(default="", description="Each judge's vote, joined for display.")
    calibration_truth: str | None = Field(
        default=None, description="Ground truth read from SQL for the calibration question."
    )
    calibration_correct: dict[str, bool] = Field(
        default={}, description="Judge model to whether its calibration answer matched the truth."
    )


class Canary(BaseModel):
    """A labelled example for a decision check: evidence exactly as a judge would see it, and the right verdict.
    Canaries measure verdict accuracy, which calibration questions (evidence reading) cannot."""

    label: str = Field(description="Unique name for this example within its check.")
    evidence: JsonObject = Field(
        description='Evidence as a judge would see it, keyed by kind, e.g. `{"output": "...", "final_state": {...}}`.'
    )
    expected: Literal["pass", "fail"] = Field(description="The verdict a correct judge must reach.")


class CanaryResult(BaseModel):
    """One judge's verdict on one canary, recorded to measure verdict accuracy."""

    experiment_id: str = Field(description="Experiment that ran the canary.")
    scenario: str = Field(description="Scenario `id@version` whose check owns the canary.")
    check: str = Field(description="Description of the decision check.")
    label: str = Field(description="The canary's label.")
    model: str = Field(description="Judge model that answered.")
    expected: Literal["pass", "fail"] = Field(description="The canary's correct verdict.")
    verdict: Literal["pass", "fail", "abstain"] = Field(description="The verdict this judge reached.")
    correct: bool = Field(description="Whether `verdict` equals `expected`; an abstain is never correct.")
    answer: JsonObject = Field(description="The judge's raw answer.")
    cost_usd: float | None = Field(default=None, description="Cost of the judge call in US dollars, if reported.")


class JudgeStats(BaseModel):
    """Per-model track record on two bars: evidence reading (calibration questions answered alongside real
    verdicts) and verdict accuracy (labelled canaries). Both must pass before a critical check may block."""

    model: str = Field(description="Judge model id.")
    samples: int = Field(description="Calibration answers seen (evidence-reading samples).")
    correct: int = Field(description="Calibration answers that matched the ground truth.")
    accuracy: float | None = Field(description="`correct / samples` from 0 to 1; null before any sample.")
    canary_samples: int = Field(default=0, description="Canary verdicts seen, excluding judge errors.")
    canary_correct: int = Field(default=0, description="Canary verdicts that matched the expected label.")
    canary_accuracy: float | None = Field(
        default=None, description="`canary_correct / canary_samples` from 0 to 1; null before any canary."
    )
    cost_usd: float | None = Field(description="Total spend on this model's calls in US dollars, if reported.")
    calibrated: bool = Field(description="Meets both accuracy bars, so critical decision checks may block releases.")


class AssertionResult(BaseModel):
    """The outcome of one check on one trial."""

    type: str = Field(description="Check type, e.g. `sql`, `tool_order` or `decision`; `budget` for limits.")
    description: str = Field(description="Human-readable statement of what was checked.")
    critical: bool = Field(description="Whether a failure blocks the release gate.")
    status: Literal["pass", "fail", "unsupported", "skipped"] = Field(
        description="`unsupported`: could not be evaluated (missing evidence, judge abstained or errored). "
        "`skipped`: not applicable to this run."
    )
    detail: str = Field(default="", description="Why it passed or failed, with the observed values.")
    judge: JudgeVerdict | None = Field(default=None, description="Judge breakdown; present for `decision` checks.")


def state_diff(before: State, after: State) -> dict[str, TableDiff]:
    diff: dict[str, TableDiff] = {}
    for table, rows in after.items():
        old = before.get(table, [])
        added, removed = [r for r in rows if r not in old], [r for r in old if r not in rows]
        if added or removed:
            diff[table] = TableDiff(added=added, removed=removed)
    return diff
