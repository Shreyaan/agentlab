"""Tool layer and LLM settings shared by the Python example agents: tools come from the environment's catalog."""

import json
import os
import re
from pathlib import Path
from typing import Self

import httpx
from pydantic import JsonValue

from agentlab.adapter import Recorder
from agentlab.environment import ToolCatalog
from agentlab.protocol import JsonObject

OPENROUTER_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "z-ai/glm-5.3-flash"
MAX_STEPS = 10
_PROMPTS = Path(__file__).parent / "prompts"


def load_catalog(base_url: str) -> ToolCatalog:
    response = httpx.get(f"{base_url.rstrip('/')}/tools", timeout=10)
    response.raise_for_status()
    return ToolCatalog.model_validate(response.json())


def system_prompt(catalog: ToolCatalog) -> str:
    return f"{load_prompt(prompt_name())}\n\nEnvironment: {catalog.description}"


class EnvTools:
    """The environment's tool catalog, loaded once per run. `call` makes exactly one POST inside `rec.tool`."""

    def __init__(self, base_url: str, rec: Recorder) -> None:
        self._http = httpx.Client(base_url=base_url.rstrip("/"), timeout=10)
        self._rec = rec
        catalog = load_catalog(base_url)
        self.system_prompt = system_prompt(catalog)
        self.schemas: list[JsonObject] = [
            {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
            for t in catalog.tools
        ]
        self._names = {t.name for t in catalog.tools}

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self._http.close()

    def _post(self, name: str, arguments: JsonObject) -> JsonValue:
        response = self._http.post(f"/tools/{name}", json=arguments)
        if response.is_error:  # 4xx/5xx; a 504 may still have committed
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:500]}")
        return response.json()

    def call(self, name: str, arguments: JsonObject) -> str:
        """Execute a model-requested tool; any failure becomes an error result the model can react to."""
        if name not in self._names:  # the model chooses `name`: only catalog tools are callable
            return json.dumps({"error": f"unknown tool {name!r}"})
        try:
            return json.dumps(self._rec.tool(name, lambda: self._post(name, arguments)))
        except Exception as exc:  # noqa: BLE001 - tool failures are results the model must see, not crashes
            return json.dumps({"error": str(exc)})


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
