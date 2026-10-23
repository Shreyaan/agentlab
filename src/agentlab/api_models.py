"""Console API contract (request/response bodies); the frontend's TypeScript types are generated from it via OpenAPI."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, JsonValue

from agentlab.client import TargetSpec
from agentlab.environment import EnvironmentSpec
from agentlab.models import Experiment, GateStatus, TargetMode, Trial
from agentlab.protocol import Manifest, ResumeFrom
from agentlab.records import Row
from agentlab.scenario import Scenario

type ExperimentStatus = Literal["running", "complete", "incomplete"]  # incomplete = job died before a decision


class ErrorResponse(BaseModel):
    """Body of every non-validation error response."""

    detail: str = Field(description="What went wrong, in plain English; never echoes secrets or input values.")


class ValidationFailure(BaseModel):
    """Body of a 422 response: a message, or FastAPI's list of field problems when the body failed to parse."""

    detail: str | list[dict[str, JsonValue]] = Field(description="The reason, or one entry per invalid field.")


ERROR_TEXT = {
    400: "The request could not be processed.",
    401: "Missing or invalid bearer token (only when a token is configured).",
    403: "Missing `X-AgentLab-Request: 1` header on a write.",
    404: "Not found.",
    409: "Conflict.",
    422: "Validation failed.",
    502: "Upstream adapter or model failure.",
    503: "A config file (targets, scenarios or environments) could not be loaded.",
}


def error_responses(codes: dict[int, str | None]) -> dict[int | str, dict[str, Any]]:
    """OpenAPI `responses` for the error statuses a route can return; None keeps the generic text."""
    return {
        code: {"description": text or ERROR_TEXT[code], "model": ValidationFailure if code == 422 else ErrorResponse}
        for code, text in codes.items()
    }


class ConsoleInfo(BaseModel):
    """Static facts about the running console."""

    version: str = Field(description="Installed AgentLab version.")
    protocol_version: str = Field(description="Wire protocol version the runner speaks.")
    auth_required: bool = Field(description="Whether API calls need a bearer token.")
    suite_path: str = Field(description="Scenario file or directory the console reads.")
    targets_path: str = Field(description="Targets YAML file the console reads and edits.")


class TargetHealth(BaseModel):
    """A configured target and whether its harness answered a manifest probe."""

    name: str = Field(description="Target name from the targets file.")
    mode: TargetMode = Field(description="How the harness is reached: `native`, `http` or `otel`.")
    url: str | None = Field(description="Harness base URL with credentials redacted; null if none.")
    version: str = Field(description="Version label of the system under test.")
    reachable: bool = Field(description="Whether the manifest probe succeeded.")
    manifest: Manifest | None = Field(
        description="Live manifest when reachable (native), else the declared one (http/otel); null if none."
    )
    error: str | None = Field(default=None, description="Why the probe failed, redacted; null when reachable.")


class ScenarioInfo(BaseModel):
    """A suite scenario with its lookup key."""

    key: str = Field(description="Scenario `id@version`.")
    scenario: Scenario = Field(description="The full scenario definition.")


class RunRequest(BaseModel):
    """Start an experiment: scenarios run on a candidate target, optionally compared to a baseline."""

    scenarios: list[str] = Field(
        default=[], description="Scenario keys (`id@version`) to run; empty runs the whole suite."
    )
    candidate: str = Field(description="Target name to judge for release.")
    baseline: str | None = Field(default=None, description="Target name to compare the candidate against.")
    repeats: int = Field(default=1, ge=1, le=20, description="Times to run each scenario on each target.")
    max_regression: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Pass-rate drop vs the baseline to tolerate, from 0 to 1."
    )


class ForkRequest(BaseModel):
    """Re-run a trial from one of its checkpoints, to test a counterfactual."""

    trial_id: str = Field(description="Trial to fork.")
    checkpoint_id: str = Field(description="Checkpoint in that trial to resume from.")
    target: str | None = Field(default=None, description="Target to resume on; defaults to the source trial's target.")
    faults: Literal["none", "scenario"] = Field(
        default="none", description="`scenario` re-applies the scenario's faults; `none` runs the fork clean."
    )


class Accepted(BaseModel):
    """Returned when work was queued and continues in the background."""

    experiment_id: str = Field(description="Id of the experiment that was started; poll it for progress.")


class ExperimentSummary(BaseModel):
    """One row of the experiment list."""

    id: str = Field(description="Unique experiment id.")
    created_at: datetime = Field(description="When the experiment was planned.")
    status: ExperimentStatus = Field(description="Whether its trials are still running or it has a decision.")
    candidate: str | None = Field(description="Target being judged for release.")
    baseline: str | None = Field(description="Target compared against, if any.")
    decision: GateStatus | None = Field(description="Release decision; null until the experiment completes.")
    planned: int = Field(description="Trials planned.")
    finished: int = Field(description="Trials no longer running.")
    errors: int = Field(description="Trials that could not be graded.")
    cost_usd: float | None = Field(description="Total agent spend in US dollars, if reported.")
    forked_from: ResumeFrom | None = Field(description="Checkpoint this experiment forked; null if not a fork.")
    error: str | None = Field(default=None, description="Why the job died, if it did.")


class ExperimentDetail(BaseModel):
    """An experiment with all of its trials."""

    summary: ExperimentSummary = Field(description="List-row view of the experiment.")
    experiment: Experiment = Field(description="Plan and release decision.")
    trials: list[Trial] = Field(description="Every trial with its evidence and check results.")


# --- Builders: define scenarios and targets from the console. Files on disk stay the source of truth. ---


class BuilderInfo(BaseModel):
    """Vocabulary for the editors' dropdowns."""

    tools: list[str] = Field(
        description="The environment's tool names, for faults, `tool_order`, `forbidden_tool` and events."
    )
    seed_columns: dict[str, list[str]] = Field(description="The environment's tables, each with its column names.")
    assertion_types: list[str] = Field(description="Check types a new scenario may use.")
    judge_models: list[str] = Field(description="Suggested decision models; the first is the default judge.")


class ScenarioDraft(BaseModel):
    """A scenario to validate or save."""

    scenario: Scenario = Field(description="The scenario definition.")


class ScenarioValidation(BaseModel):
    """Outcome of validating a scenario or environment draft."""

    valid: bool = Field(description="Whether the draft can be saved.")
    errors: list[str] = Field(default=[], description='Problems as `"path: message"`, without echoing input values.')
    yaml: str | None = Field(default=None, description="Normalized YAML that would be written; set when valid.")
    key: str | None = Field(
        default=None, description="`id@version` saving would produce (version auto-bumps on change); set when valid."
    )


class SavedScenario(BaseModel):
    """Result of saving a scenario or environment file."""

    key: str = Field(description="`id@version` that was written.")
    path: str = Field(description="File that was written.")
    created: bool = Field(description="True for a new file; false when an existing one got a new version.")


class QueryTest(BaseModel):
    """A SQL query to try against a temporary seeded environment."""

    environment: str = Field(default="refund@2", description="Environment `id@version` to create.")
    seed: dict[str, list[Row]] = Field(default={}, description="Rows to insert first, keyed by table name.")
    query: str = Field(description="Read-only SELECT to run, as a `sql` check would.")


class QueryResult(BaseModel):
    """What a test query returned."""

    ok: bool = Field(description="Whether the query ran.")
    rows: list[list[JsonValue]] = Field(default=[], description="Result rows, each a list of cell values.")
    value: JsonValue = Field(
        default=None,
        description="Single-cell result as a scalar, exactly as the `sql` check compares it; null otherwise.",
    )
    error: str | None = Field(default=None, description="Why the query failed; null when `ok`.")


class DryRunRequest(BaseModel):
    """Run one scenario once on one target without saving it."""

    scenario: Scenario = Field(description="The scenario to run; it may be unsaved.")
    target: str = Field(description="Target name to run it on.")


class TargetDraft(BaseModel):
    """A target to test or save."""

    name: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$",
        description="Target name, up to 64 letters, digits, `.`, `_` or `-`.",
    )
    spec: TargetSpec = Field(description="How to reach the harness.")


class SavedTarget(BaseModel):
    """Result of saving a target."""

    name: str = Field(description="Target name that was written.")
    created: bool = Field(description="True for a new target; false when an existing one was replaced.")


# --- Free-form environments and natural-language authoring. ---


class EnvironmentInfo(BaseModel):
    """An environment spec with its lookup key."""

    key: str = Field(description="Environment `id@version`.")
    environment: EnvironmentSpec = Field(description="The full environment definition.")


class EnvironmentDraft(BaseModel):
    """An environment to validate or save."""

    environment: EnvironmentSpec = Field(description="The environment definition.")


class AuthorRequest(BaseModel):
    """Ask a model to draft a scenario (and optionally its environment) from plain English."""

    description: str = Field(min_length=10, max_length=8000, description="The scenario to build, in plain English.")
    environment: str | None = Field(
        default=None, description="Existing environment key to build on; null drafts a new environment too."
    )


class AuthorDraft(BaseModel):
    """A model-written draft, already validated against a real temporary environment. Never saved automatically."""

    environment: EnvironmentSpec | None = Field(
        description="The drafted environment; set only when a new one was drafted."
    )
    scenario: Scenario | None = Field(
        description="The drafted scenario; null only when no attempt produced a parseable one (then `valid` is false)."
    )
    valid: bool = Field(description="Whether the draft passed validation and can be saved.")
    errors: list[str] = Field(default=[], description="Problems remaining after the repair attempts.")
    notes: list[str] = Field(default=[], description="Assumptions the author model made, for a human to review.")
    model: str = Field(description="Authoring model id.")
    attempts: int = Field(description="Model calls made, including repair attempts.")
    cost_usd: float | None = Field(default=None, description="Total model spend in US dollars, if reported.")
