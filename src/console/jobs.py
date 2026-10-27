"""Lượt demo trực tiếp chạy nền — mỗi lúc một lượt.

Hạ tầng lab (hộp thư MailHog, kho phiếu, Qdrant, canary listener) là trạng thái dùng chung giữa
các run, nên hai lượt chạy song song sẽ dọn dữ liệu của nhau. `JobManager` từ chối lượt mới khi
lượt trước chưa xong.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
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
    sandbox: Any = None  # demo.Sandbox khi target = "sandbox"
    status: str = "queued"  # queued · running · done · error
    events: list[dict[str, Any]] = field(default_factory=list)
    batch_id: str | None = None
    spent_usd: float | None = None
    budget_status: str | None = None
    error: str | None = None
    created_at: str = field(default_factory=_now)
    finished_at: str | None = None
    # preset → run đang/đã chạy: meta của recorder + các bước (dict của `obs.trace.Step`) tới hiện tại.
    live: dict[str, dict[str, Any]] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        out = {k: v for k, v in self.__dict__.items() if k != "live"}
        out["sandbox"] = asdict(self.sandbox) if self.sandbox else None
        return out


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
        self,
        scenario_key: str,
        target: str,
        presets: Sequence[str],
        prompt_variant: str | None,
        sandbox: Any = None,
    ) -> Job:
        scenario = demo.scenario(scenario_key)  # KeyError nếu khóa lạ
        with self._lock:
            if self._active and self._jobs[self._active].status in ("queued", "running"):
                raise BusyError(self._active)
            job = Job(
                uuid.uuid4().hex[:12], scenario_key, target, list(presets), prompt_variant, sandbox
            )
            self._jobs[job.id] = job
            self._active = job.id
        threading.Thread(target=self._run, args=(job, scenario), daemon=True).start()
        return job

    def _run(self, job: Job, scenario: Any) -> None:
        job.status = "running"

        def progress(preset: str, event: str) -> None:
            job.events.append({"preset": preset, "event": event, "at": _now()})

        def step(preset: str, rec: Any, s: Any) -> None:
            run = rec.run
            entry = job.live.get(preset)
            if entry is None or entry["run_id"] != rec.run_id:
                entry = job.live[preset] = {
                    "run_id": rec.run_id, "payload_id": run.payload_id, "lang": run.lang,
                    "canaries": run.run_canaries, "steps": [],
                }
            # Bản sao dữ liệu, không giữ object ORM: khi run ghi xong, session commit làm object
            # hết hạn và đọc lại từ luồng API sẽ lỗi DetachedInstanceError.
            entry["steps"].append(s.model_dump())

        try:
            result = self._runner(
                scenario, target=job.target, presets=job.presets,
                prompt_variant=job.prompt_variant, on_progress=progress, sandbox=job.sandbox,
                on_step=step,
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
