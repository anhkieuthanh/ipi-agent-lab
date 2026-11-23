"""Test harness HN-OW (STT-79) — parse sự kiện JSON opencode thành trace, không gọi opencode thật."""

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from agent.llm_client import LLMClientError
from attack.harness_ow import MCP_SERVER_NAME, OpenWorkCore


@dataclass
class _FakeModel:
    model: str = "glm-5.2"


@dataclass
class _FakeRecorder:
    steps: list[dict[str, Any]] = field(default_factory=list)

    def step(self, **kw: Any) -> None:
        self.steps.append(kw)


def _core() -> OpenWorkCore:
    return OpenWorkCore(
        model=_FakeModel(), tools=object(), system_prompt="SP", max_steps=8, max_tokens=512
    )


def _ev(**kw: Any) -> str:
    return json.dumps(kw, ensure_ascii=False)


def _tool_ev(tool: str, inp: dict[str, Any], out: str, status: str = "completed") -> str:
    return _ev(type="tool_use", part={"type": "tool", "tool": tool, "callID": "c1",
                                      "state": {"status": status, "input": inp, "output": out}})


def test_record_dung_tool_roi_llm_cuoi():
    core = _core()
    rec = _FakeRecorder()
    stdout = "\n".join([
        _ev(type="step_start", part={"type": "step-start"}),
        _tool_ev(f"{MCP_SERVER_NAME}_search_kb", {"query": "x", "k": 8}, '{"results": []}'),
        _ev(type="step_finish", part={"tokens": {"input": 100, "output": 20}}),
        _ev(type="text", part={"type": "text", "text": "Câu trả lời cuối."}),
    ])
    outcome = core._record(stdout, rec)
    # bước 0 = tool (đã bỏ tiền tố server), bước 1 = llm không-tool mang câu trả lời
    assert [s["kind"] for s in rec.steps] == ["tool", "llm"]
    assert rec.steps[0]["tool_name"] == "search_kb"
    assert rec.steps[0]["tool_args"] == {"query": "x", "k": 8}
    assert rec.steps[0]["tool_result"] == '{"results": []}'
    assert rec.steps[1]["llm_text"] == "Câu trả lời cuối."
    assert rec.steps[1]["tool_args"] is None  # hợp đồng _final_answer của scorer
    assert rec.steps[1]["tokens_in"] == 100 and rec.steps[1]["tokens_out"] == 20
    assert outcome.final_answer == "Câu trả lời cuối."
    assert outcome.stop_reason == "final_answer"
    assert outcome.n_steps == 2


def test_record_tool_chua_completed_bi_bo_qua():
    core = _core()
    rec = _FakeRecorder()
    stdout = "\n".join([
        _tool_ev(f"{MCP_SERVER_NAME}_send_email", {"to": "a@b.c"}, "", status="running"),
        _ev(type="text", part={"type": "text", "text": "xong"}),
    ])
    core._record(stdout, rec)
    assert [s["kind"] for s in rec.steps] == ["llm"]  # tool running không ghi


def test_record_loi_khong_co_text_thanh_parse_error():
    core = _core()
    rec = _FakeRecorder()
    stdout = _ev(type="error", error={"name": "UnknownError"})
    with pytest.raises(LLMClientError, match="UnknownError"):
        core._record(stdout, rec)


def test_record_text_cuoi_thang():
    core = _core()
    rec = _FakeRecorder()
    stdout = "\n".join([
        _ev(type="text", part={"type": "text", "text": "giữa"}),
        _ev(type="text", part={"type": "text", "text": "cuối"}),
    ])
    out = core._record(stdout, rec)
    assert out.final_answer == "cuối"  # text sau cùng thắng


def test_write_config_co_provider_mcp_agent(tmp_path, monkeypatch):
    monkeypatch.setenv("GATEWAY_BASE_URL", "https://gw.example/v1")
    core = _core()
    core._write_config(tmp_path, "http://127.0.0.1:8765/mcp")
    cfg = json.loads((tmp_path / "opencode.json").read_text("utf-8"))
    assert cfg["provider"]["llmgate"]["options"]["baseURL"] == "https://gw.example/v1"
    # không ghi key trực tiếp — chỉ template {env:...}
    assert cfg["provider"]["llmgate"]["options"]["apiKey"] == "{env:GATEWAY_API_KEY}"
    assert cfg["mcp"][MCP_SERVER_NAME]["url"] == "http://127.0.0.1:8765/mcp"
    assert cfg["agent"]["testbed"]["tools"]["bash"] is False  # builtin tắt
    assert (tmp_path / "system_prompt.md").read_text("utf-8") == "SP"


def test_write_config_thieu_base_url_bao_loi(tmp_path, monkeypatch):
    monkeypatch.delenv("GATEWAY_BASE_URL", raising=False)
    with pytest.raises(LLMClientError, match="GATEWAY_BASE_URL"):
        _core()._write_config(tmp_path, "http://x/mcp")


def test_strip_prefix():
    assert OpenWorkCore._strip_prefix("testbed_search_kb") == "search_kb"
    assert OpenWorkCore._strip_prefix("search_kb") == "search_kb"
