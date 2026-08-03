from __future__ import annotations

import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from .store import JsonStore, utc_now


class JobRunner:
    def __init__(self, store: JsonStore, workers: int = 2) -> None:
        self.store = store
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="atlas-job")

    def submit(self, kind: str, actor: dict, task: Callable[[], dict]) -> dict:
        job = self.store.insert(
            "jobs",
            {
                "kind": kind,
                "status": "pending",
                "requested_by": actor.get("username"),
                "requested_role": actor.get("role"),
            },
            "job",
        )
        self.executor.submit(self._run, job["id"], task)
        return job

    def _run(self, job_id: str, task: Callable[[], dict]) -> None:
        self.store.update("jobs", job_id, {"status": "running", "started_at": utc_now()})
        try:
            result = task()
            self.store.update(
                "jobs",
                job_id,
                {"status": "completed", "completed_at": utc_now(), "result": result},
            )
        except Exception as exc:
            self.store.update(
                "jobs",
                job_id,
                {
                    "status": "failed",
                    "completed_at": utc_now(),
                    "error": str(exc),
                    "traceback": traceback.format_exc(limit=8),
                },
            )
