"""Durable experiment/trial records in Postgres (schema `agentlab`).

A trial is written as `running` before invocation, so a crash leaves an inspectable incomplete trial that the gate
treats as an error, never a pass. Everything is redacted on the way in.
"""

import re

from psycopg.types.json import Jsonb
from pydantic import JsonValue

from agentlab.db import Pool
from agentlab.models import Decision, Experiment, ExperimentMeta, Trial, TrialRecord, TrialStatus

SECRET_KEY = re.compile(r"secret|token|password|authorization|api[_-]?key|cookie", re.IGNORECASE)
SECRET_PARAM = re.compile(r"token|key|secret|sig|password", re.IGNORECASE)
QUERY_PARAM = re.compile(r"[?&]([^=&\s?#]{1,256})=")  # bounded, delimiter-free name: linear on hostile text
VALUE_END = re.compile(r"[&\s\"']")
SECRET_VALUE = [  # (pattern, replacement) for secrets embedded in free text: errors, outputs, URLs
    (re.compile(r"(://)[^/\s@]+@"), r"\1[REDACTED]@"),
    (re.compile(r"(bearer\s+)[\w.~+/=-]+", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r"\b(?:sk|pk|rk)[-_][\w-]{16,}|\bgh[pousr]_\w{20,}|\bAKIA[0-9A-Z]{16}\b"), "[REDACTED]"),
]

SCHEMA = """
SELECT pg_advisory_xact_lock(7311);  -- concurrent first runs must not race the DDL
CREATE SCHEMA IF NOT EXISTS agentlab;
CREATE TABLE IF NOT EXISTS agentlab.experiments (
    id TEXT PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), meta JSONB NOT NULL, decision JSONB
);
CREATE TABLE IF NOT EXISTS agentlab.trials (
    id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES agentlab.experiments(id) ON DELETE CASCADE,
    target TEXT NOT NULL, scenario TEXT NOT NULL, repeat INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'passed', 'failed', 'error')),
    record JSONB NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS trials_by_experiment ON agentlab.trials (experiment_id);
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


def redact(value: JsonValue) -> JsonValue:
    """Key-based for structured data (string values only, so typed numeric fields survive), pattern-based for text."""
    if isinstance(value, dict):
        return {k: "[REDACTED]" if SECRET_KEY.search(k) and isinstance(v, str) else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = redact_query_params(value)
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

    def experiments(self, limit: int = 50) -> list[Experiment]:
        with self.db.connection() as conn:
            rows = conn.execute("SELECT * FROM agentlab.experiments ORDER BY created_at DESC LIMIT %s", (limit,))
            return [Experiment.model_validate(r) for r in rows.fetchall()]

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
