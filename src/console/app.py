"""FastAPI của IPI Guard Console. Phục vụ API `/api/*` và bản build của `web/` (nếu có).

Chỉ đọc trace store; ghi duy nhất qua lượt demo (`POST /api/demo/jobs`, cần `DEMO_LIVE=1`), vốn
đi đúng đường `run_one_attack` của lô thật và canh chi phí bằng `BudgetGuard`.

Server chỉ nghe `127.0.0.1` (`make console`). Middleware từ chối mọi Host ngoài localhost để chặn
DNS rebinding — trang web lạ không thể gọi API qua tên miền trỏ về máy này mà đốt ngân sách API.

    PYTHONPATH=src:dashboard uv run uvicorn console.app:app --host 127.0.0.1 --port 8600
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Annotated

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from console import data
from console.jobs import BusyError, JobManager

load_dotenv(data.ROOT / ".env")

WEB_DIST = data.ROOT / "web" / "dist"
ALLOWED_HOSTS = {"localhost", "127.0.0.1", "[::1]", "testserver"}

app = FastAPI(title="IPI Guard Console", version="1.0.0", docs_url="/api/docs",
              openapi_url="/api/openapi.json")
cache = data.RunCache()
jobs = JobManager()

Batches = Annotated[list[str] | None, Query(alias="batch")]
Kinds = Annotated[list[str] | None, Query(alias="kind")]


def scoped(batch: list[str] | None, kind: list[str] | None, **equals):
    """Run theo lô đã chọn; không chọn lô thì theo loại lô (mặc định chỉ lô thực nghiệm)."""
    return data.select(cache.runs(), batches=batch, kinds=kind or ("experiment",), **equals)


@app.middleware("http")
async def localhost_only(request: Request, call_next):
    host = (request.headers.get("host") or "").rsplit(":", 1)[0].lower()
    if host not in ALLOWED_HOSTS:
        return JSONResponse({"detail": "chỉ phục vụ localhost"}, status_code=403)
    return await call_next(request)


def live() -> bool:
    return os.getenv("DEMO_LIVE") == "1"


def _commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(data.ROOT), "describe", "--always", "--dirty"],
            capture_output=True, text=True, timeout=3, check=False,
        )
        return out.stdout.strip() or None
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------


@app.get("/api/meta")
def meta() -> dict:
    cfg = data.config_summary()
    return {
        "product": "IPI Guard Console",
        "lab_commit": _commit(),
        "models": {t["id"]: t["model_id"] for t in cfg["targets"]},
        "model_tag": "v-models-1.0",
        "attack_tag": "v-attack-1.0",
        "prompt_active": cfg["prompt"]["active"],
        "live_demo": live(),
    }


@app.get("/api/overview")
def overview(batch: Batches = None, kind: Kinds = None) -> dict:
    return data.overview(cache, scoped(batch, kind))


@app.get("/api/batches")
def batches(kind: Annotated[list[str] | None, Query()] = None) -> list[dict]:
    return data.batches(cache, kind or data.KINDS)


# ---------------------------------------------------------------------------
# Phân tích
# ---------------------------------------------------------------------------


@app.get("/api/attack/asr")
def attack_asr(
    by: str = "channel,technique",
    batch: Batches = None,
    target: str | None = None,
    preset: str | None = None,
    goal: str | None = None,
    channel: str | None = None,
    kind: Kinds = None,
) -> dict:
    cols = [c for c in by.split(",") if c]
    allowed = {"channel", "technique", "goal", "target_id", "preset", "carrier_task_id"}
    if not cols or not set(cols) <= allowed:
        raise HTTPException(400, f"by chỉ nhận {sorted(allowed)}")
    runs = scoped(batch, kind, target_id=target, preset=preset, goal=goal, channel=channel)
    return {"by": cols, "rows": data.asr(runs, cols)}


@app.get("/api/defense/points")
def defense_points(batch: Batches = None, kind: Kinds = None, by: str = "target_id") -> dict:
    if by not in {"target_id", "goal", "channel"}:
        raise HTTPException(400, "by chỉ nhận target_id · goal · channel")
    return {"by": by, "points": data.defense_points(scoped(batch, kind), by)}


@app.get("/api/defense/presets")
def defense_presets() -> list[dict]:
    return data.presets()


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


@app.get("/api/runs")
def runs(
    batch: Batches = None,
    kind: Kinds = None,
    run_kind: str | None = None,
    outcome: str | None = None,
    target: str | None = None,
    preset: str | None = None,
    q: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    df = data.select(cache.runs(), batches=batch, kinds=kind or data.KINDS, run_kind=run_kind,
                     outcome=outcome, target_id=target, preset=preset)
    return data.run_list(df, q=q, limit=limit, offset=offset)


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str) -> dict:
    out = data.run_detail(cache, run_id)
    if out is None:
        raise HTTPException(404, "không có run này")
    return out


# ---------------------------------------------------------------------------
# Cấu hình · demo
# ---------------------------------------------------------------------------


@app.get("/api/config")
def config() -> dict:
    return data.config_summary()


@app.get("/api/demo/scenarios")
def scenarios() -> list[dict]:
    return data.scenarios()


class DemoRequest(BaseModel):
    scenario: str
    target: str = Field(pattern=r"^A[123]$")
    presets: list[str] = Field(min_length=1, max_length=7)
    prompt_variant: str | None = None


@app.post("/api/demo/jobs", status_code=202)
def start_demo(req: DemoRequest) -> dict:
    if not live():
        raise HTTPException(403, "demo trực tiếp chỉ mở khi chạy `make console` (DEMO_LIVE=1)")
    known = {p["name"] for p in data.presets()} | {"off"}
    if not set(req.presets) <= known:
        raise HTTPException(400, f"preset lạ: {sorted(set(req.presets) - known)}")
    _, variants = data.demo.prompt_variants()
    if req.prompt_variant and req.prompt_variant not in variants:
        raise HTTPException(400, f"biến thể prompt lạ: {req.prompt_variant}")
    try:
        job = jobs.start(req.scenario, req.target, req.presets, req.prompt_variant)
    except KeyError as e:
        raise HTTPException(404, "không có kịch bản này") from e
    except BusyError as e:
        raise HTTPException(409, f"đang có lượt demo chạy: {e}") from e
    return job.public()


@app.get("/api/demo/jobs/{job_id}")
def demo_job(job_id: str) -> dict:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "không có lượt này")
    return job.public()


@app.get("/api/demo/active")
def demo_active() -> dict | None:
    job = jobs.active()
    return job.public() if job else None


# ---------------------------------------------------------------------------
# Giao diện web (bản build)
# ---------------------------------------------------------------------------

if (WEB_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404)
    index = WEB_DIST / "index.html"
    if not index.is_file():
        return JSONResponse(
            {"detail": "chưa build giao diện — chạy `make console-build`"}, status_code=503
        )
    candidate = (WEB_DIST / path).resolve()
    if path and candidate.is_file() and Path(WEB_DIST.resolve()) in candidate.parents:
        return FileResponse(candidate)
    return FileResponse(index)
