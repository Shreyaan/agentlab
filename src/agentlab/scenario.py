"""Versioned, harness-independent test scenarios loaded from YAML."""

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel

from agentlab.assertions import Assertion, Budget
from agentlab.fixture import Fault, Seed


class Scenario(BaseModel):
    id: str
    version: int
    risk_tier: Literal["critical", "high", "normal"] = "normal"
    source: str = "synthetic"
    slices: list[str] = []
    fixture: Seed
    input: dict[str, Any]
    faults: list[Fault] = []
    assertions: list[Assertion]
    budget: Budget = Budget()

    @property
    def key(self) -> str:
        return f"{self.id}@{self.version}"


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
