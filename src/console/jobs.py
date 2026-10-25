"""Lượt demo trực tiếp chạy nền — mỗi lúc một lượt.

Hạ tầng lab (hộp thư MailHog, kho phiếu, Qdrant, canary listener) là trạng thái dùng chung giữa
các run, nên hai lượt chạy song song sẽ dọn dữ liệu của nhau. `JobManager` từ chối lượt mới khi
lượt trước chưa xong.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from console.data import demo


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Job:
    id: str
    scenario: str
    target: str
    presets: list[str]
    prompt_variant: str | None
    status: str = "queued"  # queued · running · done · error
    events: list[dict[str, Any]] = field(default_factory=list)
    batch_id: str | None = None
    spent_usd: float | None = None
    budget_status: str | None = None
    error: str | None = None
    created_at: str = field(default_factory=_now)
    finished_at: str | None = None

    def public(self) -> dict[str, Any]:
        return dict(self.__dict__)


class BusyError(RuntimeError):
    pass


class JobManager:
    def __init__(self, runner: Callable[..., Any] = demo.run_demo) -> None:
        self._runner = runner
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._active: str | None = None

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def active(self) -> Job | None:
        return self._jobs.get(self._active) if self._active else None

    def start(
        self, scenario_key: str, target: str, presets: Sequence[str], prompt_variant: str | None
    ) -> Job:
        scenario = demo.scenario(scenario_key)  # KeyError nếu khóa lạ
        with self._lock:
            if self._active and self._jobs[self._active].status in ("queued", "running"):
                raise BusyError(self._active)
            job = Job(uuid.uuid4().hex[:12], scenario_key, target, list(presets), prompt_variant)
            self._jobs[job.id] = job
            self._active = job.id
        threading.Thread(target=self._run, args=(job, scenario), daemon=True).start()
        return job

    def _run(self, job: Job, scenario: Any) -> None:
        job.status = "running"

        def progress(preset: str, event: str) -> None:
            job.events.append({"preset": preset, "event": event, "at": _now()})

        try:
            result = self._runner(
                scenario, target=job.target, presets=job.presets,
                prompt_variant=job.prompt_variant, on_progress=progress,
            )
            job.batch_id = result.batch_id
            job.spent_usd = result.spent_usd
            job.budget_status = result.budget_status
            job.status = "done"
        except Exception as e:  # noqa: BLE001 — báo lỗi lên giao diện, không làm sập server
            job.error = f"{type(e).__name__}: {e}"
            job.status = "error"
        finally:
            job.finished_at = _now()
