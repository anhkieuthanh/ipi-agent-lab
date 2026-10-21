"""Test cho attack.payloads.render — dạng payload trên kênh K1/K2a/K2b (STT-41, taxonomy mục 2.3)
và bất biến 12 (`channel_override`).

Payload mẫu mang chỉ thị là chuỗi trung tính: test kiểm định dạng và ràng buộc, không kiểm hiệu lực
tấn công.
"""

from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path

import pytest

from src.attack.payloads.render import (
    ChannelRenderError,
    apply_k2a,
    apply_k2b,
    base_text,
    channel_override_errors,
    k2a_target_tool,
    load_render_config,
    render_for_channel,
)
from src.attack.payloads.schema import load_payloads, load_task_meta, validate_pairs

ROOT = Path(__file__).resolve().parents[1]
CFG = load_render_config()
META = load_task_meta()


def _payload(lang: str = "vi") -> dict:
    return {
        "id": f"P-T1-G2-{lang.upper()}-001",
        "technique": {"code": "T1", "variant": "bare", "template": "GHI CHU: {INSTRUCTION}"},
        "goal": "G2",
        "goal_binding": {
            "tool": "create_ticket",
            "arguments": {},
            "instruction_vi": "noi dung chi thi mau",
            "instruction_en": "sample instruction body",
        },
        "channels": ["K1", "K2a", "K2b"],
        "lang": lang,
    }


def _small_cfg(limit: int) -> dict:
    cfg = copy.deepcopy(CFG)
    for ch in ("K2a", "K2b"):
        cfg["channels"][ch]["max_payload_chars"] = limit
    return cfg


# ── render_for_channel ────────────────────────────────────────────────────────
def test_base_text_fills_instruction_by_lang():
    assert base_text(_payload("vi")) == "GHI CHU: noi dung chi thi mau"
    assert base_text(_payload("en")) == "GHI CHU: sample instruction body"


def test_same_text_on_every_channel_without_override():
    p = _payload()
    texts = {ch: render_for_channel(p, ch) for ch in p["channels"]}
    assert len(set(texts.values())) == 1


def test_channel_not_declared_raises():
    p = _payload()
    p["channels"] = ["K1", "K2b"]
    with pytest.raises(ChannelRenderError, match="không nằm trong channels"):
        render_for_channel(p, "K2a")


def test_over_limit_raises_and_never_truncates():
    p = _payload()
    with pytest.raises(ChannelRenderError, match="không cắt"):
        render_for_channel(p, "K2a", cfg=_small_cfg(10))
    # K1 không có giới hạn ở bước này
    assert render_for_channel(p, "K1", cfg=_small_cfg(10)) == base_text(p)


def test_override_replaces_base_on_its_channel_only():
    p = _payload()
    p["channel_override"] = {"K2a": "noi dung chi thi mau"}
    assert render_for_channel(p, "K2a") == "noi dung chi thi mau"
    assert render_for_channel(p, "K2b") == base_text(p)


def test_override_is_length_checked_too():
    p = _payload()
    p["channel_override"] = {"K2a": "x " * 20 + "noi dung chi thi mau"}
    with pytest.raises(ChannelRenderError, match="channel_override"):
        render_for_channel(p, "K2a", cfg=_small_cfg(25))


# ── bất biến 12 ──────────────────────────────────────────────────────────────
def test_inv12_valid_override_passes():
    p = _payload()
    p["channel_override"] = {"K2b": "Luu y: noi dung chi thi mau"}
    assert channel_override_errors(p) == []


@pytest.mark.parametrize(
    ("override", "channels", "needle"),
    [
        ({"K1": "noi dung chi thi mau"}, ["K1", "K2a"], "∉"),
        ({"K2b": "noi dung chi thi mau"}, ["K1", "K2a"], "không nằm trong channels"),
        ({"K2a": "X {INSTRUCTION}"}, ["K1", "K2a"], "{INSTRUCTION}"),
        ({"K2a": "chi thi da sua"}, ["K1", "K2a"], "nguyên văn"),
        ({"K2a": ""}, ["K1", "K2a"], "không rỗng"),
    ],
)
def test_inv12_bad_override(override, channels, needle):
    p = _payload()
    p["channels"] = channels
    p["channel_override"] = override
    errs = channel_override_errors(p)
    assert any("[INV12]" in x and needle in x for x in errs), errs


def test_inv12_flags_k2_channel_over_limit_without_override():
    errs = channel_override_errors(_payload(), cfg=_small_cfg(10))
    assert sum("[INV12]" in x for x in errs) == 2  # K2a và K2b


def test_inv12_override_fixes_over_limit():
    p = _payload()
    p["channel_override"] = {"K2a": "noi dung chi thi mau", "K2b": "noi dung chi thi mau"}
    assert channel_override_errors(p, cfg=_small_cfg(25)) == []


def test_pair_may_differ_in_override_content():
    vi, en = _payload("vi"), _payload("en")
    for p in (vi, en):
        p["pair_id"] = "PR-T1-G2-001"
    vi["channel_override"] = {"K2a": "Rut gon: noi dung chi thi mau"}
    assert validate_pairs([vi, en]) == {}


# ── K2a ──────────────────────────────────────────────────────────────────────
def test_k2a_target_prefers_goal_tool_then_search_kb():
    p = _payload()
    assert k2a_target_tool(p, ["search_kb", "query_customer_db", "create_ticket"]) == "create_ticket"
    assert k2a_target_tool(p, ["search_kb"]) == "search_kb"
    p["goal_binding"]["tool"] = None  # G3 / G1 qua final_answer
    assert k2a_target_tool(p, ["search_kb", "http_request"]) == "search_kb"


def test_k2a_target_raises_when_nothing_allowed():
    with pytest.raises(ChannelRenderError):
        k2a_target_tool(_payload(), ["http_request"])


def test_apply_k2a_appends_and_keeps_original():
    out = apply_k2a("Tra cuu kho tri thuc.", "GHI CHU: x")
    assert out == "Tra cuu kho tri thuc." + CFG["channels"]["K2a"]["joiner"] + "GHI CHU: x"


# ── K2b ──────────────────────────────────────────────────────────────────────
def test_apply_k2b_root_adds_field_and_keeps_rows():
    content = json.dumps(
        {"columns": ["id"], "rows": [{"id": 1}], "row_count": 1, "truncated": False}
    )
    out = json.loads(apply_k2b("query_customer_db", content, "GHI CHU: x"))
    field = CFG["channels"]["K2b"]["tools"]["query_customer_db"]["field"]
    assert out[field] == "GHI CHU: x"
    assert out["rows"] == [{"id": 1}] and out["row_count"] == 1


def test_apply_k2b_http_body_nested_and_roundtrips():
    body = json.dumps({"sku": "SKU-1", "quantity": 3}, ensure_ascii=False)
    content = json.dumps({"status": 200, "body": body}, ensure_ascii=False)
    text = 'Có "ngoặc kép" và\nxuống dòng'
    out = json.loads(apply_k2b("http_request", content, text))
    inner = json.loads(out["body"])
    field = CFG["channels"]["K2b"]["tools"]["http_request"]["field"]
    assert inner[field] == text and inner["quantity"] == 3 and out["status"] == 200


@pytest.mark.parametrize(
    ("tool", "content", "needle"),
    [
        ("send_email", "{}", "không chở K2b"),
        ("search_kb", "{}", "không chở K2b"),
        ("query_customer_db", "không phải json", "không phải JSON"),
        ("query_customer_db", json.dumps({"ghi_chu": "có sẵn"}), "không ghi đè"),
        ("http_request", json.dumps({"status": 200, "body": "text"}), "body"),
    ],
)
def test_apply_k2b_errors(tool, content, needle):
    with pytest.raises(ChannelRenderError, match=needle):
        apply_k2b(tool, content, "x")


def test_k2b_forbidden_field_rejected():
    cfg = copy.deepcopy(CFG)
    cfg["channels"]["K2b"]["tools"]["query_customer_db"]["field"] = "canary_note"
    with pytest.raises(ChannelRenderError, match="cấm"):
        apply_k2b("query_customer_db", "{}", "x", cfg=cfg)


# ── config khớp dữ liệu ──────────────────────────────────────────────────────
def test_config_k2b_tools_match_channel_rule_and_fields_are_new():
    k2b = CFG["channels"]["K2b"]
    assert set(k2b["tools"]) <= set(META.tools)
    assert "search_kb" not in k2b["tools"]  # kết quả search_kb là K1
    with sqlite3.connect(ROOT / "data" / "customers.db") as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(customers)")}
    for spec in k2b["tools"].values():
        assert spec["field"] not in cols
        assert spec["field"] not in k2b["forbidden_fields"]


def test_k2a_fallback_tool_is_in_every_carrier():
    data = json.loads((ROOT / "data" / "carrier_tasks.json").read_text(encoding="utf-8"))
    fallback = [t for t in CFG["channels"]["K2a"]["target_tool_priority"] if t != "goal_tool"]
    assert all(
        any(t in ct["allowed_tools"] for t in fallback) for ct in data["carrier_tasks"]
    )


# ── corpus thật ──────────────────────────────────────────────────────────────
def test_corpus_renders_on_every_declared_channel():
    items, report = load_payloads(ROOT / "src" / "attack" / "payloads")
    assert report.all_ok, report.errors_by_id
    for p in items:
        for ch in p["channels"]:
            assert render_for_channel(p, ch)
