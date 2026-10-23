"""Talks to a harness over the wire protocol. Every transport failure becomes a typed AgentLabError."""

import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx
import yaml
from pydantic import BaseModel, Field, JsonValue, ValidationError

from agentlab.models import TargetMode
from agentlab.protocol import (
    PROTOCOL_VERSION,
    AgentLabError,
    Capabilities,
    ErrorCode,
    InvokeRequest,
    InvokeResponse,
    Manifest,
)

DEFAULT_ALLOWED_HOSTS = ["127.0.0.1", "localhost", "::1"]


class TargetSpec(BaseModel):
    """How to reach a harness, as written under `targets:` in the targets file."""

    mode: TargetMode = Field(
        description="`native`: harness implements the AgentLab protocol. `http`: any endpoint that takes the scenario "
        "input as a JSON POST. `otel`: observe-only, cannot be invoked."
    )
    url: str | None = Field(
        default=None,
        description="Harness base URL (native) or endpoint to POST to (http); its host must be in `allowed_hosts`.",
    )
    version: str = Field(default="unversioned", description="Version label of the system under test, shown in results.")
    manifest: Manifest | None = Field(
        default=None, description="Capabilities declared by the user for http/otel targets, which expose no manifest."
    )


class Target(TargetSpec):
    """A named target."""

    name: str = Field(description="Target name used in runs and results.")


class TargetsFile(BaseModel):
    allowed_hosts: list[str] = Field(
        default=DEFAULT_ALLOWED_HOSTS,
        description="Hosts a target URL may point at; guards against hitting real systems.",
    )
    targets: dict[str, TargetSpec] = Field(description="Targets by name.")


def load_targets(path: str | Path) -> tuple[dict[str, Target], list[str]]:
    cfg = TargetsFile.model_validate(yaml.safe_load(Path(path).read_text()))
    return {name: Target(name=name, **t.model_dump()) for name, t in cfg.targets.items()}, cfg.allowed_hosts


class HarnessClient:
    def __init__(self, target: Target, allowed_hosts: list[str]) -> None:
        self.target = target
        if target.mode != "otel":
            host = urlparse(target.url or "").hostname
            if host not in allowed_hosts:  # mutating scenarios must never reach a non-test endpoint
                raise AgentLabError(ErrorCode.UNSAFE_TARGET, f"{target.name}: host {host!r} not in allowed_hosts")

    def manifest(self, timeout: float = 10) -> Manifest:
        t = self.target
        if t.mode == "otel":
            return Manifest(
                adapter_id=t.name, language="unknown", capabilities=Capabilities(invoke=False, observe="otel_partial")
            )
        if t.mode == "http":
            return t.manifest or Manifest(adapter_id=t.name, language="unknown")
        m = _parse(Manifest, self._request("GET", f"{t.url}/manifest", timeout=timeout))
        if m.protocol_version != PROTOCOL_VERSION:
            raise AgentLabError(
                ErrorCode.PROTOCOL_VERSION_MISMATCH, f"{t.name} speaks {m.protocol_version}, runner {PROTOCOL_VERSION}"
            )
        return m

    def invoke(self, req: InvokeRequest) -> InvokeResponse:
        t, timeout = self.target, req.deadline_ms / 1000
        if t.mode == "otel":
            raise AgentLabError(ErrorCode.CAPABILITY_UNSUPPORTED, f"{t.name} is observe-only; it cannot be invoked")
        if t.mode == "native":
            body = self._request("POST", f"{t.url}/invoke", json=req.model_dump(mode="json"), timeout=timeout)
            return _parse(InvokeResponse, body)
        # Generic HTTP: post the scenario input as-is; any 2xx JSON body is the output. No events.
        # shortcut: no request/response field mapping yet, add it when a real API needs a different shape.
        try:
            r = httpx.post(str(t.url), json=req.input, headers={"traceparent": req.traceparent or ""}, timeout=timeout)
        except httpx.TimeoutException as exc:
            raise AgentLabError(ErrorCode.ADAPTER_TIMEOUT, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise AgentLabError(ErrorCode.ADAPTER_ERROR, str(exc)) from exc
        if r.is_success:
            return InvokeResponse(run_id=str(uuid.uuid4()), status="completed", output=_json_or_text(r))
        return InvokeResponse(
            run_id=str(uuid.uuid4()), status="failed", output={"http_status": r.status_code, "body": r.text[:2000]}
        )

    def _request(self, method: str, url: str, *, json: JsonValue = None, timeout: float) -> JsonValue:
        try:
            r = httpx.request(method, url, json=json, timeout=timeout)
        except httpx.TimeoutException as exc:
            raise AgentLabError(ErrorCode.ADAPTER_TIMEOUT, f"{url}: {exc}") from exc
        except httpx.HTTPError as exc:
            raise AgentLabError(ErrorCode.ADAPTER_ERROR, f"{url}: {exc}") from exc
        for code in (ErrorCode.PROTOCOL_VERSION_MISMATCH, ErrorCode.CAPABILITY_UNSUPPORTED):
            if r.status_code == 400 and code in r.text:
                raise AgentLabError(code, r.text[:500])
        if not r.is_success:
            raise AgentLabError(ErrorCode.ADAPTER_ERROR, f"{url}: HTTP {r.status_code} {r.text[:500]}")
        try:
            return r.json()
        except ValueError as exc:
            raise AgentLabError(ErrorCode.ADAPTER_ERROR, f"{url}: non-JSON body") from exc


def _json_or_text(r: httpx.Response) -> JsonValue:
    try:
        return r.json()
    except ValueError:
        return r.text


def _parse[M: BaseModel](model: type[M], data: JsonValue) -> M:
    try:
        return model.model_validate(data)
    except ValidationError as exc:  # a malformed adapter response is a protocol defect, not an agent result
        raise AgentLabError(ErrorCode.ADAPTER_ERROR, f"invalid {model.__name__}: {exc}") from exc
