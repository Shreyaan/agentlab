"""Durable experiment/trial records in Postgres (schema `agentlab`).

A trial is written as `running` before invocation, so a crash leaves an inspectable incomplete trial that the gate
treats as an error, never a pass. Everything is redacted on the way in.
"""

from collections.abc import Callable
from typing import Any

from psycopg.types.json import Jsonb

from agentlab.api_models import ExperimentStatus, ExperimentSummary
from agentlab.db import Pool
from agentlab.models import Decision, Experiment, ExperimentMeta, Trial, TrialRecord, TrialStatus
from agentlab.records import CanaryResult, JudgeStats
from agentlab.redaction import redact
from agentlab.verdicts import is_calibrated

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
CREATE TABLE IF NOT EXISTS agentlab.canary_results (
    id BIGSERIAL PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES agentlab.experiments(id) ON DELETE CASCADE,
    scenario TEXT NOT NULL, check_name TEXT NOT NULL, label TEXT NOT NULL, model TEXT NOT NULL,
    expected TEXT NOT NULL, verdict TEXT NOT NULL, correct BOOLEAN NOT NULL, answer JSONB NOT NULL, cost_usd FLOAT8
);
CREATE INDEX IF NOT EXISTS canary_results_by_experiment ON agentlab.canary_results (experiment_id);
"""

SUMMARY_SELECT = """
SELECT e.id, e.created_at, e.meta, e.decision, e.error,
    count(t.id) FILTER (WHERE t.status <> 'running') AS finished,
    count(t.id) FILTER (WHERE t.status = 'error') AS errors,
    sum((t.record->'usage'->>'cost_usd')::float8) AS cost_usd
FROM agentlab.experiments e LEFT JOIN agentlab.trials t ON t.experiment_id = e.id
"""

JUDGE_STATS_SQL = """
WITH verdicts AS (
    SELECT a->'judge' AS j FROM agentlab.trials t, jsonb_array_elements(t.record->'assertions') a
    WHERE jsonb_typeof(a->'judge') = 'object'
), calibration AS (
    SELECT c.key AS model, count(*) AS samples, count(*) FILTER (WHERE c.value = 'true'::jsonb) AS correct
    FROM verdicts, jsonb_each(j->'calibration_correct') c GROUP BY c.key
), canaries AS (
    SELECT model, count(*) AS canary_samples, count(*) FILTER (WHERE correct) AS canary_correct
    FROM agentlab.canary_results GROUP BY model
), cost AS (
    SELECT model, sum(cost_usd) AS cost_usd FROM (
        SELECT x->>'model' AS model, (x->>'cost_usd')::float8 AS cost_usd
        FROM verdicts, jsonb_array_elements(j->'judges') x
        UNION ALL SELECT model, cost_usd FROM agentlab.canary_results
    ) costs GROUP BY model
)
SELECT model, coalesce(samples, 0) AS samples, coalesce(correct, 0) AS correct,
    coalesce(canary_samples, 0) AS canary_samples, coalesce(canary_correct, 0) AS canary_correct, cost_usd
FROM calibration FULL JOIN canaries USING (model) FULL JOIN cost USING (model) ORDER BY model
"""


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

    def add_canary_results(self, results: list[CanaryResult]) -> None:
        with self.db.connection() as conn, conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO agentlab.canary_results (experiment_id, scenario, check_name, label, model, expected, "
                "verdict, correct, answer, cost_usd) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    (
                        r.experiment_id,
                        r.scenario,
                        redact(r.check),
                        r.label,
                        r.model,
                        r.expected,
                        r.verdict,
                        r.correct,
                        Jsonb(redact(r.answer)),
                        r.cost_usd,
                    )
                    for r in results
                ],
            )

    def canary_results(self, exp_id: str) -> list[CanaryResult]:
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT experiment_id, scenario, check_name AS check, label, model, expected, verdict, correct, "
                "answer, cost_usd FROM agentlab.canary_results WHERE experiment_id = %s ORDER BY id",
                (exp_id,),
            ).fetchall()
        return [CanaryResult.model_validate(r) for r in rows]

    def judge_stats(self) -> list[JudgeStats]:
        with self.db.connection() as conn:
            rows = conn.execute(JUDGE_STATS_SQL).fetchall()
        return [
            JudgeStats(
                model=r["model"],
                samples=r["samples"],
                correct=r["correct"],
                accuracy=r["correct"] / r["samples"] if r["samples"] else None,
                canary_samples=r["canary_samples"],
                canary_correct=r["canary_correct"],
                canary_accuracy=r["canary_correct"] / r["canary_samples"] if r["canary_samples"] else None,
                cost_usd=r["cost_usd"],
                calibrated=is_calibrated(r["samples"], r["correct"], r["canary_samples"], r["canary_correct"]),
            )
            for r in rows
        ]

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
