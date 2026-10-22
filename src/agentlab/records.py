"""Evidence records shared by the fixture and the graders."""

from typing import Literal

from pydantic import BaseModel, JsonValue

from agentlab.protocol import JsonObject

type Row = dict[str, JsonValue]
type State = dict[str, list[Row]]


class LedgerEntry(BaseModel):
    """One tool call as the environment saw it.

    `committed` means its side effect persisted, even if the caller saw an error.
    """

    seq: int
    tool: str
    request: JsonObject
    status: int
    response: JsonValue
    committed: bool
    ts: float


class TableDiff(BaseModel):
    added: list[Row] = []
    removed: list[Row] = []


class AssertionResult(BaseModel):
    type: str
    description: str
    critical: bool
    status: Literal["pass", "fail", "unsupported", "skipped"]  # skipped: not applicable to this run
    detail: str = ""


def state_diff(before: State, after: State) -> dict[str, TableDiff]:
    diff: dict[str, TableDiff] = {}
    for table, rows in after.items():
        old = before.get(table, [])
        added, removed = [r for r in rows if r not in old], [r for r in old if r not in rows]
        if added or removed:
            diff[table] = TableDiff(added=added, removed=removed)
    return diff
