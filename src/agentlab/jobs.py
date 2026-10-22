"""Background experiment execution for the console. A failed job is recorded on the experiment, never raised."""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from agentlab.runner import Runner, TrialPlan

log = logging.getLogger(__name__)


class Jobs:
    def __init__(self, runner: Runner, max_workers: int = 2) -> None:
        self.runner = runner
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="agentlab-job")
        self._running: set[str] = set()
        self._lock = threading.Lock()

    def submit(self, exp_id: str, plans: list[TrialPlan]) -> None:
        with self._lock:
            self._running.add(exp_id)
        self._executor.submit(self._run, exp_id, plans)

    def is_running(self, exp_id: str) -> bool:
        with self._lock:
            return exp_id in self._running

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=True)

    def _run(self, exp_id: str, plans: list[TrialPlan]) -> None:
        try:
            self.runner.execute(plans)
            self.runner.conclude(exp_id)
        except Exception as exc:  # a job must never take the server down
            log.exception("experiment %s failed", exp_id)
            self.runner.store.set_error(exp_id, f"{type(exc).__name__}: {exc}")
        finally:
            with self._lock:
                self._running.discard(exp_id)
