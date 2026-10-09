"""Unit test cho src/agent/llm_client.py — STT-26, giai đoạn 0.

Không gọi mạng thật: gateway giả bằng `httpx.MockTransport`, đi qua đúng đường SDK openai.
Kiểm: chuẩn hóa response, pin model theo `model_id`, retry 429/5xx, không retry 4xx khác,
`parse_error` khi tool-call sai JSON, ghi `response_model`, log JSONL đủ dòng.
"""

import json
from pathlib import Path

import httpx
import pytest

from agent import llm_client as llm_mod
from agent.llm_client import LLMClient, LLMClientConfigError, LLMClientError

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "models.yaml"
PINNED = {"A1": "claude-opus-5", "A2": "glm-5.2", "A3": "glm-5.3-flash"}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("GATEWAY_BASE_URL", "https://gateway.invalid/v1")
    monkeypatch.setenv("GATEWAY_API_KEY", "test-key")
    for target, model in PINNED.items():
        monkeypatch.setenv(f"TARGET_MODEL_{target}", model)
    monkeypatch.setattr(llm_mod.time, "sleep", lambda _s: None)


def _completion(*, model, content=None, tool_args=None):
    message = {"role": "assistant", "content": content}
    if tool_args is not None:
        message["tool_calls"] = [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "search_kb", "arguments": tool_args},
            }
        ]
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 42, "completion_tokens": 7, "total_tokens": 49},
    }


def _gateway(responses):
    """Gateway giả trả lần lượt từng phần tử của `responses`: dict = 200, int = mã lỗi."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        item = responses[min(len(calls), len(responses)) - 1]
        if isinstance(item, int):
            return httpx.Response(item, json={"error": {"message": "boom"}})
        return httpx.Response(200, json=item)

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def _client(tmp_path, http_client, target="A2"):
    return LLMClient(
        target_id=target,
        config_path=CONFIG_PATH,
        log_path=tmp_path / "llm.jsonl",
        http_client=http_client,
    )


def _log_lines(tmp_path):
    return [json.loads(x) for x in (tmp_path / "llm.jsonl").read_text("utf-8").splitlines()]


def test_three_targets_resolve_to_pinned_models(tmp_path):
    for target, model in PINNED.items():
        client = LLMClient(target_id=target, config_path=CONFIG_PATH, log_path=None)
        assert client.model == model


def test_unknown_target_raises(tmp_path):
    with pytest.raises(LLMClientConfigError):
        LLMClient(target_id="api1", config_path=CONFIG_PATH, log_path=None)


def test_model_env_must_match_pinned_id(monkeypatch):
    monkeypatch.setenv("TARGET_MODEL_A3", "deepseek-v4.1-flash")
    with pytest.raises(LLMClientConfigError, match="model_id đã pin"):
        LLMClient(target_id="A3", config_path=CONFIG_PATH, log_path=None)


def test_missing_env_raises(monkeypatch):
    monkeypatch.delenv("GATEWAY_API_KEY")
    with pytest.raises(LLMClientConfigError, match="GATEWAY_API_KEY"):
        LLMClient(target_id="A1", config_path=CONFIG_PATH, log_path=None)


def test_chat_normalizes_tool_call_and_logs(tmp_path):
    http, calls = _gateway([_completion(model="glm-5.2", tool_args='{"query": "bảo hành"}')])
    result = _client(tmp_path, http).chat(
        [{"role": "user", "content": "chính sách bảo hành?"}],
        tools=[{"type": "function", "function": {"name": "search_kb", "parameters": {}}}],
    )

    assert calls[0]["model"] == "glm-5.2"
    assert calls[0]["temperature"] == 0
    assert result.tool_calls[0].name == "search_kb"
    assert result.tool_calls[0].arguments == {"query": "bảo hành"}
    assert not result.tool_calls[0].parse_error
    assert (result.tokens_in, result.tokens_out, result.attempts) == (42, 7, 1)

    (line,) = _log_lines(tmp_path)
    assert line["ok"] and line["tokens_in"] == 42
    assert line["request"]["messages"][0]["content"] == "chính sách bảo hành?"


def test_response_model_recorded_for_drift(tmp_path):
    http, _ = _gateway([_completion(model="glm-5.2-20261001", content="ok")])
    result = _client(tmp_path, http).chat([{"role": "user", "content": "hi"}])
    assert result.model == "glm-5.2"
    assert result.response_model == "glm-5.2-20261001"
    assert _log_lines(tmp_path)[0]["response_model"] == "glm-5.2-20261001"


@pytest.mark.parametrize("bad_args", ['{"query": ', '["không phải object"]'])
def test_malformed_tool_args_flag_parse_error_without_retry(tmp_path, bad_args):
    http, calls = _gateway([_completion(model="glm-5.2", tool_args=bad_args)])
    result = _client(tmp_path, http).chat([{"role": "user", "content": "hi"}])
    assert len(calls) == 1
    assert result.tool_calls[0].parse_error
    assert result.tool_calls[0].arguments is None
    assert result.tool_calls[0].arguments_raw == bad_args


def test_retries_429_and_5xx_then_succeeds(tmp_path):
    http, calls = _gateway([429, 503, _completion(model="glm-5.2", content="ok")])
    result = _client(tmp_path, http).chat([{"role": "user", "content": "hi"}])
    assert result.text == "ok"
    assert result.attempts == 3
    assert len(calls) == 3
    assert [x["ok"] for x in _log_lines(tmp_path)] == [False, False, True]


def test_no_retry_on_400(tmp_path):
    http, calls = _gateway([400])
    with pytest.raises(LLMClientError, match="400"):
        _client(tmp_path, http).chat([{"role": "user", "content": "hi"}])
    assert len(calls) == 1
    assert _log_lines(tmp_path)[0]["retryable"] is False


def test_gives_up_after_max_retries(tmp_path):
    http, calls = _gateway([500])
    client = _client(tmp_path, http)
    with pytest.raises(LLMClientError):
        client.chat([{"role": "user", "content": "hi"}])
    assert len(calls) == client.max_retries + 1
