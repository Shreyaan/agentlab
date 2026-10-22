"""AgentLab BYOH wire protocol v0.3: the language-neutral contract between the runner and any harness.

JSON Schema for these models is published with `agentlab schema`; adapters in any language implement it.
"""

import secrets
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, JsonValue

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
    invoke: bool = True
    observe: Literal["native_events", "otel_partial", "none"] = "none"
    intercept_tools: Literal["declared_only", "none"] = "none"
    checkpoint: bool = False
    resume: bool = False
    fork: bool = False


class Manifest(BaseModel):
    protocol_version: str = PROTOCOL_VERSION
    adapter_id: str
    language: str
    framework: str = "custom"
    transport: Literal["http_json"] = "http_json"
    capabilities: Capabilities = Capabilities()


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
    seq: int
    type: EventType
    name: str | None = None  # tool name for tool_* events
    ts: float | None = None  # unix seconds; ordering uses seq, never ts across runtimes
    span_id: str | None = None
    parent_id: str | None = None
    # tool_failed: {"injected": bool, "committed": bool} when a harness fault fired.
    # checkpoint_saved: {"checkpoint_id": str}.
    data: JsonObject = {}


class ToolFault(BaseModel):
    """A scripted tool failure. Applied by the fixture service, or by the harness when sent in `tool_faults`."""

    tool: str
    when: FaultWhen = "first_call"
    # timeout_after_commit: the side effect happens, the caller sees a failure. error_before_commit: no side effect.
    action: FaultAction

    def fires_on(self, tool: str, call_number: int) -> bool:
        return self.tool == tool and (
            self.when == "always" or (self.when == "first_call" and call_number == 1) or self.when == call_number
        )


class Environment(BaseModel):
    id: str
    base_url: str  # the fixture service the agent must use for every tool call


class ResumeFrom(BaseModel):
    """Continue a prior run from one of its checkpoints. Only for adapters declaring resume/fork."""

    trial_id: str
    checkpoint_id: str


class InvokeRequest(BaseModel):
    protocol_version: str = PROTOCOL_VERSION
    trial_id: str
    scenario_version: str
    system_version: str
    environment: Environment
    idempotency_key: str
    input: JsonObject
    deadline_ms: int = 60_000
    traceparent: str | None = None
    tool_faults: list[ToolFault] = []  # harness-boundary faults; requires intercept_tools="declared_only"
    resume_from: ResumeFrom | None = None


class Usage(BaseModel):
    steps: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None


class InvokeResponse(BaseModel):
    run_id: str
    status: Literal["completed", "failed"]
    output: JsonValue = None
    events: list[Event] = []
    usage: Usage = Usage()


class ErrorBody(BaseModel):
    code: ErrorCode
    message: str


def json_schemas() -> dict[str, JsonObject]:
    models: list[type[BaseModel]] = [Manifest, InvokeRequest, InvokeResponse, Event, ErrorBody]
    return {m.__name__: m.model_json_schema() for m in models}


def new_traceparent() -> str:
    return f"00-{secrets.token_hex(16)}-{secrets.token_hex(8)}-01"
