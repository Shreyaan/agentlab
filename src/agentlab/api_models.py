"""Console API contract (request/response bodies); the frontend's TypeScript types are generated from it via OpenAPI."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from agentlab.models import Experiment, GateStatus, TargetMode, Trial
from agentlab.protocol import Manifest, ResumeFrom
from agentlab.scenario import Scenario

type ExperimentStatus = Literal["running", "complete", "incomplete"]  # incomplete = job died before a decision


class ConsoleInfo(BaseModel):
    version: str
    protocol_version: str
    auth_required: bool
    suite_path: str
    targets_path: str


class TargetHealth(BaseModel):
    name: str
    mode: TargetMode
    url: str | None
    version: str
    reachable: bool
    manifest: Manifest | None  # live manifest (native) or declared one (http/otel)
    error: str | None = None


class ScenarioInfo(BaseModel):
    key: str
    scenario: Scenario


class RunRequest(BaseModel):
    scenarios: list[str] = []  # scenario keys (id@version); empty = whole suite
    candidate: str
    baseline: str | None = None
    repeats: int = Field(default=1, ge=1, le=20)
    max_regression: float = Field(default=0.0, ge=0.0, le=1.0)


class ForkRequest(BaseModel):
    trial_id: str
    checkpoint_id: str
    target: str | None = None  # default: the source trial's target
    faults: Literal["none", "scenario"] = "none"


class Accepted(BaseModel):
    experiment_id: str


class ExperimentSummary(BaseModel):
    id: str
    created_at: datetime
    status: ExperimentStatus
    candidate: str | None
    baseline: str | None
    decision: GateStatus | None
    planned: int
    finished: int  # trials no longer running
    errors: int
    cost_usd: float | None
    forked_from: ResumeFrom | None
    error: str | None = None  # why the job died, if it did


class ExperimentDetail(BaseModel):
    summary: ExperimentSummary
    experiment: Experiment
    trials: list[Trial]
