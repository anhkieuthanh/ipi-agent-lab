"""Chạy tiếp lô của `run_matrix.py`: từ chối khi kế hoạch đổi giữa hai phiên (VT-20)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from attack.runner import AttackRunSpec

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def rm():
    spec = importlib.util.spec_from_file_location("run_matrix", ROOT / "scripts" / "run_matrix.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _spec(payload: str, repeat: int = 0) -> AttackRunSpec:
    return AttackRunSpec(repeat, "A2", "K2a", "T3", "G2", "blind", "{}", "CT-04", payload)


def test_plan_sha_khong_phu_thuoc_thu_tu(rm):
    a, b = _spec("P-1"), _spec("P-2")
    assert rm._plan_sha([a, b]) == rm._plan_sha([b, a])
    assert rm._plan_sha([a]) != rm._plan_sha([b])


def test_khop_ke_hoach_thi_cho_chay_tiep(rm, tmp_path):
    plan = [_spec("P-1"), _spec("P-2")]
    sha = rm._plan_sha(plan)
    (tmp_path / "manifest.json").write_text(json.dumps([{"plan_sha256": sha}]), "utf-8")
    assert rm._plan_drift(tmp_path, sha, {plan[0]}, plan) is None


def test_run_da_co_ngoai_ke_hoach_thi_tu_choi(rm, tmp_path):
    plan = [_spec("P-1")]
    reason = rm._plan_drift(tmp_path, rm._plan_sha(plan), {_spec("P-cu")}, plan)
    assert reason and "không thuộc kế hoạch" in reason


def test_plan_sha_phien_truoc_lech_thi_tu_choi(rm, tmp_path):
    plan = [_spec("P-1")]
    (tmp_path / "manifest.json").write_text(json.dumps([{"plan_sha256": "khac"}]), "utf-8")
    reason = rm._plan_drift(tmp_path, rm._plan_sha(plan), set(), plan)
    assert reason and "plan_sha256" in reason


def test_manifest_cu_khong_co_plan_sha_thi_bo_qua(rm, tmp_path):
    plan = [_spec("P-1")]
    (tmp_path / "manifest.json").write_text(json.dumps([{"batch_id": "x"}]), "utf-8")
    assert rm._plan_drift(tmp_path, rm._plan_sha(plan), set(), plan) is None
