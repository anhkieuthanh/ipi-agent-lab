"""Kiểm corpus T8 đã sinh (STT-47): hợp lệ, phủ ô B1 T8, dựng được mọi kênh, giữ token mục tiêu."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from attack.payloads.render import render_for_channel
from attack.payloads.schema import load_payloads

ROOT = Path(__file__).resolve().parents[1]
T8_PATH = ROOT / "src" / "attack" / "payloads" / "t8_vietnamese.yaml"
B1_GOALS = ("G1", "G2", "G3")
B1_T8_CHANNELS = ("K1", "K2a", "K2b")


@pytest.fixture(scope="module")
def t8():
    return yaml.safe_load(T8_PATH.read_text(encoding="utf-8"))


def test_file_ton_tai_va_hop_le():
    payloads, report = load_payloads(T8_PATH)
    assert report.all_ok, report.errors_by_id
    assert payloads and all(p["technique"]["code"] == "T8" for p in payloads)


def test_moi_payload_khai_vi_transform_va_base_frame(t8):
    for p in t8:
        assert p["vi_transform"] and p["lang"] in ("vi", "mixed")
        assert p["base_frame"] in ("T1", "T2", "T3", "T5")
        assert "pair_id" not in p  # INV11: T8 không có bản en


def test_phu_moi_o_b1_t8(t8):
    for goal in B1_GOALS:
        for ch in B1_T8_CHANNELS:
            n = sum(1 for p in t8 if p["goal"] == goal and ch in p["channels"])
            assert n >= 1, f"ô T8 {ch}·{goal} không có payload"


def test_dung_duoc_moi_kenh_k2(t8):
    for p in t8:
        for ch in ("K2a", "K2b"):
            render_for_channel(p, ch)  # không ném ChannelRenderError


def test_giu_marker_run_id_cho_g3(t8):
    for p in t8:
        if p["goal"] == "G3":
            assert "{run_id}" in p["goal_binding"]["instruction_vi"]
            assert "{run_id}" in p["activation_check"]["marker_template"]


def test_khong_lo_canary_that(t8):
    blob = yaml.safe_dump(t8, allow_unicode=True)
    import re

    for hit in re.findall(r"CANARY_(?:SYSPROMPT|DB)_[0-9a-f]+", blob):
        pytest.fail(f"lộ canary thật: {hit}")


def test_sinh_tat_dinh_khop_file(t8):
    # Generator chạy lại cho ra y hệt file đã ghi — bộ đo tái lập được.
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    import gen_t8_payloads

    assert gen_t8_payloads.generate() == t8
