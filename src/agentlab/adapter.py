"""Native Python adapter: wraps an existing agent function behind the BYOH wire protocol."""

import time
import uuid
from collections import Counter
from collections.abc import Callable, Sequence
from typing import Literal

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import JsonValue

from agentlab.protocol import (
    PROTOCOL_VERSION,
    ErrorBody,
    ErrorCode,
    Event,
    EventType,
    InvokeRequest,
    InvokeResponse,
    JsonObject,
    Manifest,
    ToolFault,
    Usage,
)


class ToolFaultError(Exception):
    """Raised by `Recorder.tool` when a declared harness fault fires. Agents should treat it like any tool error."""


class Recorder:
    """Collects normalized events for one run and applies declared harness faults. Wrap each tool call in `tool()`."""

    def __init__(self, tool_faults: Sequence[ToolFault] = ()) -> None:
        self.events: list[Event] = []
        self.usage = Usage()
        self._faults = list(tool_faults)
        self._calls: Counter[str] = Counter()

    def emit(self, kind: EventType, name: str | None = None, **data: JsonValue) -> None:
        self.events.append(Event(seq=len(self.events) + 1, type=kind, name=name, ts=time.time(), data=data))

    def tool[T](self, name: str, fn: Callable[[], T]) -> T:
        self._calls[name] += 1
        fault = next((f for f in self._faults if f.fires_on(name, self._calls[name])), None)
        self.emit("tool_requested", name)
        if fault and fault.action == "error_before_commit":
            self.emit("tool_failed", name, error="injected error", injected=True, committed=False)
            raise ToolFaultError(f"{name}: service unavailable (injected)")
        try:
            result = fn()
        except Exception as exc:
            self.emit("tool_failed", name, error=str(exc))
            raise
        if fault:  # timeout_after_commit: the call went through, the agent never learns it
            self.emit("tool_failed", name, error="injected timeout", injected=True, committed=True)
            raise ToolFaultError(f"{name}: upstream timeout (injected)")
        self.emit("tool_completed", name)
        return result


type Handler = Callable[[InvokeRequest, Recorder], JsonValue]


def _error(code: ErrorCode, message: str) -> JSONResponse:
    return JSONResponse(ErrorBody(code=code, message=message).model_dump(mode="json"), status_code=400)


def create_app(manifest: Manifest, handler: Handler) -> FastAPI:
    app = FastAPI(title=f"AgentLab adapter: {manifest.adapter_id}")
    caps = manifest.capabilities

    @app.get("/manifest")
    def get_manifest() -> Manifest:
        return manifest

    @app.post("/invoke", response_model=None)
    def invoke(req: InvokeRequest) -> InvokeResponse | JSONResponse:
        if req.protocol_version != PROTOCOL_VERSION:
            return _error(ErrorCode.PROTOCOL_VERSION_MISMATCH, f"adapter speaks {PROTOCOL_VERSION}")
        if req.tool_faults and caps.intercept_tools == "none":
            return _error(ErrorCode.CAPABILITY_UNSUPPORTED, "adapter does not intercept tools")
        if req.resume_from and not caps.resume:
            return _error(ErrorCode.CAPABILITY_UNSUPPORTED, "adapter cannot resume from checkpoints")
        rec = Recorder(req.tool_faults)
        rec.emit("run_started")
        output: JsonValue
        status: Literal["completed", "failed"] = "completed"
        try:
            output = handler(req, rec)
            rec.emit("run_completed")
        except Exception as exc:  # noqa: BLE001 - an agent crash is an agent failure, reported in-band
            output = {"error": str(exc)}
            status = "failed"
            rec.emit("run_failed", error=str(exc))
        return InvokeResponse(
            run_id=str(uuid.uuid4()), status=status, output=output, events=rec.events, usage=rec.usage
        )

    return app


def serve(manifest: Manifest, handler: Handler, port: int, host: str = "127.0.0.1") -> None:
    uvicorn.run(create_app(manifest, handler), host=host, port=port, log_level="warning")


__all__ = ["Handler", "JsonObject", "Recorder", "ToolFaultError", "create_app", "serve"]
