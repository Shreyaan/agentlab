"""Persisted domain records: experiments, trials and release decisions."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, JsonValue

from agentlab.protocol import ErrorCode, Event, Manifest, ResumeFrom, Usage
from agentlab.records import AssertionResult, LedgerEntry, State, TableDiff
from agentlab.scenario import Scenario

type TrialStatus = Literal["running", "passed", "failed", "error"]
type GateStatus = Literal["PASS", "BLOCK", "INSUFFICIENT_EVIDENCE"]
type TargetMode = Literal["native", "http", "otel"]


class TrialError(BaseModel):
    code: ErrorCode
    message: str


class TrialRecord(BaseModel):
    run_id: str | None = None
    agent_status: Literal["completed", "failed"] | None = None
    output: JsonValue = None
    events: list[Event] = []
    ledger: list[LedgerEntry] = []
    initial_state: State = {}
    final_state: State = {}
    state_diff: dict[str, TableDiff] = {}
    assertions: list[AssertionResult] = []
    latency_ms: float | None = None
    usage: Usage = Usage()
    error: TrialError | None = None
    resumed_from: ResumeFrom | None = None


class Trial(BaseModel):
    id: str
    experiment_id: str
    target: str
    scenario: str
    repeat: int
    status: TrialStatus
    record: TrialRecord = TrialRecord()

    @property
    def graded(self) -> bool:
        return self.status in ("passed", "failed")


class TargetInfo(BaseModel):
    mode: TargetMode
    url: str | None
    version: str
    manifest: Manifest | None


class ExperimentMeta(BaseModel):
    targets: dict[str, TargetInfo]
    scenarios: dict[str, Scenario]
    repeats: int
    fixture_url: str
    forked_from: ResumeFrom | None = None


class TargetStats(BaseModel):
    passed: int
    graded: int
    errors: int
    pass_rate: float | None
    ci95: tuple[float, float]
    p50_ms: float | None
    p95_ms: float | None
    cost_usd: float | None


class Paired(BaseModel):
    pairs: int
    regressions: int
    fixes: int


class Decision(BaseModel):
    status: GateStatus
    candidate: str
    baseline: str | None
    block_reasons: list[str]
    insufficient_reasons: list[str]
    coverage_gaps: list[str]
    stats: dict[str, TargetStats]
    paired: Paired | None


class Experiment(BaseModel):
    id: str
    created_at: datetime
    meta: ExperimentMeta
    decision: Decision | None = None
