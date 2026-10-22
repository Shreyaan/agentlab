"""Versioned, harness-independent test scenarios loaded from YAML."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

from agentlab.assertions import Assertion, Budget
from agentlab.fixture import Seed
from agentlab.protocol import JsonObject, ToolFault


class ScenarioFault(ToolFault):
    # fixture: injected by the environment service (works for every harness).
    # harness: sent in `tool_faults`, applied by the adapter (needs intercept_tools="declared_only").
    boundary: Literal["fixture", "harness"] = "fixture"


class Scenario(BaseModel):
    id: str
    version: int
    risk_tier: Literal["critical", "high", "normal"] = "normal"
    source: str = "synthetic"
    slices: list[str] = []
    fixture: Seed
    input: JsonObject
    faults: list[ScenarioFault] = []
    assertions: list[Assertion]
    budget: Budget = Budget()

    @property
    def key(self) -> str:
        return f"{self.id}@{self.version}"

    def faults_at(self, boundary: Literal["fixture", "harness"]) -> list[ToolFault]:
        return [
            ToolFault.model_validate(f.model_dump(exclude={"boundary"})) for f in self.faults if f.boundary == boundary
        ]


def load_suite(path: str | Path) -> list[Scenario]:
    path = Path(path)
    files = sorted(path.glob("*.y*ml")) if path.is_dir() else [path]
    if not files:
        raise ValueError(f"no scenario files in {path}")
    scenarios = [Scenario.model_validate(yaml.safe_load(f.read_text())) for f in files]
    keys = [s.key for s in scenarios]
    if len(keys) != len(set(keys)):
        raise ValueError(f"duplicate scenario id@version in {path}")
    return scenarios
