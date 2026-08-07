"""Unit test cho src/agent/llm_client.py — W2-02.

Không gọi mạng thật: mock `openai.OpenAI().chat.completions.create` để kiểm
(1) chuẩn hóa response -> LLMResult, (2) retry backoff cho 429/5xx rồi thành
công, (3) không retry cho lỗi 4xx khác, (4) mỗi lần gọi ghi đúng số dòng vào
JSONL log. DoD "3/3 model gọi được tool" được xác nhận riêng bằng
`scripts/check_targets.py` chạy trên máy có mạng/LM Studio thật.
"""

import json
import os
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import openai
import pytest

os.environ.setdefault("OPENAI_COMPATIBLE_BASE_URL", "https://example.invalid/v1")
os.environ.setdefault("OPENAI_COMPATIBLE_API_KEY", "test-key")
os.environ.setdefault("TARGET_MODEL_A", "test-model-a")
os.environ.setdefault("TARGET_MODEL_B", "test-model-b")
os.environ.setdefault("LOCAL_LLM_BASE_URL", "http://localhost:1234/v1")
os.environ.setdefault("LOCAL_LLM_API_KEY", "lm-studio")
os.environ.setdefault("LOCAL_LLM_MODEL", "test-model-local")

from agent.llm_client import LLMClient, LLMClientConfigError, LLMClientError  # noqa: E402

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "models.yaml")


def _fake_response(*, with_tool_call=True, content=None):
    if with_tool_call:
        message = SimpleNamespace(
            content=content,
            tool_calls=[
                SimpleNamespace(
                    id="call_1",
                    function=SimpleNamespace(
                        name="get_weather", arguments=json.dumps({"city": "Đà Nẵng"})
                    ),
                )
            ],
        )
    else:
        message = SimpleNamespace(content=content or "xin chào", tool_calls=None)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=42, completion_tokens=7),
    )


def _fake_http_error(status_code: int) -> httpx.Response:
    request = httpx.Request("POST", "https://example.invalid/v1/chat/completions")
    return httpx.Response(status_code=status_code, request=request, json={"error": "boom"})


def _client(tmp_path, target_id="api1"):
    return LLMClient(
        target_id=target_id,
        config_path=CONFIG_PATH,
        log_path=str(tmp_path / "llm_client.jsonl"),
    )


def test_unknown_target_raises_config_error(tmp_path):
    with pytest.raises(LLMClientConfigError):
        LLMClient(target_id="khong_ton_tai", config_path=CONFIG_PATH, log_path=str(tmp_path / "x.jsonl"))


def test_target_switch_is_one_string(tmp_path):
    c1 = _client(tmp_path, "api1")
    c2 = _client(tmp_path, "api2")
    c3 = _client(tmp_path, "local")
    assert c1.model == "test-model-a"
    assert c2.model == "test-model-b"
    assert c3.model == "test-model-local"


def test_chat_normalizes_tool_call_and_logs(tmp_path):
    client = _client(tmp_path)
    with patch.object(client._client.chat.completions, "create", return_value=_fake_response()):
        result = client.chat(
            messages=[{"role": "user", "content": "thời tiết Đà Nẵng"}],
            tools=[{"type": "function", "function": {"name": "get_weather", "parameters": {}}}],
        )

    assert result.attempts == 1
    assert result.tokens_in == 42
    assert result.tokens_out == 7
    assert len(result.tool_calls) == 1
    tc = result.tool_calls[0]
    assert tc.name == "get_weather"
    assert tc.arguments == {"city": "Đà Nẵng"}
    assert tc.parse_error is False

    log_lines = client.log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(log_lines) == 1
    record = json.loads(log_lines[0])
    assert record["ok"] is True
    assert record["target_id"] == "api1"
    assert record["tool_calls"] == [{"name": "get_weather", "parse_error": False}]


def test_retries_on_429_then_succeeds(tmp_path):
    client = _client(tmp_path)
    client.backoff_base_s = 0.001
    client.backoff_max_s = 0.002

    err = openai.RateLimitError(message="rate limited", response=_fake_http_error(429), body=None)
    calls = {"n": 0}

    def side_effect(**kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise err
        return _fake_response(with_tool_call=False, content="ok")

    with patch.object(client._client.chat.completions, "create", side_effect=side_effect):
        result = client.chat(messages=[{"role": "user", "content": "hi"}])

    assert calls["n"] == 3
    assert result.attempts == 3
    assert result.text == "ok"

    log_lines = client.log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(log_lines) == 3  # 2 lần lỗi + 1 lần thành công, mỗi lần 1 dòng
    assert json.loads(log_lines[0])["ok"] is False
    assert json.loads(log_lines[-1])["ok"] is True


def test_400_error_does_not_retry(tmp_path):
    client = _client(tmp_path)
    err = openai.BadRequestError(message="bad request", response=_fake_http_error(400), body=None)
    with patch.object(client._client.chat.completions, "create", side_effect=err):
        with pytest.raises(LLMClientError):
            client.chat(messages=[{"role": "user", "content": "hi"}])

    log_lines = client.log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(log_lines) == 1  # không retry -> đúng 1 lần thử


def test_log_bodies_ghi_nguyen_van_request_va_response(tmp_path):
    """DoD W2-02 'log mọi request/response': phải có nguyên văn, không chỉ metadata.

    Không có phần này thì khi một payload kích hoạt được (hoặc bị chặn) sẽ không
    truy ngược được model đã nhìn thấy chính xác chuỗi nào.
    """
    client = _client(tmp_path)
    assert client.log_bodies is True, "mặc định trong config/models.yaml phải là true"

    messages = [{"role": "user", "content": "thời tiết Đà Nẵng"}]
    tools = [{"type": "function", "function": {"name": "get_weather", "parameters": {}}}]
    with patch.object(client._client.chat.completions, "create", return_value=_fake_response()):
        client.chat(messages=messages, tools=tools)

    record = json.loads(client.log_path.read_text(encoding="utf-8").strip())
    assert record["request"]["messages"] == messages
    assert record["request"]["tools"] == tools
    assert record["request"]["model"] == "test-model-a"
    assert "response" in record


def test_log_bodies_tat_thi_chi_con_metadata(tmp_path):
    client = LLMClient(
        target_id="api1",
        config_path=CONFIG_PATH,
        log_path=str(tmp_path / "llm_client.jsonl"),
        log_bodies=False,
    )
    with patch.object(client._client.chat.completions, "create", return_value=_fake_response()):
        client.chat(messages=[{"role": "user", "content": "hi"}])

    record = json.loads(client.log_path.read_text(encoding="utf-8").strip())
    assert "request" not in record and "response" not in record
    assert record["tokens_in"] == 42  # metadata chi phí vẫn còn


def test_max_retries_la_so_lan_thu_lai_khong_ke_lan_dau(tmp_path):
    """Chốt ngữ nghĩa `max_retries` để không ai đọc nhầm thành 'tổng số lần gọi'."""
    client = _client(tmp_path)
    client.max_retries = 3
    client.backoff_base_s = 0.001
    client.backoff_max_s = 0.002
    err = openai.InternalServerError(message="boom", response=_fake_http_error(503), body=None)
    calls = {"n": 0}

    def side_effect(**kwargs):
        calls["n"] += 1
        raise err

    with patch.object(client._client.chat.completions, "create", side_effect=side_effect):
        with pytest.raises(LLMClientError):
            client.chat(messages=[{"role": "user", "content": "hi"}])

    assert calls["n"] == 4  # 1 lần đầu + 3 lần thử lại


def test_exhausts_retries_and_raises(tmp_path):
    client = _client(tmp_path)
    client.max_retries = 2
    client.backoff_base_s = 0.001
    client.backoff_max_s = 0.002
    err = openai.InternalServerError(message="server error", response=_fake_http_error(500), body=None)
    with patch.object(client._client.chat.completions, "create", side_effect=err):
        with pytest.raises(LLMClientError):
            client.chat(messages=[{"role": "user", "content": "hi"}])

    log_lines = client.log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(log_lines) == client.max_retries + 1  # lần đầu + max_retries lần retry
