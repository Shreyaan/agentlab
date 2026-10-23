"""Persisted domain records: experiments, trials and release decisions."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, JsonValue

from agentlab.environment import EnvironmentSpec
from agentlab.protocol import ErrorCode, Event, Manifest, ResumeFrom, Usage
from agentlab.records import AssertionResult, LedgerEntry, State, TableDiff
from agentlab.scenario import Scenario

type TrialStatus = Literal["running", "passed", "failed", "error"]
type GateStatus = Literal["PASS", "BLOCK", "INSUFFICIENT_EVIDENCE"]
type TargetMode = Literal["native", "http", "otel"]


class TrialError(BaseModel):
    """Why a trial could not be graded: an infrastructure failure, never an agent failure."""

    code: ErrorCode = Field(description="Machine-readable failure category.")
    message: str = Field(description="What went wrong, with secrets redacted.")


class TrialRecord(BaseModel):
    """Everything captured while running and grading one trial."""

    run_id: str | None = Field(default=None, description="Harness-side run id; null if the harness never replied.")
    agent_status: Literal["completed", "failed"] | None = Field(
        default=None, description="Whether the agent finished its run, as the harness reported it."
    )
    output: JsonValue = Field(default=None, description="The agent's final answer.")
    events: list[Event] = Field(default=[], description="Steps the harness reported, if it streams events.")
    ledger: list[LedgerEntry] = Field(default=[], description="Every tool call the environment received, in order.")
    initial_state: State = Field(default={}, description="Table contents before the agent ran.")
    final_state: State = Field(default={}, description="Table contents after the agent ran.")
    state_diff: dict[str, TableDiff] = Field(
        default={}, description="Per-table rows added or removed by the run; unchanged tables are omitted."
    )
    assertions: list[AssertionResult] = Field(default=[], description="Results of every check, budget limits last.")
    latency_ms: float | None = Field(default=None, description="Wall-clock time of the invoke call, in milliseconds.")
    usage: Usage = Field(default=Usage(), description="Resources the harness reported using.")
    error: TrialError | None = Field(default=None, description="Set when the trial errored instead of being graded.")
    resumed_from: ResumeFrom | None = Field(
        default=None, description="Checkpoint this trial continued from, for forks."
    )


class Trial(BaseModel):
    """One run of one scenario on one target."""

    id: str = Field(description="Unique trial id.")
    experiment_id: str = Field(description="Experiment this trial belongs to.")
    target: str = Field(description="Name of the target that ran it.")
    scenario: str = Field(description="Scenario `id@version`.")
    repeat: int = Field(description="Zero-based repeat index within the experiment.")
    status: TrialStatus = Field(
        description="`running`, then `passed` or `failed` once graded, or `error` if it could not be graded."
    )
    record: TrialRecord = Field(default=TrialRecord(), description="Captured evidence and check results.")

    @property
    def graded(self) -> bool:
        return self.status in ("passed", "failed")


class TargetInfo(BaseModel):
    """A target as it was when the experiment was planned."""

    mode: TargetMode = Field(description="How the harness is reached: `native`, `http` or `otel`.")
    url: str | None = Field(description="Harness base URL; null for targets without one.")
    version: str = Field(description="Version label of the system under test.")
    manifest: Manifest | None = Field(description="The harness manifest, live or as declared; null if none.")


class ExperimentMeta(BaseModel):
    """The plan of an experiment, pinned at start so history stays reproducible."""

    targets: dict[str, TargetInfo] = Field(description="Participating targets by name.")
    scenarios: dict[str, Scenario] = Field(description="Scenarios run, by `id@version`, as they were at start.")
    environments: dict[str, EnvironmentSpec] = Field(
        default={}, description="Environment specs pinned at plan time; absent in history recorded before pinning."
    )
    repeats: int = Field(description="Times each scenario ran on each target.")
    fixture_url: str = Field(description="Base URL of the fixture service as agents saw it.")
    forked_from: ResumeFrom | None = Field(
        default=None, description="Checkpoint this experiment forked, if it is a fork."
    )
    candidate: str | None = Field(default=None, description="Target being judged for release.")
    baseline: str | None = Field(default=None, description="Target the candidate is compared against, if any.")
    max_regression: float = Field(
        default=0.0, description="Pass-rate drop vs the baseline that is tolerated, from 0 to 1."
    )
    planned_trials: int = Field(default=0, description="Total trials planned at start.")


class TargetStats(BaseModel):
    """Aggregate results for one target."""

    passed: int = Field(description="Graded trials that passed.")
    graded: int = Field(description="Trials that were graded (passed or failed).")
    errors: int = Field(description="Trials that could not be graded; excluded from rates.")
    pass_rate: float | None = Field(description="`passed / graded` from 0 to 1; null when nothing was graded.")
    ci95: tuple[float, float] = Field(description="95% Wilson confidence interval of the pass rate, as (low, high).")
    p50_ms: float | None = Field(description="Median latency of graded trials, in milliseconds.")
    p95_ms: float | None = Field(description="95th-percentile latency of graded trials, in milliseconds.")
    cost_usd: float | None = Field(description="Total agent spend in US dollars; null if no trial reported cost.")
    pass_all_k: float | None = Field(
        default=None,
        description="pass^k: share of scenarios whose every repeat passed (k = repeats); exposes flakiness a pass "
        "rate hides.",
    )
    k: int = Field(default=1, description="Most repeats any scenario had; the k in `pass_all_k`.")


class Paired(BaseModel):
    """Same scenario and repeat compared between baseline and candidate, where both were graded."""

    pairs: int = Field(description="Scenario-repeat pairs graded on both targets.")
    regressions: int = Field(description="Pairs that passed on the baseline but failed on the candidate.")
    fixes: int = Field(description="Pairs that failed on the baseline but passed on the candidate.")


class Decision(BaseModel):
    """The release decision for a candidate."""

    status: GateStatus = Field(
        description="`PASS`, `BLOCK` (a critical check failed or the pass rate regressed), or `INSUFFICIENT_EVIDENCE` "
        "(errors or unsupported critical checks)."
    )
    candidate: str = Field(description="Target being judged.")
    baseline: str | None = Field(description="Target compared against, if any.")
    block_reasons: list[str] = Field(description="Why the release is blocked; empty unless `BLOCK`.")
    insufficient_reasons: list[str] = Field(
        description="What evidence is missing; empty unless `INSUFFICIENT_EVIDENCE`."
    )
    coverage_gaps: list[str] = Field(description="Non-critical checks the harness could not support.")
    stats: dict[str, TargetStats] = Field(description="Aggregates per target name (candidate and baseline).")
    paired: Paired | None = Field(description="Candidate-vs-baseline comparison; null without a baseline.")


class Experiment(BaseModel):
    """A batch of trials with its plan and release decision."""

    id: str = Field(description="Unique experiment id.")
    created_at: datetime = Field(description="When the experiment was planned.")
    meta: ExperimentMeta = Field(description="The pinned plan.")
    decision: Decision | None = Field(default=None, description="Release decision; null until all trials finish.")
