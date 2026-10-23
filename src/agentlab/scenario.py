"""Versioned, harness-independent test scenarios loaded from YAML."""

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from agentlab.assertions import Assertion, Budget, RetiredCheck
from agentlab.protocol import JsonObject, ToolFault
from agentlab.records import Row

SCENARIO_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")


class ScenarioFault(ToolFault):
    """A tool fault plus the layer that applies it."""

    boundary: Literal["fixture", "harness"] = Field(
        default="fixture",
        description="`fixture`: injected by the environment service, works for every harness. `harness`: sent in "
        '`tool_faults` and applied by the adapter (needs `intercept_tools="declared_only"`).',
    )


class Scenario(BaseModel):
    """A versioned, harness-independent test case: input, starting data, faults and assertions."""

    id: str = Field(description="Scenario id: 1-64 lowercase letters, digits, `.`, `_` or `-`; also the file name.")
    version: int = Field(ge=1, description="Bumped on every change; results are always tied to `id@version`.")
    risk_tier: Literal["critical", "high", "normal"] = Field(
        default="normal",
        description="How much a failure matters; a label shown in the console, it does not change grading.",
    )
    source: str = Field(
        default="synthetic", description="Free-form label for where the case came from; informational only."
    )
    slices: list[str] = Field(default=[], description="Free-form tags for grouping results, e.g. `refund`, `timeout`.")
    environment: str = Field(default="refund@2", description="Environment `id@version` the scenario runs in.")
    seed: dict[str, list[Row]] = Field(
        default={}, description="Rows inserted before the run, keyed by table name; each row maps column to value."
    )
    input: JsonObject = Field(description="Payload handed to the agent as the invoke `input`.")
    faults: list[ScenarioFault] = Field(default=[], description="Scripted tool failures to inject during the run.")
    assertions: list[Assertion] = Field(description="Checks that decide pass or fail.")
    budget: Budget = Field(default=Budget(), description="Optional ceilings on tool calls, latency and cost.")

    @model_validator(mode="before")
    @classmethod
    def _legacy_fixture(cls, data: object) -> object:
        """Stored history and old files carry `fixture: {customers, orders, approval_limit_cents}`: refund@1 seeds."""
        if not (isinstance(data, dict) and "fixture" in data):
            return data
        legacy = data["fixture"] or {}
        limit = legacy.get("approval_limit_cents", 50_000)
        seed = {
            "customers": legacy.get("customers", []),
            "orders": legacy.get("orders", []),
            "settings": [{"key": "approval_limit_cents", "value": limit}],
        }
        return {**{k: v for k, v in data.items() if k != "fixture"}, "environment": "refund@1", "seed": seed}

    @field_validator("id")
    @classmethod
    def _id_is_a_safe_file_name(cls, value: str) -> str:
        if not SCENARIO_ID.fullmatch(value):  # it becomes a file name and part of every trial id
            raise ValueError("use 1-64 lowercase letters, digits, '.', '_' or '-', starting with a letter or digit")
        return value

    @property
    def key(self) -> str:
        return f"{self.id}@{self.version}"

    def faults_at(self, boundary: Literal["fixture", "harness"]) -> list[ToolFault]:
        return [
            ToolFault.model_validate(f.model_dump(exclude={"boundary"})) for f in self.faults if f.boundary == boundary
        ]


def retired(s: Scenario) -> list[str]:
    """Checks a new or edited scenario may not use (history still loads them)."""
    return [
        f"assertions.{i}: {a.type} is retired; use a decision check"
        for i, a in enumerate(s.assertions)
        if isinstance(a, RetiredCheck)
    ]


def load_suite(path: str | Path) -> list[Scenario]:
    path = Path(path)
    files = sorted(path.glob("*.y*ml")) if path.is_dir() else [path]
    if not files:
        raise ValueError(f"no scenario files in {path}")
    scenarios = [Scenario.model_validate(yaml.safe_load(f.read_text())) for f in files]
    if problems := [f"{s.key}: {p}" for s in scenarios for p in retired(s)]:
        raise ValueError("; ".join(problems))
    keys = [s.key for s in scenarios]
    if len(keys) != len(set(keys)):
        raise ValueError(f"duplicate scenario id@version in {path}")
    return scenarios
