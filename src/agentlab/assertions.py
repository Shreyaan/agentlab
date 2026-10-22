"""Graders, in precedence order: executable environment state first, then process (ledger/events), then output text."""

import re
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from agentlab.fixture import Fixture
from agentlab.protocol import Capabilities, Event, Usage


@dataclass
class Evidence:
    fixture: Fixture
    ledger: list[dict]
    events: list[Event]
    output: Any
    capabilities: Capabilities
    latency_ms: float
    usage: Usage


class Result(BaseModel):
    type: str
    description: str
    critical: bool
    status: Literal["pass", "fail", "unsupported"]
    detail: str = ""


class _Base(BaseModel):
    critical: bool = False
    description: str = ""

    def result(self, status: str, detail: str = "") -> Result:
        return Result(type=self.type, description=self.description or self.default_description(),
                      critical=self.critical, status=status, detail=detail)


class Sql(_Base):
    """Read-only SQL over the fixture's final state; a single-cell result is compared as a scalar."""

    type: Literal["sql"]
    query: str
    equals: Any

    def default_description(self) -> str:
        return f"{self.query} == {self.equals!r}"

    def check(self, ev: Evidence) -> Result:
        rows = ev.fixture.query(self.query)
        value = rows[0][0] if len(rows) == 1 and len(rows[0]) == 1 else rows
        return self.result("pass" if value == self.equals else "fail", f"got {value!r}")


class ToolOrder(_Base):
    """`requires` must succeed (2xx) in the side-effect ledger before the first `before` call."""

    type: Literal["tool_order"]
    before: str
    requires: str

    def default_description(self) -> str:
        return f"{self.requires} succeeds before {self.before}"

    def check(self, ev: Evidence) -> Result:
        tools = [(e["tool"], e["status"]) for e in ev.ledger]
        first = next((i for i, (t, _) in enumerate(tools) if t == self.before), None)
        if first is None:
            return self.result("pass", f"{self.before} never called")
        ok = any(t == self.requires and s < 400 for t, s in tools[:first])
        return self.result("pass" if ok else "fail", "" if ok else f"{self.before} at ledger #{first + 1} without {self.requires}")


class ForbiddenTool(_Base):
    type: Literal["forbidden_tool"]
    name: str

    def default_description(self) -> str:
        return f"{self.name} is never called"

    def check(self, ev: Evidence) -> Result:
        n = sum(e["tool"] == self.name for e in ev.ledger)
        return self.result("fail" if n else "pass", f"called {n}x" if n else "")


class EventPresent(_Base):
    """Process evidence from inside the harness; unsupported unless the adapter streams native events."""

    type: Literal["event_present"]
    event: str
    name: str | None = None

    def default_description(self) -> str:
        return f"agent reports {self.event}" + (f" for {self.name}" if self.name else "")

    def check(self, ev: Evidence) -> Result:
        if ev.capabilities.observe != "native_events":
            return self.result("unsupported", f"adapter observe={ev.capabilities.observe}")
        hit = any(e.type == self.event and (self.name is None or e.name == self.name) for e in ev.events)
        return self.result("pass" if hit else "fail")


class OutputMatches(_Base):
    type: Literal["output_matches"]
    pattern: str

    def default_description(self) -> str:
        return f"response matches /{self.pattern}/"

    def check(self, ev: Evidence) -> Result:
        text = ev.output if isinstance(ev.output, str) else str(ev.output)
        return self.result("pass" if re.search(self.pattern, text, re.I) else "fail", text[:200])


Assertion = Annotated[Sql | ToolOrder | ForbiddenTool | EventPresent | OutputMatches, Field(discriminator="type")]


class Budget(BaseModel):
    max_tool_calls: int | None = None
    max_latency_ms: int | None = None
    max_cost_usd: float | None = None


def check_budget(budget: Budget, ev: Evidence) -> list[Result]:
    def limit(name: str, actual: float | None, cap: float | None) -> Result | None:
        if cap is None:
            return None
        if actual is None:
            return Result(type="budget", description=f"{name} <= {cap}", critical=False, status="unsupported",
                          detail="not reported by adapter")
        return Result(type="budget", description=f"{name} <= {cap}", critical=False,
                      status="pass" if actual <= cap else "fail", detail=f"actual {actual:g}")

    checks = [
        limit("tool_calls", len(ev.ledger), budget.max_tool_calls),
        limit("latency_ms", ev.latency_ms, budget.max_latency_ms),
        limit("cost_usd", ev.usage.cost_usd, budget.max_cost_usd),
    ]
    return [c for c in checks if c]


def _safe_check(a: _Base, ev: Evidence) -> Result:
    try:
        return a.check(ev)
    except Exception as exc:  # a broken grader is a grader defect, never an agent pass or fail
        return a.result("unsupported", f"grader error: {exc}")


def grade(assertions: list[Assertion], budget: Budget, ev: Evidence) -> list[Result]:
    return [_safe_check(a, ev) for a in assertions] + check_budget(budget, ev)
