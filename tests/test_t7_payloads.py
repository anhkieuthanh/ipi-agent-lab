"""Kiểm corpus T7 kích hoạt trễ/có điều kiện (STT-50): hợp lệ, phủ cả hai loại trigger
(tool_result_match + min_step), base_frame ∈ {T1,T2,T5}, phủ 3 goal, dựng được trên 3 kênh.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from attack.payloads.render import render_for_channel
from attack.payloads.schema import BASE_FRAMES, load_payloads

ROOT = Path(__file__).resolve().parents[1]
T7_PATH = ROOT / "src" / "attack" / "payloads" / "t7_deferred.yaml"
GOALS = ("G1", "G2", "G3")


@pytest.fixture(scope="module")
def t7():
    return yaml.safe_load(T7_PATH.read_text(encoding="utf-8"))


def test_file_ton_tai_va_hop_le():
    payloads, report = load_payloads(T7_PATH)
    assert report.all_ok, report.errors_by_id
    assert payloads and all(p["technique"]["code"] == "T7" for p in payloads)


def test_ca_hai_loai_trigger(t7):
    kinds = {p["trigger"]["kind"] for p in t7}
    assert kinds == {"tool_result_match", "min_step"}
    for p in t7:
        tr = p["trigger"]
        if tr["kind"] == "tool_result_match":
            assert tr.get("tool") and tr.get("pattern")
        else:
            assert tr["step_min"] >= 3


def test_base_frame_va_khong_pair(t7):
    for p in t7:
        assert p["base_frame"] in BASE_FRAMES
        assert "pair_id" not in p
        assert "vi_transform" not in p and "fragments" not in p


def test_phu_du_ba_goal(t7):
    assert {p["goal"] for p in t7} == set(GOALS)


def test_dung_duoc_ba_kenh(t7):
    for p in t7:
        assert p["channels"] == ["K1", "K2a", "K2b"]
        for ch in p["channels"]:
            render_for_channel(p, ch)
