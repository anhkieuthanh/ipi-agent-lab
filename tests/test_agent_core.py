"""Lõi agent Core-A (STT-26): vòng lặp, thứ tự hook, logic dừng, ghi trace.

Không gọi mạng: model, tầng công cụ và phòng thủ đều là bản giả theo `Protocol` ở
`src/interfaces.py`. Mỗi test kiểm một điều kiện mà runner và scorer sau này dựa vào.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from sqlmodel import Session, select

from agent.core import CoreA, load_core_params
from agent.llm_client import LLMResult, ToolCall
from interfaces import (
    AgentCore,
    Decision,
    DefenseHit,
    HookStage,
    NoDefense,
    SessionState,
    ToolResult,
    ToolSpec,
    Transformed,
    check_stage,
)
from obs.trace import Run, RunMeta, Step, TraceRecorder, open_store

# ---------------------------------------------------------------------------
# Bản giả
# ---------------------------------------------------------------------------


def _result(text: str | None = None, calls: list[ToolCall] | None = None, **kw: Any) -> LLMResult:
    return LLMResult(
        text=text,
        tool_calls=calls or [],
        tokens_in=kw.get("tokens_in", 10),
        tokens_out=kw.get("tokens_out", 5),
        latency_ms=1,
        target_id="A2",
        model="fake",
        response_model=kw.get("response_model", "fake-snap"),
        attempts=1,
        finish_reason=kw.get("finish_reason", "tool_calls" if calls else "stop"),
    )


def _call(name: str, args: dict[str, Any] | None = None, cid: str = "c1") -> ToolCall:
    args = args or {}
    return ToolCall(id=cid, name=name, arguments=args, arguments_raw=json.dumps(args))


class FakeModel:
    """Trả lần lượt các `LLMResult` đã kịch bản; ghi lại messages/tools mỗi lần gọi."""

    def __init__(self, script: list[LLMResult]) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages, tools=None, **kwargs):
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools, **kwargs})
        if not self.script:
            raise AssertionError("model bị gọi quá số lượt kịch bản")
        return self.script.pop(0)


def _spec(name: str, kind: str = "read") -> ToolSpec:
    return ToolSpec(
        name=name,
        description=f"mô tả {name}",
        input_schema={"type": "object", "properties": {}},
        kind=kind,
        side_effect=kind == "outbound",
    )


class FakeTools:
    def __init__(self, names: tuple[str, ...] = ("search_kb", "query_customer_db", "send_email")):
        self.specs = [_spec(n, "outbound" if n == "send_email" else "read") for n in names]
        self.executed: list[ToolCall] = []
        self.list_calls = 0

    def list_tools(self):
        self.list_calls += 1
        return list(self.specs)

    def call_tool(self, call):
        self.executed.append(call)
        return ToolResult(call_id=call.id, name=call.name, content=f"kết quả {call.name}")


class SpyDefense(NoDefense):
    """Ghi thứ tự hook; tùy chọn chặn một tool ở một stage, đánh dấu văn bản đi qua."""

    def __init__(self, block: tuple[HookStage, str] | None = None, mark: bool = False) -> None:
        self.events: list[tuple[str, str]] = []
        self.block = block
        self.mark = mark

    def transform(self, stage, text, *, source, session):
        check_stage(stage, "transform", source)
        self.events.append((stage.value, source))
        if not self.mark:
            return Transformed(text=text)
        hit = DefenseHit(defense="spy", stage=stage.value, action="transform")
        return Transformed(text=f"<{stage.value}>{text}</{stage.value}>", hits=(hit,))

    def gate(self, stage, call, *, session):
        check_stage(stage, "gate")
        self.events.append((stage.value, call.name))
        if self.block == (stage, call.name):
            hit = DefenseHit(defense="spy", stage=stage.value, action="block", rule="R_test")
            return Decision(action="block", reason="bị chặn để thử", hits=(hit,))
        return Decision()


class ListRecorder:
    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []

    def step(self, *, kind, **fields):
        self.steps.append({"kind": kind, **fields})

    def finish(self, **result):  # pragma: no cover - lõi agent không được gọi
        raise AssertionError("lõi agent không được gọi finish()")


def _core(model, tools=None, defense=None, max_steps=8, **kw) -> CoreA:
    return CoreA(
        model=model,
        tools=tools or FakeTools(),
        defense=defense or NoDefense(),
        system_prompt="Bạn là trợ lý nội bộ.",
        max_steps=max_steps,
        max_tokens=kw.get("max_tokens", 4096),
    )


# ---------------------------------------------------------------------------
# Hợp đồng và tham số
# ---------------------------------------------------------------------------


def test_thoa_protocol_agentcore():
    assert isinstance(_core(FakeModel([])), AgentCore)


def test_tham_so_lay_tu_experiment_yaml():
    params = load_core_params()
    assert params == {"max_steps": 8, "max_tokens": 4096}


@pytest.mark.parametrize("bad", [0, -1, None])
def test_tu_choi_max_steps_khong_hop_le(bad):
    with pytest.raises(ValueError):
        _core(FakeModel([]), max_steps=bad)


# ---------------------------------------------------------------------------
# Logic dừng
# ---------------------------------------------------------------------------


def test_tra_loi_ngay_khong_goi_tool():
    model = FakeModel([_result("Xin chào")])
    rec = ListRecorder()
    out = _core(model).run("hỏi", session=SessionState(run_id="r"), recorder=rec)
    assert (out.final_answer, out.stop_reason, out.n_steps) == ("Xin chào", "final_answer", 1)
    assert [s["kind"] for s in rec.steps] == ["llm"]
    assert model.calls[0]["max_tokens"] == 4096
    first = model.calls[0]["messages"]
    assert first[0] == {"role": "system", "content": "Bạn là trợ lý nội bộ."}
    assert first[1] == {"role": "user", "content": "hỏi"}


def test_mot_vong_tool_roi_tra_loi():
    model = FakeModel([_result(calls=[_call("search_kb", {"query": "x"})]), _result("Đáp")])
    tools = FakeTools()
    out = _core(model, tools).run("hỏi", session=SessionState(run_id="r"), recorder=ListRecorder())
    assert out.stop_reason == "final_answer" and out.final_answer == "Đáp"
    assert out.n_steps == 2
    assert [c.name for c in tools.executed] == ["search_kb"]
    msgs = model.calls[1]["messages"]
    assert msgs[2]["role"] == "assistant" and msgs[2]["tool_calls"][0]["id"] == "c1"
    assert msgs[3] == {"role": "tool", "tool_call_id": "c1", "content": "kết quả search_kb"}


def test_dung_o_max_steps():
    loop = [_result(calls=[_call("search_kb", cid=f"c{i}")]) for i in range(3)]
    model = FakeModel(loop)
    tools = FakeTools()
    out = _core(model, tools, max_steps=3).run(
        "hỏi", session=SessionState(run_id="r"), recorder=ListRecorder()
    )
    assert out.stop_reason == "max_steps"
    assert out.final_answer is None
    assert out.n_steps == 3 and len(model.calls) == 3
    assert len(tools.executed) == 3  # tool-call của bước cuối vẫn chạy, chỉ không gọi model nữa


def test_tool_call_sai_json_dung_parse_error_khong_thuc_thi():
    bad = ToolCall(
        id="c1", name="send_email", arguments=None, arguments_raw="{oops", parse_error=True
    )
    ok = _call("search_kb", cid="c2")
    model = FakeModel([_result(calls=[ok, bad])])
    tools = FakeTools()
    defense = SpyDefense()
    rec = ListRecorder()
    out = _core(model, tools, defense).run("hỏi", session=SessionState(run_id="r"), recorder=rec)
    assert out.stop_reason == "parse_error"
    assert out.final_answer is None
    assert tools.executed == []  # không chạy nửa lượt
    assert not [e for e in defense.events if e[0] in ("pre_tool_execution", "pre_egress")]
    assert [s["kind"] for s in rec.steps] == ["llm"]


def test_cau_tra_loi_rong_van_la_final_answer():
    model = FakeModel([_result(None, finish_reason="length")])
    out = _core(model).run("hỏi", session=SessionState(run_id="r"), recorder=ListRecorder())
    assert out.stop_reason == "final_answer" and out.final_answer is None


# ---------------------------------------------------------------------------
# Hook
# ---------------------------------------------------------------------------


def test_thu_tu_hook_tren_mot_tool_call():
    model = FakeModel([_result(calls=[_call("query_customer_db")]), _result("xong")])
    defense = SpyDefense()
    _core(model, defense=defense).run(
        "hỏi", session=SessionState(run_id="r"), recorder=ListRecorder()
    )
    # Ba mô tả tool qua CONTEXT_ASSEMBLY trước lời gọi model đầu tiên.
    assert defense.events[:3] == [("context_assembly", "tool_description")] * 3
    assert defense.events[3:] == [
        ("pre_tool_execution", "query_customer_db"),
        ("pre_egress", "query_customer_db"),  # gọi cho mọi tool; DefenseLayer tự bỏ qua
        ("tool_result", "tool_result"),
        ("context_assembly", "tool_result"),
    ]


def test_search_kb_di_qua_kb_retrieval():
    model = FakeModel([_result(calls=[_call("search_kb")]), _result("xong")])
    defense = SpyDefense()
    _core(model, defense=defense).run(
        "hỏi", session=SessionState(run_id="r"), recorder=ListRecorder()
    )
    assert defense.events[-2:] == [("kb_retrieval", "kb_chunk"), ("context_assembly", "kb_chunk")]


def test_van_ban_da_bien_doi_di_vao_context_va_tools():
    model = FakeModel([_result(calls=[_call("search_kb")]), _result("xong")])
    rec = ListRecorder()
    _core(model, defense=SpyDefense(mark=True)).run(
        "hỏi", session=SessionState(run_id="r"), recorder=rec
    )
    desc = model.calls[0]["tools"][0]["function"]["description"]
    assert desc == "<context_assembly>mô tả search_kb</context_assembly>"
    tool_msg = model.calls[1]["messages"][3]["content"]
    assert tool_msg == (
        "<context_assembly><kb_retrieval>kết quả search_kb</kb_retrieval></context_assembly>"
    )
    # Hit của mô tả tool gắn vào bước llm đầu; hit của kết quả gắn vào bước tool.
    llm0, tool = rec.steps[0], rec.steps[1]
    assert {h["stage"] for h in llm0["defense_hits"]} == {"context_assembly"}
    assert len(llm0["defense_hits"]) == 3
    assert [h["stage"] for h in tool["defense_hits"]] == ["kb_retrieval", "context_assembly"]
    # Trace giữ kết quả THÔ (bằng chứng), không phải bản đã bọc.
    assert tool["tool_result"] == "kết quả search_kb"


@pytest.mark.parametrize("stage", [HookStage.PRE_TOOL_EXECUTION, HookStage.PRE_EGRESS])
def test_gate_chan_khong_thuc_thi_va_bao_model(stage):
    model = FakeModel([_result(calls=[_call("send_email", {"to": "x@y.z"})]), _result("thôi")])
    tools = FakeTools()
    defense = SpyDefense(block=(stage, "send_email"))
    rec = ListRecorder()
    session = SessionState(run_id="r", task_type="LOOKUP")
    out = _core(model, tools, defense).run("hỏi", session=session, recorder=rec)
    assert tools.executed == []
    assert out.defense_blocked is True
    assert out.stop_reason == "final_answer"
    gates = [e for e in defense.events if e[0] in ("pre_tool_execution", "pre_egress")]
    if stage is HookStage.PRE_TOOL_EXECUTION:
        assert gates == [("pre_tool_execution", "send_email")]  # D3 chặn thì D4 không chạy
    # Kết quả lỗi do harness sinh: không qua hook transform.
    assert not [
        e
        for e in defense.events
        if e[0] in ("tool_result", "context_assembly") and e[1] != "tool_description"
    ]
    msg = model.calls[1]["messages"][3]
    assert msg["role"] == "tool" and msg["tool_call_id"] == "c1" and "bị chặn" in msg["content"]
    kinds = [s["kind"] for s in rec.steps]
    assert kinds == ["llm", "defense", "llm"]
    d = rec.steps[1]
    assert d["tool_name"] == "send_email" and d["tool_args"] == {"to": "x@y.z"}
    assert d["defense_hits"][0]["action"] == "block"
    executed = out.tool_calls[0]
    assert executed.result is not None and executed.result.is_error
    assert not executed.decision.allowed


def test_lich_su_phien_cap_nhat_truoc_lan_gate_sau():
    """D3 (R2/R3) đọc `session.history`: tool-call trước phải có mặt khi gate tool-call sau."""
    seen: list[list[str]] = []

    class HistorySpy(NoDefense):
        def gate(self, stage, call, *, session):
            if stage is HookStage.PRE_TOOL_EXECUTION:
                seen.append([ec.call.name for ec in session.history])
            return super().gate(stage, call, session=session)

    calls = [_call("query_customer_db", cid="a"), _call("send_email", cid="b")]
    model = FakeModel([_result(calls=calls), _result("xong")])
    session = SessionState(run_id="r")
    out = _core(model, defense=HistorySpy()).run("hỏi", session=session, recorder=ListRecorder())
    assert seen == [[], ["query_customer_db"]]
    assert [ec.call.name for ec in session.history] == ["query_customer_db", "send_email"]
    assert out.tool_calls == session.history


def test_step_idx_tang_theo_luot_model():
    seen: list[int] = []

    class IdxSpy(NoDefense):
        def gate(self, stage, call, *, session):
            seen.append(session.step_idx)
            return super().gate(stage, call, session=session)

    model = FakeModel(
        [
            _result(calls=[_call("search_kb", cid="a")]),
            _result(calls=[_call("search_kb", cid="b")]),
            _result("xong"),
        ]
    )
    _core(model, defense=IdxSpy()).run(
        "hỏi", session=SessionState(run_id="r"), recorder=ListRecorder()
    )
    assert seen == [0, 0, 1, 1]


def test_danh_sach_tool_lay_lai_moi_run():
    tools = FakeTools()
    core = _core(FakeModel([_result("a"), _result("b")]), tools)
    core.run("1", session=SessionState(run_id="r1"), recorder=ListRecorder())
    tools.specs[0] = ToolSpec(
        name="search_kb",
        description="mô tả đã bị đầu độc",
        input_schema={},
        kind="read",
        side_effect=False,
    )
    core.run("2", session=SessionState(run_id="r2"), recorder=ListRecorder())
    assert tools.list_calls == 2
    assert core.model.calls[1]["tools"][0]["function"]["description"] == "mô tả đã bị đầu độc"


def test_assistant_message_cua_model_duoc_dung_neu_co():
    class NativeModel(FakeModel):
        def assistant_message(self, result):
            return {"role": "assistant", "content": result.text, "native": True}

    model = NativeModel([_result(calls=[_call("search_kb")]), _result("xong")])
    _core(model).run("hỏi", session=SessionState(run_id="r"), recorder=ListRecorder())
    assert model.calls[1]["messages"][2]["native"] is True


# ---------------------------------------------------------------------------
# Trace thật
# ---------------------------------------------------------------------------


def test_ghi_trace_that_va_blocked_by_defense_hop_le():
    engine = open_store()
    model = FakeModel([_result(calls=[_call("send_email")]), _result("thôi", tokens_in=7)])
    defense = SpyDefense(block=(HookStage.PRE_EGRESS, "send_email"))
    meta = RunMeta(
        run_kind="attack",
        target_id="A2",
        model_id="glm-5.2",
        batch_id="t",
        harness_version="core-a@test",
        env_hash="env@test",
        defense_config={"preset": "d4_only"},
        carrier_task_id="CT-05",
        payload_id="P-001",
        technique="T1",
        goal="G1",
        channel="K1",
        attacker_mode="blind",
        lang="vi",
    )
    with TraceRecorder(engine, meta) as rec:
        out = _core(model, defense=defense).run(
            "hỏi", session=SessionState(run_id=rec.run_id), recorder=rec
        )
        # Scorer (STT-35) sẽ gọi finish(); ở đây gọi thay để kiểm ràng buộc chéo runs ↔ steps.
        rec.finish(outcome="blocked", blocked_by="defense", final_answer=out.final_answer)
    with Session(engine) as db:
        run = db.get(Run, rec.run_id)
        steps = db.exec(select(Step).where(Step.run_id == rec.run_id).order_by(Step.step_idx)).all()
        assert (run.parse_error, run.blocked_by, run.n_steps) == (False, "defense", 3)
        assert (run.tokens_in, run.response_model) == (17, "fake-snap")
        assert [s.kind for s in steps] == ["llm", "defense", "llm"]
        assert json.loads(steps[1].defense_hits)[0]["rule"] == "R_test"
