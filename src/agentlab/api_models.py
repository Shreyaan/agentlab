"""Console API contract (request/response bodies); the frontend's TypeScript types are generated from it via OpenAPI."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, JsonValue

from agentlab.client import TargetSpec
from agentlab.environment import EnvironmentSpec
from agentlab.models import Experiment, GateStatus, TargetMode, Trial
from agentlab.protocol import Manifest, ResumeFrom
from agentlab.records import Row
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


# --- Builders: define scenarios and targets from the console. Files on disk stay the source of truth. ---


class BuilderInfo(BaseModel):
    """Vocabulary for the editors' dropdowns."""

    tools: list[str]  # the environment's tool names, for faults / tool_order / forbidden_tool / events
    seed_columns: dict[str, list[str]]  # the environment's table -> columns
    assertion_types: list[str]
    judge_models: list[str]  # suggested decision models; the first is the default judge


class ScenarioDraft(BaseModel):
    scenario: Scenario


class ScenarioValidation(BaseModel):
    valid: bool
    errors: list[str] = []  # human-readable "path: message", no input echo
    yaml: str | None = None  # normalized YAML that would be written
    key: str | None = None  # id@version that saving would produce (version auto-bumped on change)


class SavedScenario(BaseModel):
    key: str
    path: str
    created: bool  # False = an existing scenario got a new version


class QueryTest(BaseModel):
    environment: str = "refund@2"
    seed: dict[str, list[Row]] = {}
    query: str


class QueryResult(BaseModel):
    ok: bool
    rows: list[list[JsonValue]] = []
    value: JsonValue = None  # single-cell results as a scalar, exactly as the sql assertion compares them
    error: str | None = None


class DryRunRequest(BaseModel):
    scenario: Scenario  # may be unsaved
    target: str


class TargetDraft(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
    spec: TargetSpec


class SavedTarget(BaseModel):
    name: str
    created: bool


# --- Free-form environments and natural-language authoring. ---


class EnvironmentInfo(BaseModel):
    key: str
    environment: EnvironmentSpec


class EnvironmentDraft(BaseModel):
    environment: EnvironmentSpec


class AuthorRequest(BaseModel):
    description: str = Field(min_length=10, max_length=8000)  # plain-English scenario
    environment: str | None = None  # existing environment key to build on; None = draft a new environment too


class AuthorDraft(BaseModel):
    """A model-written draft, already validated against a real temporary environment. Never saved automatically."""

    environment: EnvironmentSpec | None  # set when a new environment was drafted
    scenario: Scenario | None  # None only when no attempt produced a parseable scenario (then valid is False)
    valid: bool
    errors: list[str] = []  # remaining problems after the repair attempts
    notes: list[str] = []  # assumptions the author model made, for the human to review
    model: str  # authoring model id
    attempts: int
    cost_usd: float | None = None
