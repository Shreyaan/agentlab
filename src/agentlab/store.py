"""Durable experiment/trial records in Postgres (schema `agentlab`).

A trial is written as `running` before invocation, so a crash leaves an inspectable incomplete trial that the gate
treats as an error, never a pass. Everything is redacted on the way in.
"""

import re
from collections.abc import Callable
from typing import Any

from psycopg.types.json import Jsonb
from pydantic import JsonValue

from agentlab.api_models import ExperimentStatus, ExperimentSummary
from agentlab.db import Pool
from agentlab.models import Decision, Experiment, ExperimentMeta, Trial, TrialRecord, TrialStatus

SECRET_KEY = re.compile(r"secret|token|password|authorization|api[_-]?key|cookie", re.IGNORECASE)
SECRET_PARAM = re.compile(r"token|key|secret|sig|password", re.IGNORECASE)
QUERY_PARAM = re.compile(r"[?&]([^=&\s?#]{1,256})=")  # bounded, delimiter-free name: linear on hostile text
VALUE_END = re.compile(r"[&\s\"']")
AUTHORITY_END = re.compile(r"[/\s]")
SECRET_VALUE = [  # (pattern, replacement) for secrets embedded in free text: errors, outputs, URLs
    (re.compile(r"(bearer\s+)[\w.~+/=-]+", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r"\b(?:sk|pk|rk)[-_][\w-]{16,}|\bgh[pousr]_\w{20,}|\bAKIA[0-9A-Z]{16}\b"), "[REDACTED]"),
]

SCHEMA = """
SELECT pg_advisory_xact_lock(7311);  -- concurrent first runs must not race the DDL
CREATE SCHEMA IF NOT EXISTS agentlab;
CREATE TABLE IF NOT EXISTS agentlab.experiments (
    id TEXT PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), meta JSONB NOT NULL, decision JSONB
);
ALTER TABLE agentlab.experiments ADD COLUMN IF NOT EXISTS error TEXT;
CREATE TABLE IF NOT EXISTS agentlab.trials (
    id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES agentlab.experiments(id) ON DELETE CASCADE,
    target TEXT NOT NULL, scenario TEXT NOT NULL, repeat INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'passed', 'failed', 'error')),
    record JSONB NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS trials_by_experiment ON agentlab.trials (experiment_id);
"""

SUMMARY_SELECT = """
SELECT e.id, e.created_at, e.meta, e.decision, e.error,
    count(t.id) FILTER (WHERE t.status <> 'running') AS finished,
    count(t.id) FILTER (WHERE t.status = 'error') AS errors,
    sum((t.record->'usage'->>'cost_usd')::float8) AS cost_usd
FROM agentlab.experiments e LEFT JOIN agentlab.trials t ON t.experiment_id = e.id
"""


def redact_query_params(text: str) -> str:
    """Secret-named params are redacted up to the next & / whitespace / quote (values may contain ? or #).
    Benign params are skipped without consuming their value, so a param embedded in it is still found."""
    out, pos = [], 0
    for m in QUERY_PARAM.finditer(text):
        if m.start() < pos or not SECRET_PARAM.search(m[1]):
            continue
        end = VALUE_END.search(text, m.end())
        out += [text[pos : m.end()], "[REDACTED]"]
        pos = end.start() if end else len(text)
    return "".join(out) + text[pos:]


def _is_number_or_null(value: JsonValue) -> bool:
    return value is None or (isinstance(value, int | float) and not isinstance(value, bool))


def redact_userinfo(text: str) -> str:
    """Redact URL credentials up to the LAST '@' before the next '/' or whitespace (passwords may contain '@', '?',
    '#'). No length bound, so nothing fails open; each authority span is scanned once, so it is linear."""
    out, pos = [], 0
    while (scheme := text.find("://", pos)) != -1:
        start = scheme + 3
        end = m.start() if (m := AUTHORITY_END.search(text, start)) else len(text)
        at = text.rfind("@", start, end)
        out.append(text[pos:start] + ("[REDACTED]" if at != -1 else ""))
        pos = at if at != -1 else start
    return "".join(out) + text[pos:]


def redact(value: JsonValue) -> JsonValue:
    """Key-based for structured data, pattern-based for free text. Under a secret-looking key everything is redacted
    except numbers and nulls, so numeric telemetry such as input_tokens survives."""
    if isinstance(value, dict):
        return {
            k: redact(v) if not SECRET_KEY.search(k) or _is_number_or_null(v) else "[REDACTED]"
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = redact_query_params(redact_userinfo(value))
        for pattern, repl in SECRET_VALUE:
            value = pattern.sub(repl, value)
    return value


class Store:
    def __init__(self, db: Pool) -> None:
        self.db = db
        with db.connection() as conn, conn.transaction():
            conn.execute(SCHEMA)

    def create_experiment(self, exp_id: str, meta: ExperimentMeta) -> None:
        with self.db.connection() as conn:
            conn.execute(
                "INSERT INTO agentlab.experiments (id, meta) VALUES (%s, %s)",
                (exp_id, Jsonb(redact(meta.model_dump(mode="json")))),
            )

    def start_trial(self, trial_id: str, exp_id: str, target: str, scenario: str, repeat: int) -> None:
        with self.db.connection() as conn:
            conn.execute(
                "INSERT INTO agentlab.trials (id, experiment_id, target, scenario, repeat, status) "
                "VALUES (%s, %s, %s, %s, %s, 'running')",
                (trial_id, exp_id, target, scenario, repeat),
            )

    def finish_trial(self, trial_id: str, status: TrialStatus, record: TrialRecord) -> None:
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE agentlab.trials SET status = %s, record = %s WHERE id = %s",
                (status, Jsonb(redact(record.model_dump(mode="json"))), trial_id),
            )

    def set_decision(self, exp_id: str, decision: Decision) -> None:
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE agentlab.experiments SET decision = %s WHERE id = %s",
                (Jsonb(redact(decision.model_dump(mode="json"))), exp_id),
            )

    def experiment(self, exp_id: str) -> Experiment:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM agentlab.experiments WHERE id = %s", (exp_id,)).fetchone()
        if not row:
            raise KeyError(exp_id)
        return Experiment.model_validate(row)

    def set_error(self, exp_id: str, message: str) -> None:
        with self.db.connection() as conn:
            conn.execute("UPDATE agentlab.experiments SET error = %s WHERE id = %s", (redact(message), exp_id))

    def experiment_summaries(self, limit: int, is_running: Callable[[str], bool]) -> list[ExperimentSummary]:
        with self.db.connection() as conn:
            rows = conn.execute(
                SUMMARY_SELECT + "GROUP BY e.id ORDER BY e.created_at DESC LIMIT %s", (limit,)
            ).fetchall()
        return [_summary(r, is_running) for r in rows]

    def experiment_summary(self, exp_id: str, is_running: Callable[[str], bool]) -> ExperimentSummary:
        with self.db.connection() as conn:
            row = conn.execute(SUMMARY_SELECT + "WHERE e.id = %s GROUP BY e.id", (exp_id,)).fetchone()
        if not row:
            raise KeyError(exp_id)
        return _summary(row, is_running)

    def trials(self, exp_id: str) -> list[Trial]:
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM agentlab.trials WHERE experiment_id = %s ORDER BY created_at, id", (exp_id,)
            ).fetchall()
        return [Trial.model_validate(r) for r in rows]

    def trial(self, trial_id: str) -> Trial:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM agentlab.trials WHERE id = %s", (trial_id,)).fetchone()
        if not row:
            raise KeyError(trial_id)
        return Trial.model_validate(row)


def _summary(row: dict[str, Any], is_running: Callable[[str], bool]) -> ExperimentSummary:
    meta = ExperimentMeta.model_validate(row["meta"])
    decision = Decision.model_validate(row["decision"]) if row["decision"] else None
    status: ExperimentStatus = "complete" if decision else "running" if is_running(row["id"]) else "incomplete"
    return ExperimentSummary(
        id=row["id"],
        created_at=row["created_at"],
        status=status,
        # experiments recorded before meta carried these fall back to the decision / trial count
        candidate=meta.candidate or (decision.candidate if decision else None),
        baseline=meta.baseline or (decision.baseline if decision else None),
        decision=decision.status if decision else None,
        planned=meta.planned_trials or row["finished"],
        finished=row["finished"],
        errors=row["errors"],
        cost_usd=row["cost_usd"],
        forked_from=meta.forked_from,
        error=row["error"],
    )
