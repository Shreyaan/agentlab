"""Scenario and target builders behind the console editors. Files on disk stay the source of truth: writes are
atomic (temp file + replace) and serialized, and saved scenario versions are immutable."""

import tempfile
import threading
import uuid
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from itertools import takewhile
from pathlib import Path
from typing import Literal, get_args
from urllib.parse import urlparse

import psycopg
import yaml
from fastapi import HTTPException
from pydantic import JsonValue, ValidationError

from agentlab.api_models import (
    BuilderInfo,
    EnvironmentDraft,
    QueryResult,
    QueryTest,
    SavedScenario,
    SavedTarget,
    ScenarioDraft,
    ScenarioValidation,
    TargetDraft,
)
from agentlab.assertions import Assertion, Decision, EventPresent, ForbiddenTool, RetiredCheck, Sql, ToolOrder
from agentlab.client import TargetsFile, TargetSpec
from agentlab.environment import EnvironmentSpec
from agentlab.fixture import Fixture, FixturePool, json_safe
from agentlab.judges import JUDGE_MODELS
from agentlab.records import Row
from agentlab.redaction import redact
from agentlab.scenario import Scenario, retired

_WRITE_LOCK = threading.Lock()
type Change = Literal["new", "same", "bump"]


def validation_errors(exc: ValidationError) -> list[str]:
    """`loc: message` per error, never the offending input (it may hold credentials)."""
    return [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors(include_input=False, include_url=False)]


def builder_info(spec: EnvironmentSpec) -> BuilderInfo:
    union = get_args(get_args(Assertion.__value__)[0])
    return BuilderInfo(
        tools=[t.name for t in spec.tools],
        seed_columns={t.name: [c.name for c in t.columns] for t in spec.tables},
        assertion_types=[str(cls.model_fields["type"].default) for cls in union if cls is not RetiredCheck],
        judge_models=JUDGE_MODELS,
    )


def atomic_write(path: Path, text: str) -> None:
    with tempfile.NamedTemporaryFile("w", dir=path.parent, suffix=".tmp", delete=False) as f:
        f.write(text)
    Path(f.name).replace(path)


def _error_message(exc: Exception) -> str:
    message = exc.diag.message_primary if isinstance(exc, psycopg.Error) and exc.diag.message_primary else str(exc)
    return str(redact(message))


def _tool_refs(a: Assertion) -> list[tuple[str, str]]:
    match a:
        case ToolOrder():
            return [("before", a.before), ("requires", a.requires)]
        case ForbiddenTool():
            return [("name", a.name)]
        case EventPresent() if a.name and a.event.startswith("tool_"):
            return [("name", a.name)]
        case _:
            return []


def _sql_refs(a: Assertion) -> list[tuple[str, str]]:
    match a:
        case Sql():
            return [("query", a.query)]
        case Decision() if a.calibration:
            return [("calibration.truth_sql", a.calibration.truth_sql)]
        case _:
            return []


def _name_errors(s: Scenario, spec: EnvironmentSpec) -> list[str]:
    tools = {t.name for t in spec.tools}
    errors = retired(s) + [
        f"faults.{i}.tool: unknown tool {f.tool!r}" for i, f in enumerate(s.faults) if f.tool not in tools
    ]
    for i, a in enumerate(s.assertions):
        errors += [f"assertions.{i}.{f}: unknown tool {n!r}" for f, n in _tool_refs(a) if n not in tools]
    return errors


@contextmanager
def temp_environment(pool: FixturePool, spec: EnvironmentSpec, seed: Mapping[str, list[Row]]) -> Generator[Fixture]:
    env_id = f"bld_{uuid.uuid4().hex[:16]}"
    try:
        yield pool.create(env_id, spec, seed)
    finally:
        pool.drop(env_id)


def _query_errors(pool: FixturePool, s: Scenario, spec: EnvironmentSpec) -> list[str]:
    errors: list[str] = []
    try:
        with temp_environment(pool, spec, s.seed) as fx:
            for i, a in enumerate(s.assertions):
                for field, query in _sql_refs(a):
                    try:
                        fx.query(query)
                    except psycopg.Error as exc:
                        errors.append(f"assertions.{i}.{field}: {_error_message(exc)}")
    except (psycopg.Error, ValueError) as exc:
        errors.append(f"seed: {_error_message(exc)}")
    return errors


def semantic_errors(pool: FixturePool, s: Scenario, environments: Mapping[str, EnvironmentSpec]) -> list[str]:
    if not (spec := environments.get(s.environment)):
        return [f"environment: unknown environment {s.environment!r}"]
    if errors := _name_errors(s, spec):
        return errors
    return _query_errors(pool, s, spec)


def environment_errors(pool: FixturePool, spec: EnvironmentSpec) -> list[str]:
    """Create the environment for real and dry-run every tool's SQL against it."""
    try:
        with temp_environment(pool, spec, {}) as fx:
            return fx.tool_errors()
    except (psycopg.Error, ValueError) as exc:
        return [f"tables: {_error_message(exc)}"]


class Library[T: (Scenario, EnvironmentSpec)]:
    """A directory of versioned YAML files (scenarios or environments). Files stay the source of truth and a saved
    version is immutable: a changed draft of an existing id is written as the next version."""

    def __init__(self, directory: str, model: type[T]) -> None:
        self.dir, self.model = Path(directory), model

    def to_yaml(self, item: T) -> str:
        # exclude_unset, not exclude_defaults: the latter would drop every assertion's `type` discriminator
        return yaml.safe_dump(item.model_dump(mode="json", exclude_unset=True), sort_keys=False)

    def _content(self, item: T) -> dict[str, JsonValue]:
        return item.model_dump(mode="json", exclude={"version"})

    def _existing(self, item_id: str) -> tuple[T, Path] | None:
        found: list[tuple[T, Path]] = []
        for f in sorted(self.dir.glob("*.y*ml")) if self.dir.is_dir() else []:
            try:
                item = self.model.model_validate(yaml.safe_load(f.read_text()))
            except (OSError, ValueError, yaml.YAMLError):
                continue
            if item.id == item_id:
                found.append((item, f.resolve()))
        return max(found, key=lambda x: x[0].version) if found else None

    def plan(self, draft: T) -> tuple[T, Path, Change]:
        """The item as it would be saved and where; a changed existing id gets the next version."""
        item_id = draft.id
        if existing := self._existing(item_id):
            old, path = existing
            if self._content(old) == self._content(draft):
                return old, path, "same"
            return draft.model_copy(update={"version": old.version + 1}), path, "bump"
        return draft, (self.dir / f"{item_id}.yaml").resolve(), "new"

    def save(self, draft: T) -> tuple[T, Path, Change]:
        if not self.dir.is_dir():
            raise HTTPException(409, f"{self.dir} is not a directory; saving needs one")
        with _WRITE_LOCK:
            item, path, change = self.plan(draft)
            if not path.is_relative_to(self.dir.resolve()):
                raise HTTPException(422, "path escapes the directory")
            if change != "same":
                atomic_write(path, self.to_yaml(item))
        return item, path, change


class ScenarioBuilder:
    def __init__(self, suite_path: str, pool: FixturePool, environments: Mapping[str, EnvironmentSpec]) -> None:
        self.library, self.pool, self.environments = Library(suite_path, Scenario), pool, environments

    def validate(self, raw: JsonValue) -> ScenarioValidation:
        try:
            draft = ScenarioDraft.model_validate(raw)
        except ValidationError as exc:
            return ScenarioValidation(valid=False, errors=validation_errors(exc))
        if errors := semantic_errors(self.pool, draft.scenario, self.environments):
            return ScenarioValidation(valid=False, errors=errors)
        scenario, _, _ = self.library.plan(draft.scenario)
        return ScenarioValidation(valid=True, yaml=self.library.to_yaml(scenario), key=scenario.key)

    def save(self, draft: ScenarioDraft) -> SavedScenario:
        if errors := semantic_errors(self.pool, draft.scenario, self.environments):
            raise HTTPException(422, "; ".join(errors))
        scenario, path, change = self.library.save(draft.scenario)
        return SavedScenario(key=scenario.key, path=str(path), created=change == "new")

    def test_query(self, body: QueryTest) -> QueryResult:
        if not (spec := self.environments.get(body.environment)):
            return QueryResult(ok=False, error=f"unknown environment {body.environment!r}")
        try:
            with temp_environment(self.pool, spec, body.seed) as fx:
                rows = json_safe([list(r) for r in fx.query(body.query)])
        except (psycopg.Error, ValueError) as exc:
            return QueryResult(ok=False, error=_error_message(exc))
        assert isinstance(rows, list)
        value = rows[0][0] if len(rows) == 1 and isinstance(rows[0], list) and len(rows[0]) == 1 else None
        return QueryResult(ok=True, rows=[r for r in rows if isinstance(r, list)], value=value)


class EnvironmentBuilder:
    def __init__(self, directory: str, pool: FixturePool) -> None:
        self.library, self.pool = Library(directory, EnvironmentSpec), pool

    def validate(self, raw: JsonValue) -> ScenarioValidation:
        try:
            draft = EnvironmentDraft.model_validate(raw)
        except ValidationError as exc:
            return ScenarioValidation(valid=False, errors=validation_errors(exc))
        if errors := environment_errors(self.pool, draft.environment):
            return ScenarioValidation(valid=False, errors=errors)
        spec, _, _ = self.library.plan(draft.environment)
        return ScenarioValidation(valid=True, yaml=self.library.to_yaml(spec), key=spec.key)

    def save(self, draft: EnvironmentDraft) -> SavedScenario:
        if errors := environment_errors(self.pool, draft.environment):
            raise HTTPException(422, "; ".join(errors))
        spec, path, change = self.library.save(draft.environment)
        return SavedScenario(key=spec.key, path=str(path), created=change == "new")


class TargetEditor:
    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def _load(self) -> dict[str, JsonValue]:
        try:
            data = yaml.safe_load(self.path.read_text())
            TargetsFile.model_validate(data)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            raise HTTPException(503, f"cannot load {self.path}: {type(exc).__name__}") from exc
        return data

    def _save(self, data: dict[str, JsonValue]) -> None:
        # yaml.safe_dump drops comments; keep the file's leading comment block (its usage/safety notes).
        lines = self.path.read_text().splitlines(keepends=True)
        header = "".join(takewhile(lambda line: line.startswith("#"), lines))
        atomic_write(self.path, header + yaml.safe_dump(data, sort_keys=False))

    def put(self, draft: TargetDraft) -> SavedTarget:
        with _WRITE_LOCK:
            data = self._load()
            allowed = TargetsFile.model_validate(data).allowed_hosts
            host = _host(draft.spec)
            if draft.spec.mode != "otel" and host not in allowed:
                raise HTTPException(422, f"host {host!r} is not in allowed_hosts")
            targets = data["targets"]
            assert isinstance(targets, dict)
            created = draft.name not in targets
            targets[draft.name] = draft.spec.model_dump(mode="json", exclude_defaults=True)
            self._save(data)
        return SavedTarget(name=draft.name, created=created)

    def delete(self, name: str) -> None:
        with _WRITE_LOCK:
            data = self._load()
            targets = data["targets"]
            assert isinstance(targets, dict)
            if name not in targets:
                raise HTTPException(404, f"unknown target {name!r}")
            del targets[name]
            self._save(data)


def _host(spec: TargetSpec) -> str | None:
    return urlparse(spec.url or "").hostname
