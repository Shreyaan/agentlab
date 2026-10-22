"""Talks to a harness over the wire protocol. Every transport failure becomes a typed AgentLabError."""

import uuid
from typing import Literal
from urllib.parse import urlparse

import httpx
import yaml
from pydantic import BaseModel, ValidationError

from agentlab.protocol import (
    PROTOCOL_VERSION, AgentLabError, Capabilities, ErrorCode, InvokeRequest, InvokeResponse, Manifest,
)

DEFAULT_ALLOWED_HOSTS = ["127.0.0.1", "localhost", "::1"]


class Target(BaseModel):
    name: str
    mode: Literal["native", "http", "otel"]
    url: str | None = None
    version: str = "unversioned"
    manifest: Manifest | None = None  # declared by the user for http/otel targets, which expose none


class TargetsFile(BaseModel):
    allowed_hosts: list[str] = DEFAULT_ALLOWED_HOSTS
    targets: dict[str, dict]


def load_targets(path: str) -> tuple[dict[str, Target], list[str]]:
    with open(path) as f:
        cfg = TargetsFile.model_validate(yaml.safe_load(f))
    return {name: Target(name=name, **t) for name, t in cfg.targets.items()}, cfg.allowed_hosts


class HarnessClient:
    def __init__(self, target: Target, allowed_hosts: list[str]):
        self.target = target
        if target.mode != "otel":
            host = urlparse(target.url or "").hostname
            if host not in allowed_hosts:  # mutating scenarios must never reach a non-test endpoint
                raise AgentLabError(ErrorCode.UNSAFE_TARGET, f"{target.name}: host {host!r} not in allowed_hosts")

    def manifest(self) -> Manifest:
        t = self.target
        if t.mode == "otel":
            return Manifest(adapter_id=t.name, language="unknown", capabilities=Capabilities(invoke=False, observe="otel_partial"))
        if t.mode == "http":
            return t.manifest or Manifest(adapter_id=t.name, language="unknown")
        m = _parse(Manifest, self._request("GET", f"{t.url}/manifest", timeout=10))
        if m.protocol_version != PROTOCOL_VERSION:
            raise AgentLabError(ErrorCode.PROTOCOL_VERSION_MISMATCH, f"{t.name} speaks {m.protocol_version}, runner {PROTOCOL_VERSION}")
        return m

    def invoke(self, req: InvokeRequest) -> InvokeResponse:
        t, timeout = self.target, req.deadline_ms / 1000
        if t.mode == "otel":
            raise AgentLabError(ErrorCode.CAPABILITY_UNSUPPORTED, f"{t.name} is observe-only; it cannot be invoked")
        if t.mode == "native":
            return _parse(InvokeResponse, self._request("POST", f"{t.url}/invoke", json=req.model_dump(mode="json"), timeout=timeout))
        # Generic HTTP: post the scenario input as-is; any 2xx JSON body is the output. No events.
        # shortcut: no request/response field mapping yet, add it when a real API needs a different shape.
        try:
            r = httpx.post(t.url, json=req.input, headers={"traceparent": req.traceparent or ""}, timeout=timeout)
        except httpx.TimeoutException as exc:
            raise AgentLabError(ErrorCode.ADAPTER_TIMEOUT, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise AgentLabError(ErrorCode.ADAPTER_ERROR, str(exc)) from exc
        ok = r.is_success
        return InvokeResponse(run_id=str(uuid.uuid4()), status="completed" if ok else "failed",
                              output=_json_or_text(r) if ok else {"http_status": r.status_code, "body": r.text[:2000]})

    def _request(self, method: str, url: str, **kw) -> dict:
        try:
            r = httpx.request(method, url, **kw)
        except httpx.TimeoutException as exc:
            raise AgentLabError(ErrorCode.ADAPTER_TIMEOUT, f"{url}: {exc}") from exc
        except httpx.HTTPError as exc:
            raise AgentLabError(ErrorCode.ADAPTER_ERROR, f"{url}: {exc}") from exc
        if r.status_code == 400 and "PROTOCOL_VERSION_MISMATCH" in r.text:
            raise AgentLabError(ErrorCode.PROTOCOL_VERSION_MISMATCH, r.text)
        if not r.is_success:
            raise AgentLabError(ErrorCode.ADAPTER_ERROR, f"{url}: HTTP {r.status_code} {r.text[:500]}")
        try:
            return r.json()
        except ValueError as exc:
            raise AgentLabError(ErrorCode.ADAPTER_ERROR, f"{url}: non-JSON body") from exc


def _json_or_text(r: httpx.Response):
    try:
        return r.json()
    except ValueError:
        return r.text



def _parse[M: BaseModel](model: type[M], data: dict) -> M:
    try:
        return model.model_validate(data)
    except ValidationError as exc:  # a malformed adapter response is a protocol defect, not an agent result
        raise AgentLabError(ErrorCode.ADAPTER_ERROR, f"invalid {model.__name__}: {exc}") from exc
