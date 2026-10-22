"""Tool layer and LLM settings shared by the real-LLM example agents (OpenAI SDK and LangGraph)."""

import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Self

import httpx
from pydantic import JsonValue

from agentlab.adapter import Recorder
from agentlab.protocol import JsonObject

OPENROUTER_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "openai/gpt-4.1-mini"
MAX_STEPS = 10
_PROMPTS = Path(__file__).parent / "prompts"


class RefundApi:
    """Fixture HTTP client bound to one run. Each method makes exactly one request inside `rec.tool`."""

    def __init__(self, base_url: str, rec: Recorder) -> None:
        self._http = httpx.Client(base_url=base_url, timeout=10)
        self._rec = rec
        self._tools: dict[str, Callable[..., JsonValue]] = {
            "get_order": self.get_order,
            "request_approval": self.request_approval,
            "issue_refund": self.issue_refund,
            "get_refunds": self.get_refunds,
        }

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self._http.close()

    def _send(
        self,
        name: str,
        method: str,
        path: str,
        *,
        json: JsonObject | None = None,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
    ) -> JsonValue:
        def send() -> JsonValue:
            response = self._http.request(method, path, json=json, headers=headers, params=params)
            response.raise_for_status()
            return response.json()

        return self._rec.tool(name, send)

    def get_order(self, order_id: str) -> JsonValue:
        return self._send("get_order", "GET", f"/orders/{order_id}")

    def request_approval(self, order_id: str, reason: str = "customer refund request") -> JsonValue:
        return self._send("request_approval", "POST", "/approvals", json={"order_id": order_id, "reason": reason})

    def issue_refund(
        self, order_id: str, amount_cents: int, approval_id: int, idempotency_key: str | None = None
    ) -> JsonValue:
        body = {"order_id": order_id, "amount_cents": amount_cents, "approval_id": approval_id}
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        return self._send("issue_refund", "POST", "/refunds", json=body, headers=headers)

    def get_refunds(self, order_id: str) -> JsonValue:
        return self._send("get_refunds", "GET", "/refunds", params={"order_id": order_id})

    def run_tool(self, name: str, arguments: JsonObject) -> str:
        """Execute a model-requested tool; any failure becomes an error result the model can react to."""
        tool = self._tools.get(name)  # the model chooses `name`: only declared tools are callable
        if tool is None:
            return json.dumps({"error": f"unknown tool {name!r}"})
        try:
            return json.dumps(tool(**arguments))
        except Exception as exc:  # noqa: BLE001 - tool failures are results the model must see, not crashes
            return json.dumps({"error": str(exc)})


def _tool(name: str, description: str, properties: JsonObject, required: list[JsonValue]) -> JsonObject:
    parameters = {"type": "object", "properties": properties, "required": required}
    return {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}


_STR: JsonObject = {"type": "string"}
TOOL_SCHEMAS: list[JsonObject] = [
    _tool("get_order", "Look up an order.", {"order_id": _STR}, ["order_id"]),
    _tool(
        "request_approval",
        "Request approval to refund an order. Returns status granted or denied.",
        {"order_id": _STR, "reason": _STR},
        ["order_id"],
    ),
    _tool(
        "issue_refund",
        "Issue a refund for an order.",
        {
            "order_id": _STR,
            "amount_cents": {"type": "integer"},
            "approval_id": {"type": "integer"},
            "idempotency_key": {**_STR, "description": "Unique per order; reuse it on retries."},
        },
        ["order_id", "amount_cents", "approval_id"],
    ),
    _tool("get_refunds", "List existing refunds for an order.", {"order_id": _STR}, ["order_id"]),
]


def load_prompt(name: str) -> str:
    return (_PROMPTS / f"{name}.md").read_text().strip()


def prompt_name() -> str:
    name = os.environ.get("PROMPT", "careful")
    if not (_PROMPTS / f"{name}.md").exists():
        raise SystemExit(f"unknown PROMPT {name!r}")
    return name


def model_name() -> str:
    return os.environ.get("MODEL", DEFAULT_MODEL)


def api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise SystemExit("OPENROUTER_API_KEY is not set")
    return key


def adapter_id(framework: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", model_name().lower()).strip("-")
    return f"{framework}-{prompt_name()}-{slug}"


def record_model_call(
    rec: Recorder, finish_reason: str | None, input_tokens: int, output_tokens: int, cost: float | None
) -> None:
    """Emit a `model_call` event and fold its usage into the run total."""
    rec.emit("model_call", model=model_name(), finish_reason=finish_reason)
    usage = rec.usage
    usage.steps = (usage.steps or 0) + 1
    usage.input_tokens = (usage.input_tokens or 0) + input_tokens
    usage.output_tokens = (usage.output_tokens or 0) + output_tokens
    if cost is not None:
        usage.cost_usd = (usage.cost_usd or 0.0) + cost
