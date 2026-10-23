"""AgentLab BYOH wire protocol v0.3: the language-neutral contract between the runner and any harness.

JSON Schema for these models is published with `agentlab schema`; adapters in any language implement it.
"""

import secrets
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, JsonValue

PROTOCOL_VERSION = "0.3"

type JsonObject = dict[str, JsonValue]


class ErrorCode(StrEnum):
    CAPABILITY_UNSUPPORTED = "CAPABILITY_UNSUPPORTED"
    PROTOCOL_VERSION_MISMATCH = "PROTOCOL_VERSION_MISMATCH"
    UNSAFE_TARGET = "UNSAFE_TARGET"
    ENVIRONMENT_NOT_RESETTABLE = "ENVIRONMENT_NOT_RESETTABLE"
    ADAPTER_TIMEOUT = "ADAPTER_TIMEOUT"
    ADAPTER_ERROR = "ADAPTER_ERROR"
    TRACE_INCOMPLETE = "TRACE_INCOMPLETE"


class AgentLabError(Exception):
    """Adapter/infrastructure failure. Never counted as an agent pass or fail."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class Capabilities(BaseModel):
    """What a harness can do beyond plain invoke; the runner skips or marks checks the harness cannot support."""

    invoke: bool = Field(default=True, description="Accepts `POST /invoke`. Always true for a working harness.")
    observe: Literal["native_events", "otel_partial", "none"] = Field(
        default="none",
        description="How much of the run the harness reveals: `native_events` streams the full event list in the "
        "response, `otel_partial` exports OpenTelemetry spans only, `none` is a black box.",
    )
    intercept_tools: Literal["declared_only", "none"] = Field(
        default="none",
        description="`declared_only` means the harness applies the `tool_faults` it receives at its own tool "
        "boundary; `none` means it ignores them.",
    )
    checkpoint: bool = Field(
        default=False, description="Emits `checkpoint_saved` events that a run can be resumed from."
    )
    resume: bool = Field(default=False, description="Can continue a prior trial from a checkpoint (`resume_from`).")
    fork: bool = Field(
        default=False, description="Can branch a prior trial's checkpoint into a new run (`resume_from`)."
    )


class Manifest(BaseModel):
    """A harness's self-description, returned by `GET /manifest`."""

    protocol_version: str = Field(
        default=PROTOCOL_VERSION, description="Wire protocol version the harness speaks; a mismatch is refused."
    )
    adapter_id: str = Field(description="Stable identifier of this adapter, e.g. `acme-support-bot`.")
    language: str = Field(description="Language the harness is written in, e.g. `python` or `typescript`.")
    framework: str = Field(default="custom", description="Agent framework in use, e.g. `langgraph`; `custom` if none.")
    transport: Literal["http_json"] = Field(default="http_json", description="Wire transport; only HTTP+JSON exists.")
    capabilities: Capabilities = Field(default=Capabilities(), description="Optional features the harness supports.")


type EventType = Literal[
    "run_started",
    "agent_step",
    "model_call",
    "tool_requested",
    "tool_completed",
    "tool_failed",
    "approval_requested",
    "retry_scheduled",
    "checkpoint_saved",
    "run_completed",
    "run_failed",
]
type FaultAction = Literal["timeout_after_commit", "error_before_commit"]
type FaultWhen = Literal["first_call", "always"] | int  # int = nth call (1-based)


class Event(BaseModel):
    """One step the harness reports about its own run (only when `observe` is `native_events`)."""

    seq: int = Field(description="Position in the run, starting at 1. Ordering always uses `seq`, never `ts`.")
    type: EventType = Field(description="What happened, e.g. `tool_requested` or `model_call`.")
    name: str | None = Field(default=None, description="Tool name, for `tool_*` events.")
    ts: float | None = Field(
        default=None, description="Unix time in seconds; informational, clocks differ across runtimes."
    )
    span_id: str | None = Field(default=None, description="Identifier of this step, for correlating with traces.")
    parent_id: str | None = Field(default=None, description="`span_id` of the step that caused this one.")
    data: JsonObject = Field(
        default={},
        description='Event payload. `tool_failed`: `{"injected": bool, "committed": bool}` when a fault fired. '
        '`checkpoint_saved`: `{"checkpoint_id": str}`.',
    )


class ToolFault(BaseModel):
    """A scripted tool failure. Applied by the fixture service, or by the harness when sent in `tool_faults`."""

    tool: str = Field(description="Name of the tool to break.")
    when: FaultWhen = Field(
        default="first_call",
        description="Which calls fail: `first_call`, `always`, or an integer N for the Nth call (1-based).",
    )
    action: FaultAction = Field(
        description="`timeout_after_commit`: the side effect happens but the caller sees a failure. "
        "`error_before_commit`: the call fails with no side effect."
    )

    def fires_on(self, tool: str, call_number: int) -> bool:
        return self.tool == tool and (
            self.when == "always" or (self.when == "first_call" and call_number == 1) or self.when == call_number
        )


class Environment(BaseModel):
    """The fixture environment a trial runs against."""

    id: str = Field(description="Environment `id@version` key, e.g. `refund@2`.")
    base_url: str = Field(description="Fixture service URL the agent must use for every tool call.")


class ResumeFrom(BaseModel):
    """Continue a prior run from one of its checkpoints. Only for adapters declaring resume/fork."""

    trial_id: str = Field(description="Trial whose run to continue.")
    checkpoint_id: str = Field(description="`checkpoint_id` from one of that trial's `checkpoint_saved` events.")


class InvokeRequest(BaseModel):
    """Body of `POST /invoke`: one trial for the harness to run."""

    protocol_version: str = Field(default=PROTOCOL_VERSION, description="Wire protocol version of the sender.")
    trial_id: str = Field(description="Unique id of this trial (one scenario, one repeat, one target).")
    scenario_version: str = Field(description="Scenario `id@version` being run.")
    system_version: str = Field(description="Version label of the system under test, from the target config.")
    environment: Environment = Field(description="Where the agent's tools live.")
    idempotency_key: str = Field(
        description="Stable key for this invocation (`<trial_id>:invoke`), "
        "so a harness can de-duplicate a retried request."
    )
    input: JsonObject = Field(description="The scenario's `input`, handed to the agent as-is.")
    deadline_ms: int = Field(default=60_000, description="Time budget for the whole invocation, in milliseconds.")
    traceparent: str | None = Field(
        default=None, description="W3C `traceparent` header value, so the harness can join the runner's trace."
    )
    tool_faults: list[ToolFault] = Field(
        default=[],
        description="Faults the harness must apply at its own tool boundary; "
        'sent only to `intercept_tools="declared_only"`.',
    )
    resume_from: ResumeFrom | None = Field(
        default=None, description="Checkpoint to continue from, for resume/fork runs."
    )


class Usage(BaseModel):
    """Resource use the harness reports for a run; omitted values are unknown, not zero."""

    steps: int | None = Field(default=None, description="Agent steps taken.")
    input_tokens: int | None = Field(default=None, description="Prompt tokens consumed across all model calls.")
    output_tokens: int | None = Field(default=None, description="Completion tokens produced across all model calls.")
    cost_usd: float | None = Field(default=None, description="Total model spend in US dollars.")


class InvokeResponse(BaseModel):
    """Body returned by `POST /invoke`."""

    run_id: str = Field(description="Harness-side identifier of this run.")
    status: Literal["completed", "failed"] = Field(
        description="Whether the agent finished its run; this is not a grading result."
    )
    output: JsonValue = Field(default=None, description="The agent's final answer, in any JSON shape.")
    events: list[Event] = Field(default=[], description="Ordered steps the agent took, if `observe` allows.")
    usage: Usage = Field(default=Usage(), description="Resources used by the run.")


class ErrorBody(BaseModel):
    """Error body a harness returns on a non-2xx response."""

    code: ErrorCode = Field(description="Machine-readable failure category.")
    message: str = Field(description="Human-readable explanation; must not contain secrets.")


def json_schemas() -> dict[str, JsonObject]:
    models: list[type[BaseModel]] = [Manifest, InvokeRequest, InvokeResponse, Event, ErrorBody]
    return {m.__name__: m.model_json_schema() for m in models}


def new_traceparent() -> str:
    return f"00-{secrets.token_hex(16)}-{secrets.token_hex(8)}-01"
