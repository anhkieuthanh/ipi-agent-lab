"""Kiểm corpus biến thể giọng thẩm quyền của T1 (STT-49): hợp lệ, variant authority_letter,
vi-only (không pair_id/bản en), phủ 3 goal, channel_override K2a/K2b chứa nguyên văn chỉ thị.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from attack.payloads.render import instruction_of, render_for_channel
from attack.payloads.schema import load_payloads

ROOT = Path(__file__).resolve().parents[1]
T1A_PATH = ROOT / "src" / "attack" / "payloads" / "t1_authority.yaml"
GOALS = ("G1", "G2", "G3")


@pytest.fixture(scope="module")
def t1a():
    return yaml.safe_load(T1A_PATH.read_text(encoding="utf-8"))


def test_file_ton_tai_va_hop_le():
    payloads, report = load_payloads(T1A_PATH)
    assert report.all_ok, report.errors_by_id
    assert payloads and all(p["technique"]["code"] == "T1" for p in payloads)


def test_variant_va_vi_only(t1a):
    for p in t1a:
        assert p["technique"]["variant"] == "authority_letter"
        assert p["lang"] == "vi"
        assert "pair_id" not in p  # vi-only: không dựng cặp vi/en


def test_phu_du_ba_goal(t1a):
    assert {p["goal"] for p in t1a} == set(GOALS)


def test_channel_override_chua_nguyen_van_chi_thi(t1a):
    # K2a/K2b có giới hạn 400 ký tự ⇒ dùng channel_override rút gọn, phải chứa nguyên văn chỉ thị.
    for p in t1a:
        co = p.get("channel_override") or {}
        assert set(co) == {"K2a", "K2b"}
        for ch in ("K2a", "K2b"):
            text = render_for_channel(p, ch)
            assert instruction_of(p) in text
            assert "{INSTRUCTION}" not in text


def test_template_khong_ten_tool_lab(t1a):
    lab_tools = ("search_kb", "query_customer_db", "http_request", "send_email", "create_ticket")
    for p in t1a:
        tpl = p["technique"]["template"]
        assert tpl.count("{INSTRUCTION}") == 1
        assert not any(t in tpl for t in lab_tools)
