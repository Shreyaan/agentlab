"""Runs scenarios against harnesses: create isolated environment -> invoke -> collect evidence -> grade -> persist.

Trials run concurrently, each in its own environment schema. Black-box HTTP agents can't be pointed at a per-trial
environment, so their trials share one environment and run one at a time.
"""

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from typing import Literal

from agentlab.assertions import Evidence, grade
from agentlab.client import HarnessClient, Target
from agentlab.fixture import SHARED_ENV, FixturePool
from agentlab.models import Experiment, ExperimentMeta, TargetInfo, Trial, TrialError, TrialRecord
from agentlab.protocol import (
    AgentLabError,
    Environment,
    ErrorCode,
    Event,
    InvokeRequest,
    Manifest,
    ResumeFrom,
    ToolFault,
    new_traceparent,
)
from agentlab.records import LedgerEntry, state_diff
from agentlab.scenario import Scenario
from agentlab.store import Store


@dataclass(frozen=True)
class RunConfig:
    fixture_url: str  # base URL of the fixture service as agents see it, without /env/<id>
    repeats: int = 1
    deadline_ms: int = 60_000
    concurrency: int = 4


@dataclass(frozen=True)
class Connection:
    client: HarnessClient
    manifest: Manifest


type Conn = Connection | AgentLabError


@dataclass(frozen=True)
class TrialPlan:
    exp_id: str
    trial_id: str
    target: Target
    conn: Conn
    scenario: Scenario
    repeat: int
    fixture_faults: list[ToolFault]
    harness_faults: list[ToolFault]
    history: list[LedgerEntry]  # ledger prefix to restore (forks); empty for fresh runs
    resume_from: ResumeFrom | None = None


def ledger_calls_before(events: list[Event], checkpoint_id: str) -> int:
    """How many environment calls preceded a checkpoint. Relies on the adapter emitting one tool_completed/tool_failed
    per call; harness-injected failures that never reached the environment are marked committed=false and skipped."""
    n = 0
    for e in events:
        if e.type == "checkpoint_saved" and e.data.get("checkpoint_id") == checkpoint_id:
            return n
        if e.type in ("tool_completed", "tool_failed") and e.data.get("committed") is not False:
            n += 1
    raise ValueError(f"checkpoint {checkpoint_id!r} not found in trial events")


class Runner:
    def __init__(self, store: Store, pool: FixturePool, allowed_hosts: list[str], cfg: RunConfig) -> None:
        self.store, self.pool, self.allowed_hosts, self.cfg = store, pool, allowed_hosts, cfg
        self._shared_env_lock = threading.Lock()

    def connect(self, target: Target) -> Conn:
        try:
            client = HarnessClient(target, self.allowed_hosts)
            manifest = client.manifest()
        except AgentLabError as exc:
            return exc
        if not manifest.capabilities.invoke:
            return AgentLabError(
                ErrorCode.CAPABILITY_UNSUPPORTED, f"{target.name} is observe-only; it cannot be invoked"
            )
        return Connection(client, manifest)

    def run_experiment(self, scenarios: list[Scenario], targets: list[Target]) -> str:
        conns = {t.name: self.connect(t) for t in targets}
        exp_id = self._create_experiment(scenarios, targets, conns)
        # Same scenario+repeat across targets shares identical initial state, so comparisons are paired.
        plans = [
            TrialPlan(
                exp_id,
                f"{exp_id}:{t.name}:{s.key}:{r}",
                t,
                conns[t.name],
                s,
                r,
                s.faults_at("fixture"),
                s.faults_at("harness"),
                [],
            )
            for s in scenarios
            for r in range(self.cfg.repeats)
            for t in targets
        ]
        with ThreadPoolExecutor(max_workers=self.cfg.concurrency) as ex:
            list(ex.map(self.run_trial, plans))  # list() re-raises any unexpected runner error
        return exp_id

    def fork(
        self,
        source: Trial,
        experiment: Experiment,
        target: Target,
        checkpoint_id: str,
        faults: Literal["scenario", "none"] = "none",
    ) -> str:
        """Counterfactual: restore the environment as it was at `checkpoint_id` and resume the agent from there."""
        conn = self.connect(target)
        if isinstance(conn, AgentLabError):
            raise conn
        if not (conn.manifest.capabilities.fork and conn.manifest.capabilities.resume):
            raise AgentLabError(ErrorCode.CAPABILITY_UNSUPPORTED, f"{target.name} cannot fork from checkpoints")
        scenario = experiment.meta.scenarios[source.scenario]
        history = source.record.ledger[: ledger_calls_before(source.record.events, checkpoint_id)]
        resume = ResumeFrom(trial_id=source.id, checkpoint_id=checkpoint_id)
        exp_id = self._create_experiment([scenario], [target], {target.name: conn}, forked_from=resume)
        keep = faults == "scenario"
        self.run_trial(
            TrialPlan(
                exp_id,
                f"{exp_id}:{target.name}:{scenario.key}:fork",
                target,
                conn,
                scenario,
                0,
                scenario.faults_at("fixture") if keep else [],
                scenario.faults_at("harness") if keep else [],
                history,
                resume,
            )
        )
        return exp_id

    def _create_experiment(
        self,
        scenarios: list[Scenario],
        targets: list[Target],
        conns: dict[str, Conn],
        forked_from: ResumeFrom | None = None,
    ) -> str:
        exp_id = f"exp_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self.store.create_experiment(
            exp_id,
            ExperimentMeta(
                targets={
                    t.name: TargetInfo(
                        mode=t.mode,
                        url=t.url,
                        version=t.version,
                        manifest=c.manifest if isinstance(c := conns[t.name], Connection) else None,
                    )
                    for t in targets
                },
                scenarios={s.key: s for s in scenarios},
                repeats=self.cfg.repeats,
                fixture_url=self.cfg.fixture_url,
                forked_from=forked_from,
            ),
        )
        return exp_id

    def run_trial(self, plan: TrialPlan) -> None:
        self.store.start_trial(plan.trial_id, plan.exp_id, plan.target.name, plan.scenario.key, plan.repeat)
        conn = plan.conn
        if isinstance(conn, AgentLabError):
            self._error(plan, conn)
            return
        if plan.harness_faults and conn.manifest.capabilities.intercept_tools == "none":
            self._error(
                plan,
                AgentLabError(ErrorCode.CAPABILITY_UNSUPPORTED, f"{plan.target.name} cannot inject harness faults"),
            )
            return
        shared = plan.target.mode == "http"
        env_id = SHARED_ENV if shared else uuid.uuid4().hex[:16]
        lock: AbstractContextManager[object] = self._shared_env_lock if shared else nullcontext()
        with lock:
            self.pool.create(env_id, plan.scenario.fixture, plan.fixture_faults, plan.history)
            try:
                self._execute(plan, conn, env_id)
            finally:
                self.pool.drop(env_id)

    def _execute(self, plan: TrialPlan, conn: Connection, env_id: str) -> None:
        fixture = self.pool.get(env_id)
        initial = fixture.state()
        req = InvokeRequest(
            trial_id=plan.trial_id,
            scenario_version=plan.scenario.key,
            system_version=plan.target.version,
            environment=Environment(id=env_id, base_url=f"{self.cfg.fixture_url.rstrip('/')}/env/{env_id}"),
            idempotency_key=f"{plan.trial_id}:invoke",
            input=plan.scenario.input,
            deadline_ms=self.cfg.deadline_ms,
            traceparent=new_traceparent(),
            tool_faults=plan.harness_faults,
            resume_from=plan.resume_from,
        )
        started = time.perf_counter()
        try:
            resp = conn.client.invoke(req)
        except AgentLabError as exc:
            self._error(plan, exc, TrialRecord(ledger=fixture.ledger(), initial_state=initial))
            return
        latency_ms = (time.perf_counter() - started) * 1000

        ledger, final = fixture.ledger(), fixture.state()
        ev = Evidence(
            fixture=fixture,
            ledger=ledger,
            events=resp.events,
            output=resp.output,
            capabilities=conn.manifest.capabilities,
            latency_ms=latency_ms,
            usage=resp.usage,
        )
        results = grade(plan.scenario.assertions, plan.scenario.budget, ev)
        self.store.finish_trial(
            plan.trial_id,
            "failed" if any(r.status == "fail" for r in results) else "passed",
            TrialRecord(
                run_id=resp.run_id,
                agent_status=resp.status,
                output=resp.output,
                events=resp.events,
                ledger=ledger,
                initial_state=initial,
                final_state=final,
                state_diff=state_diff(initial, final),
                assertions=results,
                latency_ms=latency_ms,
                usage=resp.usage,
                resumed_from=plan.resume_from,
            ),
        )

    def _error(self, plan: TrialPlan, exc: AgentLabError, record: TrialRecord | None = None) -> None:
        record = (record or TrialRecord()).model_copy(update={"error": TrialError(code=exc.code, message=exc.message)})
        self.store.finish_trial(plan.trial_id, "error", record)
