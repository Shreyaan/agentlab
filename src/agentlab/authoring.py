"""Plain-English scenario authoring: a model drafts an environment + scenario, the engine's validators check it,
and validation errors are fed back to the model until the draft is valid or attempts run out. Nothing is saved."""

import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from agentlab.api_models import AuthorDraft, AuthorRequest
from agentlab.environment import EnvironmentSpec
from agentlab.scenario import Scenario

CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
API_KEY_ENV = "OPENROUTER_API_KEY"
MODEL_ENV = "AGENTLAB_AUTHOR_MODEL"
DEFAULT_MODEL = "anthropic/claude-sonnet-5.5"
TIMEOUT_S = 120
ROOT = Path(__file__).parent.parent.parent
PROMPT = Path(__file__).parent / "prompts" / "author.md"
EXAMPLE_ENVIRONMENT = ROOT / "environments" / "travel.yaml"
EXAMPLE_SCENARIO = ROOT / "scenarios" / "travel_payment_timeout.yaml"

type Message = dict[str, str]
type EnvironmentValidator = Callable[[EnvironmentSpec], list[str]]
type ScenarioValidator = Callable[[Scenario, EnvironmentSpec], list[str]]


class AuthorError(Exception):
    """Model or network failure; draft() turns it into an invalid draft."""


@dataclass(frozen=True)
class Completion:
    text: str
    cost_usd: float | None


type Complete = Callable[[str, list[Message]], Completion]  # (model, messages) -> reply


def _compact(schema: dict[str, Any]) -> str:
    return json.dumps(schema, separators=(",", ":"))


def build_system_prompt(example_environment: str, example_scenario: str, environment: EnvironmentSpec | None) -> str:
    """The prompt teaches the spec from the live pydantic schemas plus one full example."""
    mode = (
        'Use EXACTLY this existing environment and draft only the scenario. Output `"environment": null` and set '
        f'the scenario\'s `environment` to "{environment.key}".\n\n```json\n{environment.model_dump_json()}\n```'
        if environment
        else "Draft a NEW environment suited to the description, and the scenario that runs in it. "
        "The scenario's `environment` must equal the new environment's `id@version`."
    )
    values = {
        "MODE": mode,
        "ENVIRONMENT_SCHEMA": _compact(EnvironmentSpec.model_json_schema()),
        "SCENARIO_SCHEMA": _compact(Scenario.model_json_schema()),
        "EXAMPLE_ENVIRONMENT": example_environment.strip(),
        "EXAMPLE_SCENARIO": example_scenario.strip(),
    }
    prompt = PROMPT.read_text()
    for name, value in values.items():
        prompt = prompt.replace("{{" + name + "}}", value)
    return prompt


def extract_json(text: str) -> dict[str, Any]:
    """The JSON object in a model reply, tolerating code fences or prose around it."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("reply contains no JSON object")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"reply is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("reply JSON must be an object")
    return data


@dataclass(frozen=True)
class Candidate:
    environment: EnvironmentSpec | None  # the new environment the model drafted, if any
    scenario: Scenario
    notes: list[str]


def _pydantic_errors(prefix: str, exc: ValidationError) -> list[str]:
    return [f"{prefix}.{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]


def parse_candidate(text: str, existing: EnvironmentSpec | None) -> Candidate:
    """Reply text -> Candidate. Raises ValueError carrying every problem as a line."""
    data = extract_json(text)
    problems: list[str] = []
    environment: EnvironmentSpec | None = None
    if existing is None:
        try:
            environment = EnvironmentSpec.model_validate(data.get("environment"))
        except ValidationError as exc:
            problems += _pydantic_errors("environment", exc)
    scenario: Scenario | None = None
    try:
        scenario = Scenario.model_validate(data.get("scenario"))
    except ValidationError as exc:
        problems += _pydantic_errors("scenario", exc)
    raw_notes = data.get("notes")
    notes = [str(n) for n in raw_notes] if isinstance(raw_notes, list) else []
    if problems or scenario is None:
        raise ValueError("\n".join(problems))
    return Candidate(environment, scenario, notes)


def semantic_errors(
    candidate: Candidate,
    existing: EnvironmentSpec | None,
    validate_environment: EnvironmentValidator,
    validate_scenario: ScenarioValidator,
) -> list[str]:
    environment = existing or candidate.environment
    if environment is None:
        return ["environment: missing"]
    if candidate.environment and (errors := validate_environment(candidate.environment)):
        return [f"environment: {e}" for e in errors]
    return [f"scenario: {e}" for e in validate_scenario(candidate.scenario, environment)]


def openrouter_complete(model: str, messages: list[Message]) -> Completion:
    if not (key := os.environ.get(API_KEY_ENV)):
        raise AuthorError(f"{API_KEY_ENV} is not set")
    body = {"model": model, "messages": messages, "response_format": {"type": "json_object"}}
    try:
        r = httpx.post(CHAT_URL, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=TIMEOUT_S)
        r.raise_for_status()
        data = r.json()
        text = data["choices"][0]["message"]["content"]
    except httpx.HTTPStatusError as exc:
        raise AuthorError(f"author model HTTP {exc.response.status_code}: {exc.response.text[:200]}") from exc
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        raise AuthorError(f"author model call failed: {type(exc).__name__}") from exc
    if not isinstance(text, str):
        raise AuthorError("author model returned no text")
    cost = (data.get("usage") or {}).get("cost")
    return Completion(text, float(cost) if isinstance(cost, int | float) else None)


class Author:
    def __init__(
        self, model: str | None = None, max_attempts: int = 3, complete: Complete = openrouter_complete
    ) -> None:
        self.model = model or os.environ.get(MODEL_ENV) or DEFAULT_MODEL
        self.max_attempts = max_attempts
        self._complete = complete

    def draft(
        self,
        request: AuthorRequest,
        environments: dict[str, EnvironmentSpec],
        validate_environment: EnvironmentValidator,
        validate_scenario: ScenarioValidator,
    ) -> AuthorDraft:
        """Never raises: model, network and spec problems come back as `valid=False` with `errors`.

        When no scenario ever parsed, `scenario` is None (AuthorDraft.scenario is not optional in the contract,
        so such a draft is built unvalidated; the router turns it into an HTTP error)."""
        existing = environments.get(request.environment) if request.environment else None
        if request.environment and existing is None:
            return self._failed(0, None, [f"unknown environment {request.environment!r}"])
        try:
            system = build_system_prompt(EXAMPLE_ENVIRONMENT.read_text(), EXAMPLE_SCENARIO.read_text(), existing)
        except OSError as exc:
            return self._failed(0, None, [f"authoring prompt unavailable: {exc}"])
        messages: list[Message] = [
            {"role": "system", "content": system},
            {"role": "user", "content": request.description},
        ]
        cost: float | None = None
        candidate: Candidate | None = None
        errors: list[str] = []
        attempts = 0
        while attempts < self.max_attempts:
            attempts += 1
            try:
                reply = self._complete(self.model, messages)
            except AuthorError as exc:
                return self._failed(attempts, cost, [str(exc)], candidate)
            if reply.cost_usd is not None:
                cost = (cost or 0.0) + reply.cost_usd
            try:
                candidate = parse_candidate(reply.text, existing)
                errors = semantic_errors(candidate, existing, validate_environment, validate_scenario)
            except ValueError as exc:
                errors = str(exc).splitlines() or ["unparseable reply"]
            if not errors and candidate:
                return AuthorDraft(
                    environment=candidate.environment,
                    scenario=candidate.scenario,
                    valid=True,
                    notes=candidate.notes,
                    model=self.model,
                    attempts=attempts,
                    cost_usd=cost,
                )
            messages += [
                {"role": "assistant", "content": reply.text},
                {
                    "role": "user",
                    "content": "Validation failed:\n- "
                    + "\n- ".join(errors)
                    + "\nReturn the corrected FULL JSON object.",
                },
            ]
        return self._failed(attempts, cost, errors, candidate)

    def _failed(
        self, attempts: int, cost: float | None, errors: list[str], candidate: Candidate | None = None
    ) -> AuthorDraft:
        return AuthorDraft(
            environment=candidate.environment if candidate else None,
            scenario=candidate.scenario if candidate else None,
            valid=False,
            errors=errors,
            notes=candidate.notes if candidate else [],
            model=self.model,
            attempts=attempts,
            cost_usd=cost,
        )


def authoring_router(
    author_factory: Callable[[], Author],
    environments: Callable[[], dict[str, EnvironmentSpec]],
    validate_environment: EnvironmentValidator,
    validate_scenario: ScenarioValidator,
    dependencies: Sequence[Any] = (),
) -> APIRouter:
    """POST /v1/author. `dependencies` are FastAPI dependency callables (token, CSRF) applied to the route."""
    router = APIRouter(dependencies=[Depends(d) for d in dependencies])

    @router.post("/v1/author")
    def author(request: AuthorRequest) -> AuthorDraft:  # sync: the model call blocks, FastAPI runs it in a thread
        envs = environments()
        if request.environment and request.environment not in envs:
            raise HTTPException(404, f"unknown environment {request.environment!r}")
        return author_factory().draft(request, envs, validate_environment, validate_scenario)

    return router
