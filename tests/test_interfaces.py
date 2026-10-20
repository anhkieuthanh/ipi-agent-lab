"""Hợp đồng năm tầng và hook phòng thủ (STT-17) phải khớp config và các module đã có.

DoD (`docs/06. Track/Lộ trình triển khai code.md`, giai đoạn 1): import được, mỗi hook nêu rõ
gọi ở giai đoạn nào. Thêm vào đó: `src/interfaces.py` không được lệch `config/defenses.yaml`
(`pipeline_order`, nguồn của D1/D2) và trace schema (kênh) — một khái niệm, một nguồn.
"""

import json
import re
from pathlib import Path

import pytest
import yaml
from sqlalchemy import text

import interfaces as itf
from interfaces import (
    HOOK_SPECS,
    SOURCE_CHANNEL,
    SOURCES,
    Decision,
    DefenseHit,
    HookStage,
    NoDefense,
    SessionState,
    ToolSpec,
    source_for_tool,
)
from obs.trace import CHANNELS, TraceRecorder

ROOT = Path(__file__).resolve().parents[1]
DEFENSES = yaml.safe_load((ROOT / "config" / "defenses.yaml").read_text(encoding="utf-8"))
CARRIER = json.loads((ROOT / "data" / "carrier_tasks.json").read_text(encoding="utf-8"))


def _pipeline_order() -> list[tuple[str, set[str], list[str]]]:
    """(tên stage, tập kênh ghi trong ngoặc, danh sách khối phòng thủ) theo thứ tự trong yaml."""
    rows = []
    for item in DEFENSES["pipeline_order"]:
        name, _, annotation = item["stage"].partition(" ")
        rows.append((name, set(re.findall(r"\bK\d[ab]?\b", annotation)), item["apply"]))
    return rows


def test_moi_ten_trong_all_ton_tai():
    for name in itf.__all__:
        assert hasattr(itf, name), name


def test_hook_trung_thu_tu_pipeline_order():
    assert [s.value for s in HookStage] == [name for name, _, _ in _pipeline_order()]


def test_moi_hook_co_dac_ta_giai_doan_va_ben_goi():
    assert set(HOOK_SPECS) == set(HookStage)
    for stage, spec in HOOK_SPECS.items():
        assert spec.phase[0] in "①②③④⑤", stage
        assert spec.caller and spec.description, stage
        assert (spec.kind == "transform") == bool(spec.sources), stage


def test_nguon_cua_hook_khop_kenh_ghi_trong_yaml():
    for name, channels, _ in _pipeline_order():
        stage = HookStage(name)
        if stage.spec.kind == "gate":
            assert not channels, name
        else:
            assert {SOURCE_CHANNEL[s] for s in stage.spec.sources} == channels, name


def test_co_che_cua_hook_khop_yaml():
    blocks = DEFENSES["defenses"]
    for name, _, apply in _pipeline_order():
        for block in apply:
            assert block in blocks, f"{name}: khối '{block}' không có trong defenses"
        letters = sorted(block.split("_")[0].upper() for block in apply)
        assert letters == sorted(HOOK_SPECS[HookStage(name)].defenses.split(", ")), name


def test_nguon_khop_d1_d2():
    d1 = DEFENSES["defenses"]["d1_spotlighting"]["params"]["wrap_sources"]
    d2 = DEFENSES["defenses"]["d2_input_sanitizer"]["apply_to_sources"]
    assert set(d1) == set(SOURCES)
    assert set(d2) <= set(SOURCES)


def test_kenh_khop_trace_schema():
    assert sorted(SOURCE_CHANNEL.values()) == sorted(CHANNELS)
    assert set(SOURCE_CHANNEL) == set(SOURCES)


def test_ket_qua_search_kb_la_k1_con_lai_la_k2b():
    assert itf.KB_TOOL in CARRIER["agent_tools"]
    for tool in CARRIER["agent_tools"]:
        expected = "kb_chunk" if tool == "search_kb" else "tool_result"
        assert source_for_tool(tool) == expected
    # Chunk K1 đi qua KB_RETRIEVAL, không qua TOOL_RESULT — D2 không chạy hai lần.
    assert HookStage.KB_RETRIEVAL.accepts(source_for_tool("search_kb"))
    assert not HookStage.TOOL_RESULT.accepts(source_for_tool("search_kb"))


@pytest.mark.parametrize("tool", sorted(CARRIER["agent_tools"]))
def test_toolspec_nhan_kind_cua_bo_do(tool):
    spec = CARRIER["agent_tools"][tool]
    ts = ToolSpec(
        name=tool,
        description="mô tả",
        input_schema={"type": "object", "properties": {}},
        kind=spec["kind"],
        side_effect=spec["side_effect"],
    )
    fn = ts.to_openai(description="mô tả đã bọc")["function"]
    assert fn["name"] == tool and fn["description"] == "mô tả đã bọc"


def test_toolspec_tu_choi_kind_la():
    with pytest.raises(ValueError):
        ToolSpec(name="x", description="", input_schema={}, kind="write", side_effect=True)


def test_decision_tu_choi_action_la():
    # `confirm` không đi tới lõi agent: DefenseLayer đã quy nó về block theo config.
    for action in ("deny", "confirm"):
        with pytest.raises(ValueError):
            Decision(action=action)
    assert Decision().allowed and not Decision(action="block").allowed


def test_d3_confirm_quy_ve_chan_trong_config():
    r4 = DEFENSES["defenses"]["d3_tool_policy"]["rules"]["R4_require_confirmation"]
    assert r4["automated_resolution"] == "block"


def test_hien_thuc_san_co_thoa_protocol():
    assert issubclass(TraceRecorder, itf.Recorder)
    assert isinstance(NoDefense(), itf.DefenseLayer)
    # LLMClient cần biến môi trường để khởi tạo; kiểm ở mức lớp.
    from agent.llm_client import LLMClient

    assert issubclass(LLMClient, itf.ChatModel)


def test_nodefense_di_thang_o_moi_hook():
    from agent.llm_client import ToolCall

    nd = NoDefense()
    session = SessionState(run_id="r1", task_type="LOOKUP")
    call = ToolCall(id="c1", name="search_kb", arguments={"query": "x"}, arguments_raw="{}")
    for stage in HookStage:
        if stage.spec.kind == "transform":
            for source in stage.spec.sources:
                out = nd.transform(stage, "nội dung", source=source, session=session)
                assert out.text == "nội dung" and out.hits == ()
            with pytest.raises(ValueError):
                nd.gate(stage, call, session=session)
        else:
            assert nd.gate(stage, call, session=session).allowed
            with pytest.raises(ValueError):
                nd.transform(stage, "x", source="tool_result", session=session)


def test_nodefense_tu_choi_nguon_sai_hook():
    with pytest.raises(ValueError):
        NoDefense().transform(
            HookStage.KB_RETRIEVAL, "x", source="tool_result", session=SessionState(run_id="r")
        )


def test_defense_hit_ghi_duoc_vao_trace():
    from obs.trace import RunMeta, open_store

    hit = DefenseHit(
        defense="d3_tool_policy",
        stage=HookStage.PRE_TOOL_EXECUTION.value,
        action="block",
        rule="R1_task_type_allowlist",
        detail="send_email ngoài allowlist LOOKUP",
    )
    engine = open_store()
    meta = RunMeta(
        run_kind="benign",
        target_id="A3",
        model_id="glm-5.3-flash",
        batch_id="test",
        harness_version="core-a@test",
        env_hash="env@test",
    )
    with TraceRecorder(engine, meta) as rec:
        rec.step(kind="defense", tool_name="send_email", defense_hits=[hit.to_json()])
        rec.finish(outcome="fail")
    with engine.connect() as conn:
        stored = conn.execute(text("SELECT defense_hits FROM steps")).scalar_one()
    assert json.loads(stored) == [hit.to_json()]
