"""AgentLab BYOH wire protocol v0.2: the language-neutral contract between the runner and any harness.

JSON Schema for these models is published with `agentlab schema`; adapters in any language implement it.
"""

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel

PROTOCOL_VERSION = "0.2"


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

    def __init__(self, code: ErrorCode, message: str):
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


EventType = Literal[
    "run_started", "agent_step", "model_call", "tool_requested", "tool_completed", "tool_failed",
    "approval_requested", "retry_scheduled", "checkpoint_saved", "run_completed", "run_failed",
]


class Event(BaseModel):
    seq: int
    type: EventType
    name: str | None = None  # tool name for tool_* events
    ts: float | None = None  # unix seconds; ordering uses seq, never ts across runtimes
    span_id: str | None = None
    parent_id: str | None = None
    data: dict[str, Any] = {}


class Environment(BaseModel):
    id: str
    base_url: str  # the fixture service the agent must use for every tool call


class InvokeRequest(BaseModel):
    protocol_version: str = PROTOCOL_VERSION
    trial_id: str
    scenario_version: str
    system_version: str
    environment: Environment
    idempotency_key: str
    input: dict[str, Any]
    deadline_ms: int = 60_000
    traceparent: str | None = None


class Usage(BaseModel):
    steps: int | None = None
    cost_usd: float | None = None


class InvokeResponse(BaseModel):
    run_id: str
    status: Literal["completed", "failed"]
    output: Any = None
    events: list[Event] = []
    usage: Usage = Usage()


class ErrorBody(BaseModel):
    code: ErrorCode
    message: str


def json_schemas() -> dict[str, dict]:
    return {m.__name__: m.model_json_schema() for m in (Manifest, InvokeRequest, InvokeResponse, Event, ErrorBody)}


def new_traceparent() -> str:
    import secrets

    return f"00-{secrets.token_hex(16)}-{secrets.token_hex(8)}-01"

