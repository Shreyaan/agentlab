"""Authoring: prompt assembly, reply parsing and the repair loop run on real candidate JSON; the router on real HTTP."""
# ruff: noqa: PT018

import json
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentlab import authoring
from agentlab.api_models import AuthorRequest
from agentlab.authoring import (
    Author,
    AuthorError,
    Completion,
    EnvironmentValidator,
    ScenarioValidator,
    authoring_router,
    build_system_prompt,
    extract_json,
)
from agentlab.builder import environment_errors, semantic_errors
from agentlab.environment import EnvironmentSpec, load_environments
from agentlab.fixture import FixturePool
from agentlab.scenario import Scenario

REFUND = load_environments(authoring.ROOT / "environments")["refund@1"]
REQUEST = AuthorRequest(
    description="A support agent refunds an order; the payment API times out after committing.", environment="refund@1"
)


def scenario_json(**overrides: object) -> dict[str, object]:
    return {
        "id": "refund.authored",
        "version": 1,
        "environment": "refund@1",
        "seed": {
            "customers": [{"id": "C-1", "name": "Ada"}],
            "orders": [{"id": "O-1", "customer_id": "C-1", "amount_cents": 500}],
        },
        "input": {"message": "Refund order O-1"},
        "assertions": [{"type": "sql", "query": "SELECT COUNT(*) FROM refunds", "equals": 1, "critical": True}],
    } | overrides


def reply(scenario: dict[str, object], notes: list[str] | None = None) -> str:
    return json.dumps({"environment": None, "scenario": scenario, "notes": notes or ["assumed amount"]})


def no_errors_environment(_: EnvironmentSpec) -> list[str]:
    return []


def reject_unsafe_ids(scenario: Scenario, _: EnvironmentSpec) -> list[str]:
    return ["id must not contain 'bad'"] if "bad" in scenario.id else []


@pytest.fixture(autouse=True)
def example_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name, text in (("EXAMPLE_ENVIRONMENT", "id: example_env"), ("EXAMPLE_SCENARIO", "id: example_scenario")):
        path = tmp_path / name
        path.write_text(text)
        monkeypatch.setattr(authoring, name, path)


class Script:
    """Replies in order, recording the messages each call received."""

    def __init__(self, *texts: str) -> None:
        self.texts, self.calls = list(texts), []

    def __call__(self, model: str, messages: list[dict[str, str]]) -> Completion:
        self.calls.append([dict(m) for m in messages])
        return Completion(self.texts.pop(0), 0.01)


def draft(script: Script, attempts: int = 3):
    return Author(model="m", max_attempts=attempts, complete=script).draft(
        REQUEST, {"refund@1": REFUND}, no_errors_environment, reject_unsafe_ids
    )


# --- prompt assembly ---


def test_prompt_embeds_schemas_and_example_for_a_new_environment() -> None:
    prompt = build_system_prompt("ENV-EXAMPLE-TEXT", "SCENARIO-EXAMPLE-TEXT", None)
    assert "ENV-EXAMPLE-TEXT" in prompt and "SCENARIO-EXAMPLE-TEXT" in prompt
    assert '"timeout_after_commit"' in prompt  # from the Scenario schema (fault actions)
    assert '"idempotent"' in prompt  # from the EnvironmentSpec schema
    assert "Draft a NEW environment" in prompt
    assert "{{" not in prompt


def test_prompt_pins_an_existing_environment() -> None:
    prompt = build_system_prompt("e", "s", REFUND)
    assert "refund@1" in prompt and "issue_refund" in prompt
    assert "draft only the scenario" in prompt


# --- parsing ---


def test_extract_json_tolerates_fences_and_rejects_garbage() -> None:
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    for bad in ("no json here", "{not json}", "[1]"):
        with pytest.raises(ValueError, match=r"JSON|object"):
            extract_json(bad)


# --- repair loop ---


def test_valid_first_reply_is_returned_with_cost_and_notes() -> None:
    result = draft(Script(reply(scenario_json())))
    assert result.valid and result.attempts == 1 and result.errors == []
    assert result.notes == ["assumed amount"] and result.cost_usd == pytest.approx(0.01)
    assert result.environment is None and result.scenario.key == "refund.authored@1"


def test_semantic_errors_are_fed_back_and_fixed_on_retry() -> None:
    script = Script(reply(scenario_json(id="bad.one")), reply(scenario_json(id="good.one")))
    result = draft(script)
    assert result.valid and result.attempts == 2 and result.scenario.id == "good.one"
    assert result.cost_usd == pytest.approx(0.02)
    feedback = script.calls[1][-1]["content"]
    assert "id must not contain 'bad'" in feedback and script.calls[1][-2]["role"] == "assistant"


def test_schema_errors_are_fed_back_with_their_paths() -> None:
    script = Script(reply(scenario_json(assertions="nope")), reply(scenario_json()))
    result = draft(script)
    assert result.valid and "scenario.assertions" in script.calls[1][-1]["content"]


def test_unrecoverable_reply_stops_at_max_attempts() -> None:
    script = Script(*["not json"] * 3)
    result = draft(script)
    assert not result.valid and result.attempts == 3 and result.errors
    assert result.scenario is None


def test_last_invalid_scenario_is_kept_for_the_human() -> None:
    result = draft(Script(*[reply(scenario_json(id="bad.one"))] * 2), attempts=2)
    assert (
        not result.valid
        and result.scenario.id == "bad.one"
        and result.errors == ["scenario: id must not contain 'bad'"]
    )


def test_model_failure_is_a_draft_not_an_exception() -> None:
    def failing(model: str, messages: list[dict[str, str]]) -> Completion:
        raise AuthorError("author model HTTP 500")

    result = Author(complete=failing).draft(REQUEST, {"refund@1": REFUND}, no_errors_environment, reject_unsafe_ids)
    assert not result.valid and result.errors == ["author model HTTP 500"] and result.attempts == 1


def test_new_environment_must_pass_the_environment_validator() -> None:
    body = json.dumps({"environment": REFUND.model_dump(mode="json"), "scenario": scenario_json(), "notes": []})
    request = AuthorRequest(description="A support agent refunds an order; the payment API times out.")
    result = Author(model="m", max_attempts=1, complete=Script(body)).draft(
        request, {}, lambda spec: ["tool x does not prepare"], reject_unsafe_ids
    )
    assert not result.valid and result.errors == ["environment: tool x does not prepare"]


def test_unknown_environment_key_is_reported() -> None:
    request = AuthorRequest(description="A support agent refunds an order.", environment="nope@1")
    result = Author(complete=Script()).draft(request, {}, no_errors_environment, reject_unsafe_ids)
    assert not result.valid and "unknown environment" in result.errors[0]


# --- router ---


def client(script: Script) -> TestClient:
    app = FastAPI()
    app.include_router(
        authoring_router(
            lambda: Author(model="m", complete=script),
            lambda: {"refund@1": REFUND},
            no_errors_environment,
            reject_unsafe_ids,
        )
    )
    return TestClient(app)


def test_router_validates_the_request() -> None:
    http = client(Script())
    assert http.post("/v1/author", json={"description": "short"}).status_code == 422
    assert (
        http.post("/v1/author", json={"description": "A long enough description", "environment": "x@1"}).status_code
        == 404
    )


def test_router_always_returns_a_draft() -> None:
    ok = client(Script(reply(scenario_json()))).post("/v1/author", json=REQUEST.model_dump())
    assert ok.status_code == 200 and ok.json()["valid"] is True
    bad = client(Script(*["no"] * 3)).post("/v1/author", json=REQUEST.model_dump())
    body = bad.json()
    assert bad.status_code == 200 and body["valid"] is False and body["scenario"] is None and body["errors"]


# --- real engine validators (Postgres) ---


def real_validators(envs: FixturePool) -> tuple[EnvironmentValidator, ScenarioValidator]:
    return (
        lambda spec: environment_errors(envs, spec),
        lambda scenario, spec: semantic_errors(envs, scenario, {spec.key: spec}),
    )


def test_real_validators_accept_a_shipped_scenario_and_reject_a_broken_one(envs: FixturePool) -> None:
    shipped = yaml.safe_load((authoring.ROOT / "scenarios" / "refund_timeout.yaml").read_text())
    validate_environment, validate_scenario = real_validators(envs)
    broken = shipped | {"faults": [{"tool": "no_such_tool", "action": "timeout_after_commit"}]}
    result = Author(model="m", max_attempts=2, complete=Script(reply(broken), reply(shipped))).draft(
        REQUEST, {"refund@1": REFUND}, validate_environment, validate_scenario
    )
    assert result.valid
    assert result.attempts == 2


@pytest.mark.live
def test_live_author_drafts_a_valid_inventory_scenario(envs: FixturePool, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.undo()  # use the real example files, not the stubs of the autouse fixture
    validate_environment, validate_scenario = real_validators(envs)
    request = AuthorRequest(
        description=(
            "An inventory agent reserves stock for an order; the reserve API times out after reserving; "
            "the agent must not double-reserve and must tell the truth."
        )
    )
    draft = Author().draft(request, {}, validate_environment, validate_scenario)
    print(
        yaml.safe_dump(
            {
                "model": draft.model,
                "attempts": draft.attempts,
                "cost_usd": draft.cost_usd,
                "notes": draft.notes,
                "environment": draft.environment and draft.environment.model_dump(mode="json"),
                "scenario": draft.scenario and draft.scenario.model_dump(mode="json", exclude_unset=True),
            },
            sort_keys=False,
        )
    )
    assert draft.valid, draft.errors
    assert draft.environment is not None
    assert draft.scenario is not None
    assert not validate_environment(draft.environment)
    assert not validate_scenario(draft.scenario, draft.environment)
    assert draft.cost_usd is not None
    assert draft.cost_usd < 0.30
