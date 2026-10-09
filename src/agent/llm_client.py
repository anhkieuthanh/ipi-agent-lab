"""llm_client dùng chung cho ba mô hình đích A1–A3 — STT-26 (giai đoạn 0 của lộ trình code).

Đọc `config/models.yaml`, nhận `target_id` ∈ {"A1", "A2", "A3"}. Đổi model đích chỉ cần đổi
chuỗi `target_id`; base_url/api_key/model lấy qua biến môi trường mà config trỏ tên, KHÔNG
hard-code ở đây (mẫu ở `.env.example`).

Pin model (quy tắc cứng #9, khóa `v-models-1.0`): giá trị biến `model_env` phải trùng
`model_id` trong config, lệch thì từ chối khởi tạo. Gateway chỉ cung cấp bí danh, nên mỗi
`LLMResult` mang thêm `response_model` — trường `model` mà gateway trả về — để trace phát hiện
nhà cung cấp đổi snapshot sau bí danh.

`chat(messages, tools)` trả `LLMResult` chuẩn hóa: `text`, `tool_calls[]`, `tokens_in`/
`tokens_out`, `latency_ms`. Retry backoff mũ có jitter cho 429/5xx/timeout. Lỗi 4xx khác không
retry. Tool-call sai JSON cũng không retry: đó là hành vi của model, đánh dấu `parse_error`.

Log JSONL (mặc định `logs/llm_client.jsonl`) ghi mọi lần gọi kể cả lần lỗi — nguồn đếm chi phí
và bằng chứng nguyên văn. Đây là log tầng gọi model, khác `TraceRecorder` (STT-32) ghi trace
một run.

Module không tự nạp `.env`; script đầu vào gọi `dotenv.load_dotenv()` trước khi khởi tạo.
"""

from __future__ import annotations

import json
import os
import random
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import openai
import yaml

__all__ = ["LLMClient", "LLMResult", "ToolCall", "LLMClientConfigError", "LLMClientError"]

DEFAULT_CONFIG_PATH = "config/models.yaml"
DEFAULT_LOG_PATH = "logs/llm_client.jsonl"

# 429 (rate limit) + 5xx (lỗi phía server) được retry.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class LLMClientError(RuntimeError):
    """Lỗi khi gọi model đích, sau khi đã hết số lần retry."""


class LLMClientConfigError(RuntimeError):
    """Lỗi cấu hình: target không tồn tại, thiếu biến môi trường, model lệch bản đã pin."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] | None
    arguments_raw: str
    parse_error: bool = False


@dataclass
class LLMResult:
    text: str | None
    tool_calls: list[ToolCall]
    tokens_in: int | None
    tokens_out: int | None
    latency_ms: int
    target_id: str
    model: str
    response_model: str | None
    attempts: int
    finish_reason: str | None = None
    raw_response: Any = field(default=None, repr=False)


def _load_config(config_path: str | Path) -> dict[str, Any]:
    path = Path(config_path)
    if not path.is_file():
        raise LLMClientConfigError(f"Không tìm thấy file cấu hình: {config_path}")
    with path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if not cfg or not cfg.get("targets"):
        raise LLMClientConfigError(f"{config_path} thiếu khối 'targets'")
    return cfg


def _resolve_env(var_name: str, *, target_id: str, field_name: str) -> str:
    value = os.getenv(var_name)
    if not value:
        raise LLMClientConfigError(
            f"target '{target_id}': biến môi trường '{var_name}' (cho '{field_name}') "
            "chưa được set — xem .env.example"
        )
    return value


def _jsonable(obj: Any) -> Any:
    """Đổi object của SDK thành dữ liệu ghi được ra JSON; không bao giờ ném lỗi khi ghi log."""
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:  # pragma: no cover - SDK đổi kiểu bất thường
            return repr(obj)
    try:
        json.dumps(obj, ensure_ascii=False)
        return obj
    except (TypeError, ValueError):
        return repr(obj)


class LLMClient:
    """Client tương thích OpenAI dùng chung cho mọi model đích của lab.

    Ví dụ:
        client = LLMClient(target_id="A2")
        result = client.chat(messages=[...], tools=[...])
    """

    def __init__(
        self,
        target_id: str,
        *,
        config_path: str | Path = DEFAULT_CONFIG_PATH,
        log_path: str | Path | None = DEFAULT_LOG_PATH,
        run_id: str | None = None,
        log_bodies: bool | None = None,
        http_client: Any = None,
    ) -> None:
        cfg = _load_config(config_path)
        targets = cfg["targets"]
        if target_id not in targets:
            raise LLMClientConfigError(
                f"target_id không hợp lệ: '{target_id}'. Có sẵn: {sorted(targets)}"
            )
        spec = targets[target_id]
        defaults = cfg.get("defaults") or {}

        def opt(key: str, fallback: Any) -> Any:
            return spec.get(key, defaults.get(key, fallback))

        self.target_id = target_id
        self.label = spec.get("label", target_id)
        self.base_url = _resolve_env(
            spec["base_url_env"], target_id=target_id, field_name="base_url"
        )
        self.api_key = _resolve_env(spec["api_key_env"], target_id=target_id, field_name="api_key")
        self.model = _resolve_env(spec["model_env"], target_id=target_id, field_name="model")

        pinned = spec.get("model_id")
        if pinned and self.model != pinned:
            raise LLMClientConfigError(
                f"target '{target_id}': {spec['model_env']}='{self.model}' lệch model_id đã pin "
                f"'{pinned}' (v-models-1.0). Sửa .env, không sửa config."
            )

        self.timeout_s: float = opt("timeout_s", 60)
        self.max_retries: int = opt("max_retries", 5)
        self.backoff_base_s: float = opt("backoff_base_s", 1.0)
        self.backoff_max_s: float = opt("backoff_max_s", 30.0)
        self.default_temperature = opt("temperature", 0)
        self.log_bodies: bool = opt("log_bodies", True) if log_bodies is None else log_bodies

        self.log_path = Path(log_path) if log_path else None
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

        # max_retries=0 ở SDK: client này tự retry để log được từng lần thử.
        self._client = openai.OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout_s,
            max_retries=0,
            http_client=http_client,
        )
        self.run_id = run_id or uuid.uuid4().hex[:12]

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        tool_choice: str = "auto",
        temperature: float | None = None,
        **extra_kwargs: Any,
    ) -> LLMResult:
        """Gọi model, chuẩn hóa kết quả, retry cho 429/5xx/timeout, log mọi lần gọi."""
        request_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.default_temperature if temperature is None else temperature,
            **extra_kwargs,
        }
        if tools:
            request_kwargs["tools"] = tools
            request_kwargs["tool_choice"] = tool_choice

        call_id = uuid.uuid4().hex[:12]
        attempt = 0
        t_start = time.perf_counter()

        while True:
            attempt += 1
            t0 = time.perf_counter()
            try:
                response = self._client.chat.completions.create(**request_kwargs)
            except openai.APIStatusError as e:
                retryable = e.status_code in _RETRYABLE_STATUS
                self._log_error(
                    call_id, attempt, request_kwargs, t0, f"HTTP {e.status_code}: {e}", retryable
                )
                if retryable and attempt <= self.max_retries:
                    self._sleep_backoff(attempt)
                    continue
                raise LLMClientError(
                    f"[{self.target_id}] lỗi HTTP {e.status_code} sau {attempt} lần thử: {e}"
                ) from e
            except (openai.APIConnectionError, openai.APITimeoutError) as e:
                self._log_error(
                    call_id, attempt, request_kwargs, t0, f"{type(e).__name__}: {e}", True
                )
                if attempt <= self.max_retries:
                    self._sleep_backoff(attempt)
                    continue
                raise LLMClientError(
                    f"[{self.target_id}] lỗi kết nối sau {attempt} lần thử: {e}"
                ) from e

            latency_ms = int((time.perf_counter() - t_start) * 1000)
            result = self._normalize(response, attempt=attempt, latency_ms=latency_ms)
            self._log_success(call_id, request_kwargs, response, result)
            return result

    def _sleep_backoff(self, attempt: int) -> None:
        # Full jitter: sleep = uniform(0, min(max, base * 2^(attempt-1))).
        cap = min(self.backoff_max_s, self.backoff_base_s * (2 ** (attempt - 1)))
        time.sleep(random.uniform(0, cap))

    def _normalize(self, response: Any, *, attempt: int, latency_ms: int) -> LLMResult:
        choice = response.choices[0]
        message = choice.message
        usage = getattr(response, "usage", None)

        tool_calls: list[ToolCall] = []
        for tc in getattr(message, "tool_calls", None) or []:
            raw_args = tc.function.arguments or ""
            try:
                parsed = json.loads(raw_args) if raw_args else {}
                parse_error = not isinstance(parsed, dict)
            except json.JSONDecodeError:
                parsed, parse_error = None, True
            tool_calls.append(
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=parsed if not parse_error else None,
                    arguments_raw=raw_args,
                    parse_error=parse_error,
                )
            )

        return LLMResult(
            text=message.content,
            tool_calls=tool_calls,
            tokens_in=getattr(usage, "prompt_tokens", None) if usage else None,
            tokens_out=getattr(usage, "completion_tokens", None) if usage else None,
            latency_ms=latency_ms,
            target_id=self.target_id,
            model=self.model,
            response_model=getattr(response, "model", None),
            attempts=attempt,
            finish_reason=choice.finish_reason,
            raw_response=response,
        )

    def _base_record(self, call_id: str, attempt: int, request: dict[str, Any]) -> dict[str, Any]:
        return {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "run_id": self.run_id,
            "call_id": call_id,
            "attempt": attempt,
            "target_id": self.target_id,
            "model": self.model,
            "n_messages": len(request.get("messages", [])),
            "has_tools": bool(request.get("tools")),
        }

    def _log_error(
        self,
        call_id: str,
        attempt: int,
        request: dict[str, Any],
        t0: float,
        error: str,
        retryable: bool,
    ) -> None:
        record = self._base_record(call_id, attempt, request)
        record.update(
            ok=False,
            error=error,
            retryable=retryable,
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )
        if self.log_bodies:
            record["request"] = _jsonable(request)
        self._write(record)

    def _log_success(
        self, call_id: str, request: dict[str, Any], response: Any, result: LLMResult
    ) -> None:
        record = self._base_record(call_id, result.attempts, request)
        record.update(
            ok=True,
            response_model=result.response_model,
            latency_ms=result.latency_ms,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            finish_reason=result.finish_reason,
            tool_calls=[
                {"name": tc.name, "parse_error": tc.parse_error} for tc in result.tool_calls
            ],
            text_preview=(result.text or "")[:200],
        )
        if self.log_bodies:
            # Nguyên văn — text_preview chỉ đủ để lướt, không đủ làm bằng chứng.
            record["request"] = _jsonable(request)
            record["response"] = _jsonable(response)
        self._write(record)

    def _write(self, record: dict[str, Any]) -> None:
        if not self.log_path:
            return
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
