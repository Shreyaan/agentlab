"""Free-form environments: any tables and tools, declared as data and run against one Postgres schema per trial.

An environment is a versioned spec (YAML in `environments/`). Its tools are SQL statements with typed parameters,
optional precondition rules and optional idempotency. The runtime gives every tool the same guarantees regardless
of domain: isolation per trial, the side-effect ledger, fault injection, ledger-replay restore for forks, and
read-only author SQL. Agents discover tools at runtime (HTTP catalog or MCP), so no agent hard-codes a domain.
"""

import re
from pathlib import Path
from typing import Literal, cast

import yaml
from pydantic import BaseModel, Field, JsonValue, field_validator, model_validator

IDENTIFIER = re.compile(r"[a-z][a-z0-9_]{0,47}")
ENVIRONMENT_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
RESERVED_TABLES = {"ledger", "idempotency"}  # owned by the runtime, never by a spec

type ColumnType = Literal["text", "integer", "bigint", "numeric", "boolean", "timestamptz", "jsonb"]
type ParamType = Literal["string", "integer", "number", "boolean"]


def _identifier(value: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise ValueError("use lowercase letters, digits and '_', starting with a letter (max 48)")
    return value


class Column(BaseModel):
    name: str
    type: ColumnType
    primary_key: bool = False
    nullable: bool = True
    unique: bool = False
    serial: bool = False  # auto-increment integer key; deterministic, so ledger replay reproduces the same ids
    references: str | None = None  # "table.column"

    _name = field_validator("name")(_identifier)


class Table(BaseModel):
    name: str
    columns: list[Column] = Field(min_length=1)

    _name = field_validator("name")(_identifier)

    @field_validator("name")
    @classmethod
    def _not_reserved(cls, value: str) -> str:
        if value in RESERVED_TABLES:
            raise ValueError(f"{value!r} is reserved by the runtime")
        return value


class ToolParam(BaseModel):
    name: str
    type: ParamType
    description: str = ""
    required: bool = True
    enum: list[str] | None = None

    _name = field_validator("name")(_identifier)


class Rule(BaseModel):
    """A precondition evaluated before the effect. `sql` is one SELECT returning a single boolean cell, with the
    tool's parameters bound as %(name)s. When it returns true the call fails with `status` and `error` and has no
    side effect (e.g. "insufficient seats" -> 409)."""

    sql: str
    status: int = Field(ge=400, le=499)
    error: str


class ToolSpec(BaseModel):
    """One tool: typed parameters, optional rules, then ONE SQL statement (parameters bound as %(name)s; use
    RETURNING to send rows back). Runs as the trial's writer role: it can change this environment's tables only."""

    name: str
    description: str
    params: list[ToolParam] = []
    rules: list[Rule] = []
    sql: str
    returns: Literal["row", "rows", "none"] = "row"  # "row": first row or 404 when none; "rows": list; "none": {}
    success_status: int = Field(default=200, ge=200, le=299)
    idempotent: bool = False  # honour an `idempotency_key` argument: a repeated key replays the first response
    mutates: bool = True  # false for read-only tools (they still go to the ledger)

    _name = field_validator("name")(_identifier)


class EnvironmentSpec(BaseModel):
    id: str
    version: int = Field(ge=1)
    description: str  # also given to agents as context about the world they operate in
    tables: list[Table] = Field(min_length=1)
    tools: list[ToolSpec] = Field(min_length=1)

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        if not ENVIRONMENT_ID.fullmatch(value):
            raise ValueError("use 1-64 lowercase letters, digits, '.', '_' or '-', starting with a letter or digit")
        return value

    @model_validator(mode="after")
    def _unique_names(self) -> "EnvironmentSpec":
        for kind, names in (("table", [t.name for t in self.tables]), ("tool", [t.name for t in self.tools])):
            if dupes := sorted({n for n in names if names.count(n) > 1}):
                raise ValueError(f"duplicate {kind} name(s): {dupes}")
        return self

    @property
    def key(self) -> str:
        return f"{self.id}@{self.version}"


# --- Tool catalog: what agents see (HTTP `GET /env/{id}/tools` and MCP `tools/list` carry the same data). ---


class CatalogTool(BaseModel):
    name: str
    description: str
    parameters: dict[str, JsonValue]  # JSON Schema object; idempotent tools get an optional `idempotency_key`


class ToolCatalog(BaseModel):
    environment: str  # id@version
    description: str
    tools: list[CatalogTool]


def _param_schema(p: ToolParam) -> dict[str, JsonValue]:
    schema: dict[str, JsonValue] = {"type": p.type}
    if p.description:
        schema["description"] = p.description
    if p.enum:
        schema["enum"] = list(p.enum)
    return schema


def tool_schema(tool: ToolSpec) -> dict[str, JsonValue]:
    props = {p.name: _param_schema(p) for p in tool.params}
    if tool.idempotent:
        props.setdefault(
            "idempotency_key", {"type": "string", "description": "a repeated key replays the first result"}
        )
    required: list[JsonValue] = [p.name for p in tool.params if p.required]
    return {
        "type": "object",
        "properties": cast("JsonValue", props),
        "required": required,
        "additionalProperties": False,
    }


def catalog(spec: EnvironmentSpec) -> ToolCatalog:
    tools = [CatalogTool(name=t.name, description=t.description, parameters=tool_schema(t)) for t in spec.tools]
    return ToolCatalog(environment=spec.key, description=spec.description, tools=tools)


_PYTHON_TYPES: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
}


def bind_args(tool: ToolSpec, args: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Check agent-supplied arguments against the tool's declared parameters and return the SQL parameters (every
    declared name, None when an optional one is absent). Messages name parameters, never echo values."""
    allowed = {p.name for p in tool.params} | ({"idempotency_key"} if tool.idempotent else set())
    if unknown := sorted(set(args) - allowed):
        raise ValueError(f"unknown argument(s): {unknown}")
    if not isinstance(args.get("idempotency_key", ""), str):
        raise ValueError("argument 'idempotency_key' must be string")
    bound: dict[str, JsonValue] = {}
    for p in tool.params:
        value = bound[p.name] = args.get(p.name)
        if value is None:
            if p.required:
                raise ValueError(f"missing required argument {p.name!r}")
        elif isinstance(value, bool) != (p.type == "boolean") or not isinstance(value, _PYTHON_TYPES[p.type]):
            raise ValueError(f"argument {p.name!r} must be {p.type}")
        elif p.enum and str(value) not in p.enum:
            raise ValueError(f"argument {p.name!r} must be one of {p.enum}")
    return bound


def load_environments(path: str | Path) -> dict[str, EnvironmentSpec]:
    specs = [EnvironmentSpec.model_validate(yaml.safe_load(f.read_text())) for f in sorted(Path(path).glob("*.y*ml"))]
    keys = [s.key for s in specs]
    if len(keys) != len(set(keys)):
        raise ValueError(f"duplicate environment id@version in {path}")
    return {s.key: s for s in specs}
