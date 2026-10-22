"""Native Python adapter: wraps an existing agent function behind the BYOH wire protocol."""

import time
import uuid
from collections.abc import Callable
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from agentlab.protocol import PROTOCOL_VERSION, ErrorBody, ErrorCode, Event, InvokeRequest, InvokeResponse, Manifest


class Recorder:
    """Collects normalized events for one run. Wrap each tool call with `tool()`."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    def emit(self, type: str, name: str | None = None, **data: Any) -> None:
        self.events.append(Event(seq=len(self.events) + 1, type=type, name=name, ts=time.time(), data=data))

    def tool[T](self, name: str, fn: Callable[[], T]) -> T:
        self.emit("tool_requested", name)
        try:
            result = fn()
        except Exception as exc:
            self.emit("tool_failed", name, error=str(exc))
            raise
        self.emit("tool_completed", name)
        return result


Handler = Callable[[InvokeRequest, Recorder], Any]


def create_app(manifest: Manifest, handler: Handler) -> FastAPI:
    app = FastAPI(title=f"AgentLab adapter: {manifest.adapter_id}")

    @app.get("/manifest")
    def get_manifest() -> Manifest:
        return manifest

    @app.post("/invoke")
    def invoke(req: InvokeRequest):
        if req.protocol_version != PROTOCOL_VERSION:
            body = ErrorBody(code=ErrorCode.PROTOCOL_VERSION_MISMATCH, message=f"adapter speaks {PROTOCOL_VERSION}")
            return JSONResponse(body.model_dump(mode="json"), status_code=400)
        rec = Recorder()
        rec.emit("run_started")
        try:
            output, status = handler(req, rec), "completed"
            rec.emit("run_completed")
        except Exception as exc:  # an agent crash is an agent failure, reported in-band
            output, status = {"error": str(exc)}, "failed"
            rec.emit("run_failed", error=str(exc))
        return InvokeResponse(run_id=str(uuid.uuid4()), status=status, output=output, events=rec.events)

    return app


def serve(manifest: Manifest, handler: Handler, port: int, host: str = "127.0.0.1") -> None:
    uvicorn.run(create_app(manifest, handler), host=host, port=port, log_level="warning")
