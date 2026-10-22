"""Durable experiment/trial records. A trial is written as `running` before invocation, so a crash leaves
an inspectable incomplete trial that the gate treats as an error, never a pass."""

import json
import re
import sqlite3
import time
from pathlib import Path

SECRET_KEY = re.compile(r"secret|token|password|authorization|api[_-]?key|cookie", re.I)
SECRET_PARAM = re.compile(r"token|key|secret|sig|password", re.I)
SECRET_VALUE = [  # (pattern, replacement) for secrets embedded in free text: errors, outputs, URLs
    (re.compile(r"(://)[^/\s@]+@"), r"\1[REDACTED]@"),
    # Bounded name charset (no `?`/`&`) keeps this linear on untrusted text; the secret-word test runs in the callback.
    (re.compile(r"([?&]([\w.-]{1,64})=)([^&\s\"']+)"),
     lambda m: m[1] + "[REDACTED]" if SECRET_PARAM.search(m[2]) else m[0]),
    (re.compile(r"(bearer\s+)[\w.~+/=-]+", re.I), r"\1[REDACTED]"),
    (re.compile(r"\b(?:sk|pk|rk)[-_][\w-]{16,}|\bgh[pousr]_\w{20,}|\bAKIA[0-9A-Z]{16}\b"), "[REDACTED]"),
]


def redact(value):
    """Applied to everything persisted: key-based for structured data, pattern-based for free text."""
    if isinstance(value, dict):
        return {k: "[REDACTED]" if SECRET_KEY.search(str(k)) else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        for pattern, repl in SECRET_VALUE:
            value = pattern.sub(repl, value)
    return value


SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    id TEXT PRIMARY KEY, created_at REAL NOT NULL, meta TEXT NOT NULL, decision TEXT
);
CREATE TABLE IF NOT EXISTS trials (
    id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES experiments(id),
    target TEXT NOT NULL, scenario TEXT NOT NULL, repeat INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'passed', 'failed', 'error')),
    record TEXT
);
CREATE INDEX IF NOT EXISTS trials_by_experiment ON trials (experiment_id);
"""


class Store:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def create_experiment(self, exp_id: str, meta: dict) -> None:
        with self.db:
            self.db.execute("INSERT INTO experiments VALUES (?, ?, ?, NULL)", (exp_id, time.time(), json.dumps(redact(meta))))

    def start_trial(self, trial_id: str, exp_id: str, target: str, scenario: str, repeat: int) -> None:
        with self.db:
            self.db.execute("INSERT INTO trials VALUES (?, ?, ?, ?, ?, 'running', NULL)", (trial_id, exp_id, target, scenario, repeat))

    def finish_trial(self, trial_id: str, status: str, record: dict) -> None:
        with self.db:
            self.db.execute("UPDATE trials SET status = ?, record = ? WHERE id = ?", (status, json.dumps(redact(record), default=str), trial_id))

    def set_decision(self, exp_id: str, decision: dict) -> None:
        with self.db:
            self.db.execute("UPDATE experiments SET decision = ? WHERE id = ?", (json.dumps(redact(decision)), exp_id))

    def experiment(self, exp_id: str) -> dict:
        row = self.db.execute("SELECT * FROM experiments WHERE id = ?", (exp_id,)).fetchone()
        if not row:
            raise KeyError(exp_id)
        return {"id": row["id"], "created_at": row["created_at"], "meta": json.loads(row["meta"]),
                "decision": json.loads(row["decision"]) if row["decision"] else None}

    def trials(self, exp_id: str) -> list[dict]:
        rows = self.db.execute("SELECT * FROM trials WHERE experiment_id = ? ORDER BY rowid", (exp_id,))
        return [dict(r) | {"record": json.loads(r["record"]) if r["record"] else {}} for r in rows]
