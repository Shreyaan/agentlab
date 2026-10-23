"""Graders, in precedence order: executable environment state first, then process (ledger/events), then output text."""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, Field, JsonValue

from agentlab.fixture import Fixture
from agentlab.protocol import Capabilities, Event, Usage
from agentlab.records import AssertionResult, LedgerEntry

type Status = Literal["pass", "fail", "unsupported", "skipped"]


@dataclass(frozen=True)
class Evidence:
    fixture: Fixture
    ledger: list[LedgerEntry]
    events: list[Event]
    output: JsonValue
    capabilities: Capabilities
    latency_ms: float
    usage: Usage


class _Check(BaseModel, ABC):
    critical: bool = False
    requires_faults: bool = False  # only meaningful when the scenario's faults are active (skipped in clean forks)
    description: str = ""

    @property
    @abstractmethod
    def default_description(self) -> str: ...

    @abstractmethod
    def check(self, ev: Evidence) -> AssertionResult: ...

    def result(self, status: Status, detail: str = "") -> AssertionResult:
        kind = type(self).model_fields["type"].default
        return AssertionResult(
            type=str(kind),
            description=self.description or self.default_description,
            critical=self.critical,
            status=status,
            detail=detail,
        )


class Sql(_Check):
    """Read-only SQL over the environment's final state; a single-cell result is compared as a scalar."""

    type: Literal["sql"] = "sql"
    query: str
    equals: JsonValue

    @property
    def default_description(self) -> str:
        return f"{self.query} == {self.equals!r}"

    def check(self, ev: Evidence) -> AssertionResult:
        rows = ev.fixture.query(self.query)
        value: JsonValue = rows[0][0] if len(rows) == 1 and len(rows[0]) == 1 else [list(r) for r in rows]
        return self.result("pass" if value == self.equals else "fail", f"got {value!r}")


class ToolOrder(_Check):
    """`requires` must succeed (2xx) in the side-effect ledger before the first `before` call."""

    type: Literal["tool_order"] = "tool_order"
    before: str
    requires: str

    @property
    def default_description(self) -> str:
        return f"{self.requires} succeeds before {self.before}"

    def check(self, ev: Evidence) -> AssertionResult:
        first = next((i for i, e in enumerate(ev.ledger) if e.tool == self.before), None)
        if first is None:
            return self.result("pass", f"{self.before} never called")
        if any(e.tool == self.requires and e.status < 400 for e in ev.ledger[:first]):
            return self.result("pass")
        return self.result("fail", f"{self.before} at ledger #{first + 1} without {self.requires}")


class ForbiddenTool(_Check):
    type: Literal["forbidden_tool"] = "forbidden_tool"
    name: str

    @property
    def default_description(self) -> str:
        return f"{self.name} is never called"

    def check(self, ev: Evidence) -> AssertionResult:
        n = sum(e.tool == self.name for e in ev.ledger)
        return self.result("fail", f"called {n}x") if n else self.result("pass")


class EventPresent(_Check):
    """Process evidence from inside the harness; unsupported unless the adapter streams native events."""

    type: Literal["event_present"] = "event_present"
    event: str
    name: str | None = None

    @property
    def default_description(self) -> str:
        return f"agent reports {self.event}" + (f" for {self.name}" if self.name else "")

    def check(self, ev: Evidence) -> AssertionResult:
        if ev.capabilities.observe != "native_events":
            return self.result("unsupported", f"adapter observe={ev.capabilities.observe}")
        hit = any(e.type == self.event and (self.name is None or e.name == self.name) for e in ev.events)
        return self.result("pass" if hit else "fail")


class OutputMatches(_Check):
    type: Literal["output_matches"] = "output_matches"
    pattern: str

    @property
    def default_description(self) -> str:
        return f"response matches /{self.pattern}/"

    def check(self, ev: Evidence) -> AssertionResult:
        text = ev.output if isinstance(ev.output, str) else str(ev.output)
        return self.result("pass" if re.search(self.pattern, text, re.IGNORECASE) else "fail", text[:200])


type Assertion = Annotated[Sql | ToolOrder | ForbiddenTool | EventPresent | OutputMatches, Field(discriminator="type")]


class Budget(BaseModel):
    max_tool_calls: int | None = None
    max_latency_ms: int | None = None
    max_cost_usd: float | None = None


def _limit(name: str, actual: float | None, cap: float | None) -> AssertionResult | None:
    if cap is None:
        return None
    description = f"{name} <= {cap:g}"
    if actual is None:
        return AssertionResult(
            type="budget",
            description=description,
            critical=False,
            status="unsupported",
            detail="not reported by adapter",
        )
    return AssertionResult(
        type="budget",
        description=description,
        critical=False,
        status="pass" if actual <= cap else "fail",
        detail=f"actual {actual:g}",
    )


def check_budget(budget: Budget, ev: Evidence) -> list[AssertionResult]:
    checks = [
        _limit("tool_calls", len(ev.ledger), budget.max_tool_calls),
        _limit("latency_ms", ev.latency_ms, budget.max_latency_ms),
        _limit("cost_usd", ev.usage.cost_usd, budget.max_cost_usd),
    ]
    return [c for c in checks if c]


def _safe_check(a: _Check, ev: Evidence, *, faults_active: bool) -> AssertionResult:
    if a.requires_faults and not faults_active:
        return a.result("skipped", "scenario faults are disabled in this run")
    try:
        return a.check(ev)
    except Exception as exc:  # noqa: BLE001 - a broken grader is a grader defect, never an agent result
        return a.result("unsupported", f"grader error: {exc}")


def grade(assertions: list[Assertion], budget: Budget, ev: Evidence, *, faults_active: bool) -> list[AssertionResult]:
    return [_safe_check(a, ev, faults_active=faults_active) for a in assertions] + check_budget(budget, ev)
