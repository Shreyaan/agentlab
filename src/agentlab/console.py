"""Web console: browse experiments and trial evidence (HTML), plus a read-only JSON API."""

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from agentlab import report
from agentlab.models import Experiment, Trial
from agentlab.store import Store


class ExperimentDetail(BaseModel):
    experiment: Experiment
    trials: list[Trial]


def create_console(store: Store) -> FastAPI:
    app = FastAPI(title="AgentLab console")

    def experiment(exp_id: str) -> Experiment:
        try:
            return store.experiment(exp_id)
        except KeyError:
            raise HTTPException(404, f"unknown experiment {exp_id!r}") from None

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return report.render_index(store.experiments())

    @app.get("/experiments/{exp_id}", response_class=HTMLResponse)
    def experiment_page(exp_id: str) -> str:
        return report.render(experiment(exp_id), store.trials(exp_id))

    @app.get("/v1/experiments")
    def list_experiments(limit: int = 50) -> list[Experiment]:
        return store.experiments(min(max(limit, 1), 500))

    @app.get("/v1/experiments/{exp_id}")
    def get_experiment(exp_id: str) -> ExperimentDetail:
        return ExperimentDetail(experiment=experiment(exp_id), trials=store.trials(exp_id))

    @app.get("/v1/trials/{trial_id:path}")
    def get_trial(trial_id: str) -> Trial:
        try:
            return store.trial(trial_id)
        except KeyError:
            raise HTTPException(404, f"unknown trial {trial_id!r}") from None

    return app
