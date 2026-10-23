import time
import uuid
from pathlib import Path

import pytest
import yaml

from agentlab.models import ExperimentMeta, TrialError, TrialRecord
from agentlab.protocol import ErrorCode, JsonObject, Usage
from agentlab.redaction import redact
from agentlab.store import Store

META = ExperimentMeta(targets={}, scenarios={}, repeats=1, fixture_url="http://127.0.0.1:1")


def new_id() -> str:
    return f"exp_test_{uuid.uuid4().hex[:8]}"


def test_trial_roundtrip_and_running_state_survives(store: Store) -> None:
    exp = new_id()
    store.create_experiment(exp, META)
    store.start_trial(f"{exp}:a", exp, "a", "s@1", 0)
    store.start_trial(f"{exp}:b", exp, "b", "s@1", 0)
    store.finish_trial(f"{exp}:a", "passed", TrialRecord(output="ok", latency_ms=12.5, usage=Usage(input_tokens=42)))
    trials = {t.id: t for t in store.trials(exp)}
    assert trials[f"{exp}:a"].record.usage.input_tokens == 42  # numeric fields survive key-based redaction
    assert trials[f"{exp}:b"].status == "running"  # a crash mid-trial stays visible, never a pass
    assert store.experiment(exp).meta == META


def test_persisted_records_are_redacted(store: Store) -> None:
    exp = new_id()
    store.create_experiment(exp, META.model_copy(update={"fixture_url": "http://user:pw@h/x?api_key=abc123&page=2"}))
    store.start_trial(f"{exp}:t", exp, "a", "s@1", 0)
    message = "HTTP 401 Bearer eyJhbGciOi.x.y sk-live_ABCDEFGHIJKLMNOPQRST"
    store.finish_trial(
        f"{exp}:t",
        "error",
        TrialRecord(
            error=TrialError(code=ErrorCode.ADAPTER_ERROR, message=message),
            output={"headers": {"Authorization": "Bearer z"}},
        ),
    )
    assert store.experiment(exp).meta.fixture_url == "http://[REDACTED]@h/x?api_key=[REDACTED]&page=2"
    rec = store.trial(f"{exp}:t").record
    assert rec.error is not None
    assert "eyJ" not in rec.error.message
    assert "sk-live" not in rec.error.message
    assert rec.output == {"headers": {"Authorization": "[REDACTED]"}}


@pytest.mark.parametrize(
    "raw",
    [
        "http://h/x?a=1?token=s3cr3t",  # benign value must not swallow the next param
        "http://h/x?api%5Fkey=s3cr3t&p=2",  # URL-encoded name
        "http://h/x?auth[token]=s3cr3t#frag",  # bracketed name
        "http://h/x?q=1&Signature=s3cr3t",
        "http://h/x?password=#s3cr3t",  # secret values may contain # or ?
        "http://h/x?token=?s3cr3t",
        "http://h/x?password=a#s3cr3t",
    ],
)
def test_query_secrets_redacted(raw: str) -> None:
    assert "s3cr3t" not in str(redact(raw))


def test_benign_query_params_untouched() -> None:
    assert redact("http://h/x?page=2&sort=asc#top") == "http://h/x?page=2&sort=asc#top"


def test_redaction_is_linear_on_hostile_input() -> None:
    started = time.perf_counter()
    redact("?" * 50_000 + "token" + "&" * 50_000)
    assert time.perf_counter() - started < 0.5


def test_secret_keys_redact_structured_values_but_keep_numbers() -> None:
    raw: JsonObject = {"token": ["abc"], "api_key": {"v": "x"}, "password": True, "input_tokens": 42, "page": "2"}
    assert redact(raw) == {
        "token": "[REDACTED]",
        "api_key": "[REDACTED]",
        "password": "[REDACTED]",
        "input_tokens": 42,
        "page": "2",
    }


@pytest.mark.parametrize(
    "raw",
    [
        "http://user:p@ss@db.internal:5432/x",  # '@' inside the password
        "postgresql://u:a@b@c@host/db?sslmode=require",
        "error contacting https://admin:s3cr3t@@h/ (timeout)",
        "http://u:p#ss@host/x",  # '#' inside the password
        "http://u:p?ss@host/x",  # '?' inside the password
    ],
)
def test_userinfo_redacted_up_to_last_at(raw: str) -> None:
    out = str(redact(raw))
    assert "[REDACTED]@" in out
    for leaked in ("ss@", "b@c", "s3cr3t", "p@ss", "p#ss", "p?ss"):
        assert leaked not in out


def test_userinfo_redaction_is_linear_and_scoped() -> None:
    started = time.perf_counter()
    redact("://" + "a" * 100_000)
    assert time.perf_counter() - started < 0.5
    assert redact("see https://h/x@y and mail me@x.org") == "see https://h/x@y and mail me@x.org"


def test_oversized_userinfo_does_not_fail_open() -> None:
    secret = "x" * 5000
    out = str(redact(f"http://user:{secret}@host/path"))
    assert secret not in out
    assert out == "http://[REDACTED]@host/path"


def test_userinfo_scan_is_linear_on_hostile_input() -> None:
    started = time.perf_counter()
    redact("://@" * 30_000 + "x" * 50_000)
    redact("://" + "@" * 100_000)
    assert time.perf_counter() - started < 0.5


def test_history_with_retired_checks_stays_readable(store: Store) -> None:
    from agentlab.scenario import Scenario, retired

    old = {
        "id": "legacy",
        "version": 1,
        "fixture": {},
        "input": {"message": "hi"},
        "assertions": [{"type": "output_matches", "pattern": "refund .* complete"}],
    }
    scenario = Scenario.model_validate(old)  # recorded experiments keep loading
    assert retired(scenario) == ["assertions.0: output_matches is retired; use a decision check"]
    exp = new_id()
    store.create_experiment(exp, META.model_copy(update={"scenarios": {scenario.key: scenario}}))
    assert store.experiment(exp).meta.scenarios["legacy@1"].assertions[0].type == "output_matches"
    assert any(s.id == exp for s in store.experiment_summaries(500, lambda _: False))


def test_suites_reject_retired_checks(tmp_path: Path) -> None:
    from agentlab.scenario import load_suite

    (tmp_path / "s.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "legacy",
                "version": 1,
                "fixture": {},
                "input": {},
                "assertions": [{"type": "output_matches", "pattern": "x"}],
            }
        )
    )
    with pytest.raises(ValueError, match="retired"):
        load_suite(tmp_path)
