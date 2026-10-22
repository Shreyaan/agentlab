"""Operator web console: JSON API under /v1 plus the built single-page frontend."""

import secrets
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, Response

from agentlab import report
from agentlab.api_models import (
    Accepted,
    ConsoleInfo,
    ExperimentDetail,
    ExperimentSummary,
    ForkRequest,
    RunRequest,
    ScenarioInfo,
    TargetHealth,
)
from agentlab.client import HarnessClient, Target, load_targets
from agentlab.jobs import Jobs
from agentlab.models import Trial
from agentlab.protocol import PROTOCOL_VERSION, AgentLabError, ErrorCode
from agentlab.runner import Runner
from agentlab.scenario import Scenario, load_suite

DIST_DIR = Path(__file__).parent / "console_dist"
PROBE_TIMEOUT_S = 3
NOT_BUILT = (
    "<!doctype html><title>AgentLab console</title><p>The console frontend is not built. "
    "Run <code>cd console &amp;&amp; bun install &amp;&amp; bun run build</code>, then restart.</p>"
)


@dataclass(frozen=True, kw_only=True)
class Console:
    runner: Runner
    jobs: Jobs
    targets_path: str
    suite_path: str
    token: str | None

    def require_token(self, authorization: Annotated[str, Header()] = "") -> None:
        if self.token and not secrets.compare_digest(authorization.encode(), f"Bearer {self.token}".encode()):
            raise HTTPException(401, "missing or invalid bearer token")

    def known_targets(self) -> dict[str, Target]:
        return _config(lambda: load_targets(self.targets_path)[0], self.targets_path)

    def suite(self) -> dict[str, Scenario]:
        return _config(lambda: {s.key: s for s in load_suite(self.suite_path)}, self.suite_path)

    def target_named(self, name: str) -> Target:
        if name not in (targets := self.known_targets()):
            raise HTTPException(422, f"unknown target {name!r}")
        return targets[name]

    def probe(self, target: Target) -> TargetHealth:
        info = {"name": target.name, "mode": target.mode, "url": target.url, "version": target.version}
        try:
            manifest = HarnessClient(target, self.runner.allowed_hosts).manifest(timeout=PROBE_TIMEOUT_S)
        except AgentLabError as exc:
            return TargetHealth(**info, reachable=False, manifest=target.manifest, error=exc.message)
        return TargetHealth(**info, reachable=True, manifest=manifest)

    def summary(self, exp_id: str) -> ExperimentSummary:
        try:
            return self.runner.store.experiment_summary(exp_id, self.jobs.is_running)
        except KeyError:
            raise HTTPException(404, f"unknown experiment {exp_id!r}") from None

    def info(self) -> ConsoleInfo:
        return ConsoleInfo(
            version=version("agentlab"),
            protocol_version=PROTOCOL_VERSION,
            auth_required=bool(self.token),
            suite_path=self.suite_path,
            targets_path=self.targets_path,
        )

    def targets(self) -> list[TargetHealth]:
        with ThreadPoolExecutor() as ex:
            return list(ex.map(self.probe, self.known_targets().values()))

    def scenarios(self) -> list[ScenarioInfo]:
        return [ScenarioInfo(key=key, scenario=s) for key, s in self.suite().items()]

    def list_experiments(self, limit: Annotated[int, Query(ge=1, le=500)] = 50) -> list[ExperimentSummary]:
        return self.runner.store.experiment_summaries(limit, self.jobs.is_running)

    def run_experiment(self, body: RunRequest) -> Accepted:
        suite = self.suite()
        if unknown := [k for k in body.scenarios if k not in suite]:
            raise HTTPException(422, f"unknown scenario(s): {', '.join(unknown)}")
        names = [body.candidate, *([body.baseline] if body.baseline else [])]
        exp_id, plans = self.runner.plan_experiment(
            [suite[k] for k in body.scenarios] if body.scenarios else list(suite.values()),
            [self.target_named(n) for n in names],
            repeats=body.repeats,
            candidate=body.candidate,
            baseline=body.baseline,
            max_regression=body.max_regression,
        )
        self.jobs.submit(exp_id, plans)
        return Accepted(experiment_id=exp_id)

    def get_experiment(self, exp_id: str) -> ExperimentDetail:
        store = self.runner.store
        return ExperimentDetail(
            summary=self.summary(exp_id), experiment=store.experiment(exp_id), trials=store.trials(exp_id)
        )

    def get_report(self, exp_id: str) -> str:
        self.summary(exp_id)
        return report.render(self.runner.store.experiment(exp_id), self.runner.store.trials(exp_id))

    def get_trial(self, trial_id: str) -> Trial:
        try:
            return self.runner.store.trial(trial_id)
        except KeyError:
            raise HTTPException(404, f"unknown trial {trial_id!r}") from None

    def fork(self, body: ForkRequest) -> Accepted:
        source = self.get_trial(body.trial_id)
        target = self.target_named(body.target or source.target)
        try:
            exp_id, plans = self.runner.plan_fork(
                source, self.runner.store.experiment(source.experiment_id), target, body.checkpoint_id, body.faults
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except AgentLabError as exc:
            raise HTTPException(409 if exc.code == ErrorCode.CAPABILITY_UNSUPPORTED else 502, exc.message) from exc
        self.jobs.submit(exp_id, plans)
        return Accepted(experiment_id=exp_id)

    def router(self) -> APIRouter:
        api = APIRouter(prefix="/v1", dependencies=[Depends(self.require_token)])
        post = [Depends(require_csrf_header)]
        api.get("/info")(self.info)
        api.get("/targets")(self.targets)
        api.get("/scenarios")(self.scenarios)
        api.get("/experiments")(self.list_experiments)
        api.post("/experiments", status_code=202, dependencies=post)(self.run_experiment)
        api.get("/experiments/{exp_id}")(self.get_experiment)
        api.get("/experiments/{exp_id}/report.html", response_class=HTMLResponse)(self.get_report)
        api.get("/trials/{trial_id:path}")(self.get_trial)
        api.post("/forks", status_code=202, dependencies=post)(self.fork)
        return api


def _config[T](load: Callable[[], T], path: str) -> T:
    """Config files are edited by hand while the console runs; report problems instead of a bare 500."""
    try:
        return load()
    except (OSError, ValueError, yaml.YAMLError) as exc:  # pydantic ValidationError is a ValueError
        raise HTTPException(503, f"cannot load {path}: {exc}") from exc


def require_csrf_header(x_agentlab_request: Annotated[str, Header()] = "") -> None:
    if x_agentlab_request != "1":  # a custom header forces a CORS preflight, which we never grant
        raise HTTPException(403, "missing X-AgentLab-Request: 1 header")


def create_console(console: Console, dist_dir: Path = DIST_DIR) -> FastAPI:
    app = FastAPI(title="AgentLab console")  # no CORS middleware: the console is same-origin only
    app.include_router(console.router())
    serve_frontend(app, dist_dir)
    return app


def serve_frontend(app: FastAPI, dist_dir: Path) -> None:
    index = dist_dir / "index.html"
    if not index.is_file():

        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        def not_built() -> str:
            return NOT_BUILT

        return

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str) -> Response:
        if path == "v1" or path.startswith("v1/"):
            raise HTTPException(404, "not found")
        file = (dist_dir / path).resolve()
        return FileResponse(file if file.is_file() and file.is_relative_to(dist_dir.resolve()) else index)


def openapi_schema() -> dict[str, Any]:
    """Routes only touch their dependencies when called, so placeholders are enough to describe the API."""
    nothing: Any = None
    console = Console(runner=nothing, jobs=nothing, targets_path="targets.yaml", suite_path="scenarios", token=None)
    return create_console(console).openapi()
