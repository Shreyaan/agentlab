"""Generate docs/reference/*.md from the code so the reference can never drift.

uv run python scripts/gen_reference.py           # rewrite the pages
uv run python scripts/gen_reference.py --check   # exit 1 if any page is stale (CI)
"""

import argparse
import contextlib
import inspect
import json
import os
import re
import sys
import types
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Annotated, Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from agentlab import cli, console, protocol
from agentlab.assertions import Budget, Decision, EventPresent, ForbiddenTool, RetiredCheck, Sql, ToolOrder
from agentlab.authoring import API_KEY_ENV, MODEL_ENV
from agentlab.db import DATABASE_URL_ENV
from agentlab.environment import Column, EnvironmentSpec, Rule, Table, ToolParam, ToolSpec
from agentlab.judges import ChoiceQuestion, JudgeSpec, NoulQuestion, ScoreQuestion
from agentlab.records import Canary
from agentlab.scenario import Scenario, ScenarioFault
from agentlab.verdicts import ChoiceRule, NoulRule, ScoreRule

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "docs" / "reference"
HELP_COLUMNS = "100"
INLINE_COMMENT = re.compile(r"^\s{4}(\w+)\s*:[^#\"']*#\s*(.+?)\s*$")
HTTP_METHODS = ("get", "post", "put", "delete")

# (path template, status code, meaning) rows are derived from console.py / fixture.py; keep in sync via review.
CONSOLE_ERRORS = [
    (400, "Request could not be processed (e.g. invalid authoring input)."),
    (401, "Missing or invalid bearer token (only when a token is configured)."),
    (403, "Missing `X-AgentLab-Request: 1` header on a write."),
    (404, "Unknown experiment, trial or environment."),
    (409, "Capability unsupported by the target (fork)."),
    (422, "Validation failed: bad body, unknown target/scenario, or a name that does not match the path."),
    (502, "Upstream adapter or model failure."),
    (503, "A config file (targets, scenarios, environments) could not be loaded."),
]
ENV_ERRORS = [
    (404, "Unknown environment, or unknown tool name."),
    (409, "Idempotency key already used by another tool."),
    (422, "Arguments failed validation against the tool's parameters."),
    (500, "Database error while running the tool."),
    (503, "Environment unavailable (a harness-injected fault, or the database is down)."),
    (504, "Upstream timeout (an injected `timeout_after_commit` fault: the effect may have happened)."),
]


def admonition(source: str) -> str:
    return f"!!! note\n    Auto-generated from {source}; do not edit. Run `uv run python scripts/gen_reference.py`.\n"


def escape_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def code_cell(text: str) -> str:
    return f"`{escape_cell(text)}`" if text else ""


# --- type rendering -------------------------------------------------------------------------------------------


def fmt_type(tp: Any) -> str:  # noqa: ANN401 - annotations are arbitrary typing objects
    if tp is type(None):
        return "null"
    if str(tp).endswith("JsonValue"):
        return "JSON"
    if hasattr(tp, "__value__"):  # `type X = ...` alias
        return fmt_type(tp.__value__)
    origin, args = get_origin(tp), get_args(tp)
    if origin is None:
        return getattr(tp, "__name__", str(tp))
    return fmt_generic(origin, args)


def fmt_generic(origin: Any, args: tuple[Any, ...]) -> str:  # noqa: ANN401
    if origin is Annotated:
        return fmt_type(args[0])
    if origin is Literal:
        return " | ".join(json.dumps(a) for a in args)
    if origin in (Union, types.UnionType):
        return " | ".join(fmt_type(a) for a in args)
    return f"{origin.__name__}[{', '.join(fmt_type(a) for a in args)}]"


def fmt_default(field: FieldInfo) -> str:
    if field.is_required():
        return ""
    value = field.get_default(call_default_factory=True)
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    elif isinstance(value, list):
        value = [v.model_dump(mode="json") if isinstance(v, BaseModel) else v for v in value]
    return json.dumps(value)


def inline_comments(model: type[BaseModel]) -> dict[str, str]:
    """`field: type = x  # comment` comments, from the model and its bases (nearest class wins)."""
    found: dict[str, str] = {}
    for cls in reversed(model.__mro__):
        if not (isinstance(cls, type) and issubclass(cls, BaseModel)) or cls is BaseModel:
            continue
        for line in inspect.getsource(cls).splitlines():
            if m := INLINE_COMMENT.match(line):
                found[m[1]] = m[2]
    return found


# --- model sections -------------------------------------------------------------------------------------------


def constraints(field: FieldInfo) -> str:
    symbols = {"ge": ">=", "le": "<=", "gt": ">", "lt": "<", "min_length": "min length", "max_length": "max length"}
    found = [f"{label} {getattr(m, key)}" for m in field.metadata for key, label in symbols.items() if hasattr(m, key)]
    return f"({', '.join(found)})" if found else ""


def field_description(name: str, field: FieldInfo, comments: dict[str, str]) -> str:
    return " ".join(p for p in (field.description or comments.get(name, ""), constraints(field)) if p)


def model_section(model: type[BaseModel], heading: str = "###", note: str = "") -> str:
    comments = inline_comments(model)
    rows = ["| Field | Type | Required | Default | Description |", "|---|---|---|---|---|"]
    for name, field in model.model_fields.items():
        rows.append(
            f"| `{name}` | {code_cell(fmt_type(field.annotation))} | {'yes' if field.is_required() else 'no'} "
            f"| {code_cell(fmt_default(field))} | {escape_cell(field_description(name, field, comments))} |"
        )
    doc = inspect.cleandoc(model.__doc__) if model.__doc__ and model.__doc__ != BaseModel.__doc__ else ""
    parts = [f"{heading} {model.__name__}"]
    if note:
        parts.append(note)
    if doc:
        parts.append(doc)
    parts.append("\n".join(rows))
    return "\n\n".join(parts)


def sections(models: list[type[BaseModel]], heading: str = "###") -> str:
    return "\n\n".join(model_section(m, heading) for m in models)


def collapsible(title: str, schema: object) -> str:
    body = json.dumps(schema, indent=2, sort_keys=True)
    indented = "\n".join(f"    {line}" for line in body.splitlines())
    return f'??? abstract "{title}"\n\n    ```json\n{indented}\n    ```\n'


def yaml_example(title: str, path: Path) -> str:
    rel = path.relative_to(ROOT)
    return f'## Example: `{rel}`\n\n```yaml title="{rel}"\n{path.read_text().rstrip()}\n```\n'


def page(title: str, source: str, *blocks: str) -> str:
    return "\n\n".join([f"# {title}", admonition(source), *blocks]).rstrip() + "\n"


# --- pages ----------------------------------------------------------------------------------------------------


@contextlib.contextmanager
def neutral_cli_env() -> Iterator[None]:
    """argparse help embeds env-derived defaults, terminal width and argv[0]; pin them for reproducible output."""
    saved_env, saved_argv = dict(os.environ), sys.argv[:]
    for key in [k for k in os.environ if k.startswith("AGENTLAB_")]:
        del os.environ[key]
    os.environ["COLUMNS"] = HELP_COLUMNS
    sys.argv[0] = "agentlab"
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved_env)
        sys.argv[:] = saved_argv


def cli_page() -> str:
    with neutral_cli_env():
        parser = cli.build_parser()
        subparsers = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
        top = parser.format_help()
        subs = {name: sub.format_help() for name, sub in subparsers.choices.items()}
    commands = "\n\n".join(f"## `agentlab {name}`\n\n```text\n{text.rstrip()}\n```" for name, text in subs.items())
    env_vars = "\n".join(
        [
            "| Variable | Used by |",
            "|---|---|",
            f"| `{DATABASE_URL_ENV}` | Postgres URL; default of `--database-url` |",
            f"| `{API_KEY_ENV}` | API key for LLM judges and the authoring assistant |",
            f"| `{MODEL_ENV}` | Model for the authoring assistant |",
            "| `AGENTLAB_CONCURRENCY` | Default of `--concurrency` |",
            "| `AGENTLAB_FIXTURE_PORT` | Default of `--fixture-port` |",
            "| `AGENTLAB_FIXTURE_BIND` | Default of `--fixture-bind` |",
            "| `AGENTLAB_FIXTURE_URL` | Default of `--fixture-url` |",
            "| `AGENTLAB_CONSOLE_TOKEN` | Default of `serve --token` (bearer token for `/v1`) |",
            "| `AGENTLAB_CONSOLE_HOSTS` | Comma-separated default of `serve --allow-host` |",
            "| `AGENTLAB_ALLOW_NO_TOKEN` | `1` makes `serve --allow-no-token` the default |",
        ]
    )
    exits = "\n".join(
        [
            "| Code | Meaning |",
            "|---|---|",
            *(f"| {code} | {name} (gate decision) |" for name, code in sorted(cli.EXIT.items(), key=lambda kv: kv[1])),
            f"| {cli.USAGE_ERROR} | Usage, configuration or infrastructure error |",
        ]
    )
    return page(
        "CLI reference",
        "`agentlab.cli.build_parser()`",
        f"```text\n{top.rstrip()}\n```",
        f"## Environment variables\n\n{env_vars}",
        f"## Exit codes\n\n{exits}\n\n`conformance` exits 1 when a target fails the protocol checks.",
        commands,
    )


def environment_page() -> str:
    models: list[type[BaseModel]] = [EnvironmentSpec, Table, Column, ToolSpec, ToolParam, Rule]
    return page(
        "Environment spec",
        "`agentlab.environment` (pydantic models)",
        "An environment is a YAML file in `environments/`: tables plus SQL-backed tools. "
        "Identifiers match `[a-z][a-z0-9_]{0,47}`; the environment `id` matches `[a-z0-9][a-z0-9._-]{0,63}`.",
        "## Models",
        sections(models),
        "## JSON Schema",
        collapsible("EnvironmentSpec JSON Schema", EnvironmentSpec.model_json_schema()),
        yaml_example("pharmacy", ROOT / "environments" / "pharmacy.yaml"),
    )


def scenario_page() -> str:
    top: list[type[BaseModel]] = [Scenario, ScenarioFault, Budget]
    assertions: list[type[BaseModel]] = [Sql, ToolOrder, ForbiddenTool, EventPresent, Decision]
    decision_parts: list[type[BaseModel]] = [
        NoulQuestion,
        ChoiceQuestion,
        ScoreQuestion,
        NoulRule,
        ChoiceRule,
        ScoreRule,
        JudgeSpec,
        Canary,
    ]
    calibration = next(f for n, f in Decision.model_fields.items() if n == "calibration")
    calibration_model = next(a for a in get_args(calibration.annotation) if isinstance(a, type))
    retired = model_section(
        RetiredCheck,
        "###",
        "**Retired.** Still parses so stored experiments stay readable, but is never evaluated (always `skipped`); "
        "new scenarios may not use it.",
    )
    return page(
        "Scenario spec",
        "`agentlab.scenario` and `agentlab.assertions` (pydantic models)",
        "A scenario is a YAML file in `scenarios/`. Every assertion carries a `type` discriminator.",
        "## Scenario",
        sections(top),
        "## Assertion types",
        f"{sections(assertions)}\n\n{retired}",
        "## Decision building blocks",
        f"{sections(decision_parts)}\n\n{model_section(calibration_model)}",
        "## JSON Schema",
        collapsible("Scenario JSON Schema", Scenario.model_json_schema()),
        yaml_example("refill timeout", ROOT / "scenarios" / "pharmacy.refill_timeout.yaml"),
    )


def ref_name(schema: dict[str, Any] | None) -> str:
    if not schema:
        return ""
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    if schema.get("type") == "array":
        return f"list[{ref_name(schema['items'])}]"
    return schema.get("type", "")


def json_schema_of(operation: dict[str, Any], status: str | None = None) -> dict[str, Any] | None:
    if status is None:
        content = operation.get("requestBody", {}).get("content", {})
    else:
        content = operation["responses"].get(status, {}).get("content", {})
    return content.get("application/json", {}).get("schema")


def endpoint_rows(schema: dict[str, Any]) -> list[str]:
    rows = ["| Method | Path | Summary | Request body | Response | Success |", "|---|---|---|---|---|---|"]
    for path, ops in sorted(schema["paths"].items()):
        for method in HTTP_METHODS:
            if not (op := ops.get(method)):
                continue
            success = next(s for s in op["responses"] if s.startswith("2"))
            rows.append(
                f"| {method.upper()} | `{path}` | {escape_cell(op.get('summary', ''))} "
                f"| {code_cell(ref_name(json_schema_of(op)))} | {code_cell(ref_name(json_schema_of(op, success)))} "
                f"| {success} |"
            )
    return rows


def status_table(errors: list[tuple[int, str]]) -> str:
    return "\n".join(["| Status | Meaning |", "|---|---|", *(f"| {c} | {m} |" for c, m in errors)])


def api_page() -> str:
    schema = console.openapi_schema()
    return page(
        "HTTP API",
        "`agentlab.console.openapi_schema()`, `agentlab.fixture` and `agentlab.mcp_env`",
        "## Console API\n\nServed by `agentlab serve` under `/v1`. Request and response model names refer to "
        "`components.schemas` in the OpenAPI document (`agentlab openapi`).\n\n"
        "**Auth.** When a token is configured (`serve --token` / `AGENTLAB_CONSOLE_TOKEN`) every `/v1` route needs "
        "`Authorization: Bearer <token>`.\n\n"
        "**CSRF guard.** Every write (POST, PUT, DELETE) also needs the header `X-AgentLab-Request: 1`.\n\n"
        "**Hosts.** Requests whose `Host` header is not allow-listed are rejected (DNS-rebinding defence).",
        "\n".join(endpoint_rows(schema)),
        f"### Status codes\n\n{status_table(CONSOLE_ERRORS)}",
        "## Agent-facing environment routes\n\n"
        "Served by the fixture service (the runner's own port, or `agentlab fixture` standalone). Agents under test "
        "use these to act on their per-trial environment; `{env_id}` is the trial's environment id. "
        "No bearer token and no `X-AgentLab-Request` header are involved.\n\n"
        "| Method | Path | Description |\n|---|---|---|\n"
        "| GET | `/env/{env_id}/tools` | Tool catalog: `{environment, description, tools: [{name, description, "
        "parameters}]}` where `parameters` is a JSON Schema object. |\n"
        "| POST | `/env/{env_id}/tools/{name}` | Call a tool with a JSON object of arguments. The response body and "
        "status are the tool's own result. An `Idempotency-Key` header is folded into the `idempotency_key` "
        "argument for idempotent tools. |\n"
        "| POST | `/env/{env_id}/mcp` | The same tools over MCP (Streamable HTTP, stateless, JSON responses). "
        "`tools/list` returns the catalog; `tools/call` runs the same executor, so calls reach the ledger, faults "
        "and idempotency identically. Tool errors (status >= 400) are returned as MCP `isError` results. |\n\n"
        "Standalone mode (`agentlab fixture`) additionally serves `POST /env/{env_id}/admin/reset` and "
        "`GET /env/{env_id}/admin/state`; these are never exposed on the runner's server.",
        f"### Tool call status codes\n\nSuccess uses the tool's `success_status` (default 200); rule failures use the "
        f"rule's own 4xx.\n\n{status_table(ENV_ERRORS)}",
    )


def protocol_page() -> str:
    models: list[type[BaseModel]] = [
        protocol.Manifest,
        protocol.Capabilities,
        protocol.InvokeRequest,
        protocol.Environment,
        protocol.ToolFault,
        protocol.ResumeFrom,
        protocol.InvokeResponse,
        protocol.Event,
        protocol.Usage,
        protocol.ErrorBody,
    ]
    event_types = "\n".join(f"- `{t}`" for t in get_args(protocol.EventType.__value__))
    error_codes = "\n".join(f"- `{c.value}`" for c in protocol.ErrorCode)
    schemas = "\n\n".join(collapsible(f"{n} JSON Schema", s) for n, s in sorted(protocol.json_schemas().items()))
    return page(
        f"BYOH wire protocol v{protocol.PROTOCOL_VERSION}",
        "`agentlab.protocol` (pydantic models and `json_schemas()`)",
        "The language-neutral contract between the runner and any harness. Schemas are also written by "
        "`agentlab schema`.",
        "## Models",
        sections(models),
        f"## Event types\n\n{event_types}",
        f"## Error codes\n\nAn `ErrorBody` is returned with HTTP status 400.\n\n{error_codes}",
        "## Invariants\n\n"
        "- **Event ordering.** Events are ordered by `seq` (1-based, strictly increasing within a run). `ts` is "
        "informational and never used to order events across runtimes.\n"
        "- **One tool event per environment call.** Each call to the environment emits `tool_requested`, then "
        "exactly one of `tool_completed` or `tool_failed`. Fork/resume maps checkpoints to ledger positions by "
        "counting these terminal events.\n"
        "- **Injected failures.** A `tool_failed` event with `data.committed = false` marks a harness-injected failure "
        "that never reached the environment; it is not counted as an environment call. `data.injected = true` marks "
        "any harness-injected fault; `timeout_after_commit` faults report `committed = true`.\n"
        "- **Checkpoints.** `checkpoint_saved` carries `data.checkpoint_id`.\n"
        "- **Adapter failures are never agent results.** Infrastructure errors use `ErrorBody` codes.",
        "## JSON Schemas",
        schemas,
    )


PAGES: dict[str, Callable[[], str]] = {
    "cli.md": cli_page,
    "environment-spec.md": environment_page,
    "scenario-spec.md": scenario_page,
    "api.md": api_page,
    "protocol.md": protocol_page,
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    ap.add_argument("--check", action="store_true", help="exit 1 if any generated file is stale")
    check = ap.parse_args(argv).check
    stale = []
    for name, build in PAGES.items():
        path, content = OUT_DIR / name, build()
        if check:
            if not path.exists() or path.read_text() != content:
                stale.append(path.relative_to(ROOT))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    if stale:
        print(f"stale generated docs: {', '.join(map(str, stale))}. Run: uv run python scripts/gen_reference.py")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
