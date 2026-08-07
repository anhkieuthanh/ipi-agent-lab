"""llm_client dùng chung cho mọi target model — W2-02.

Đọc `config/models.yaml`, nhận `target_id` (vd `"api1"`, `"api2"`, `"local"`
— xem file config để biết danh sách đầy đủ, khớp 3 model đích của W1-11).
Đổi model đích chỉ cần đổi chuỗi `target_id` khi khởi tạo `LLMClient`; mọi
giá trị nhạy cảm (base_url/api_key/model) lấy qua biến môi trường tên trong
config, KHÔNG hard-code trong file này (xem `.env.example`).

`chat(messages, tools)` trả về `LLMResult` chuẩn hóa: `text`, `tool_calls[]`,
`tokens_in`/`tokens_out`, `latency_ms` — giống nhau bất kể target là API
gateway hay LM Studio local, vì cả hai đều expose schema tương thích OpenAI.

Retry: backoff mũ (có jitter) cho lỗi 429 (rate limit) và 5xx (lỗi server).
`max_retries` = số lần **thử lại**, không tính lần gọi đầu: `max_retries=5`
nghĩa là tối đa 6 lần gọi mạng. Lỗi 4xx khác (vd 400, 401) KHÔNG retry — đó là
lỗi cấu hình/yêu cầu sai, thử lại không giúp gì. Sai định dạng tool-call cũng
KHÔNG retry: đó là hành vi của model, là thứ đề tài phải đo (nhãn `parse_error`
của W1-10), retry sẽ làm đẹp số một cách giả tạo.

Log: mọi request/response (kể cả các lần bị lỗi/retry) được ghi 1 dòng JSON
vào file JSONL (mặc định `logs/llm_client.jsonl`) — dùng để soát chi phí
(`docs/technical_notes/cost_budget.md`) và debug định dạng tool-calling
(`docs/technical_notes/local_model_notes.md`). Với `log_bodies=True` (mặc
định, đặt được ở `config/models.yaml`) dòng log mang cả `messages`, `tools` và
response thô — không có phần này thì không truy được vì sao một payload cụ thể
kích hoạt hay bị chặn, mà đó chính là bằng chứng của luận văn. Tắt bằng
`LLMClient(..., log_bodies=False)` khi chỉ cần đếm chi phí.

Đây là log ở tầng gọi model, khác với `TraceRecorder` (W2-11) ghi trace đầy đủ
1 run theo `docs/technical_notes/trace_schema.md`.
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

import yaml

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - dotenv là tiện ích dev, không bắt buộc ở runtime
    pass

import openai

__all__ = ["LLMClient", "LLMResult", "ToolCall", "LLMClientConfigError", "LLMClientError"]

DEFAULT_CONFIG_PATH = "config/models.yaml"
DEFAULT_LOG_PATH = "logs/llm_client.jsonl"

# Mã lỗi HTTP được phép retry — 429 (rate limit) + mọi 5xx (lỗi phía server).
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class LLMClientError(RuntimeError):
    """Lỗi khi gọi model đích, sau khi đã hết số lần retry."""


class LLMClientConfigError(RuntimeError):
    """Lỗi cấu hình: target_id không tồn tại, thiếu biến môi trường, v.v."""


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
    attempts: int
    finish_reason: str | None = None
    raw_response: Any = field(default=None, repr=False)


def _load_config(config_path: str) -> dict[str, Any]:
    path = Path(config_path)
    if not path.is_file():
        raise LLMClientConfigError(f"Không tìm thấy file cấu hình: {config_path}")
    with path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if not cfg or "targets" not in cfg:
        raise LLMClientConfigError(f"{config_path} thiếu khối 'targets'")
    return cfg


def _jsonable(obj: Any) -> Any:
    """Đổi object của SDK (pydantic) thành dữ liệu ghi được ra JSON.

    Không được để việc ghi log làm hỏng một lần gọi model đã thành công, nên
    mọi trường hợp không serialize được đều rơi về `repr()` thay vì ném lỗi.
    """
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


def _resolve_env(var_name: str, *, target_id: str, field_name: str) -> str:
    value = os.getenv(var_name)
    if not value:
        raise LLMClientConfigError(
            f"target_id='{target_id}': biến môi trường '{var_name}' (cho '{field_name}') "
            f"chưa được set — xem .env.example"
        )
    return value


class LLMClient:
    """Client OpenAI-compatible dùng chung cho mọi model đích của lab.

    Ví dụ:
        client = LLMClient(target_id="api1")
        result = client.chat(messages=[...], tools=[...])

    Đổi target chỉ cần đổi chuỗi:
        client = LLMClient(target_id="local")
    """

    def __init__(
        self,
        target_id: str,
        *,
        config_path: str = DEFAULT_CONFIG_PATH,
        log_path: str | None = DEFAULT_LOG_PATH,
        run_id: str | None = None,
        log_bodies: bool | None = None,
    ) -> None:
        cfg = _load_config(config_path)
        targets = cfg["targets"]
        if target_id not in targets:
            raise LLMClientConfigError(
                f"target_id không hợp lệ: '{target_id}'. Có sẵn: {sorted(targets)}"
            )
        spec = targets[target_id]
        defaults = cfg.get("defaults", {})

        self.target_id = target_id
        self.label = spec.get("label", target_id)
        self.base_url = _resolve_env(spec["base_url_env"], target_id=target_id, field_name="base_url")
        self.api_key = _resolve_env(spec["api_key_env"], target_id=target_id, field_name="api_key")
        self.model = _resolve_env(spec["model_env"], target_id=target_id, field_name="model")

        self.timeout_s: float = spec.get("timeout_s", defaults.get("timeout_s", 30))
        self.max_retries: int = spec.get("max_retries", defaults.get("max_retries", 5))
        self.backoff_base_s: float = spec.get("backoff_base_s", defaults.get("backoff_base_s", 1.0))
        self.backoff_max_s: float = spec.get("backoff_max_s", defaults.get("backoff_max_s", 30.0))
        self.default_temperature = spec.get("temperature", defaults.get("temperature", 0))

        self.log_bodies: bool = (
            spec.get("log_bodies", defaults.get("log_bodies", True))
            if log_bodies is None
            else log_bodies
        )

        self.log_path = Path(log_path) if log_path else None
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

        self._client = openai.OpenAI(
            api_key=self.api_key, base_url=self.base_url, timeout=self.timeout_s
        )
        self.run_id = run_id or uuid.uuid4().hex[:12]

    # ------------------------------------------------------------------
    # API chính
    # ------------------------------------------------------------------
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        tool_choice: str = "auto",
        temperature: float | None = None,
        **extra_kwargs: Any,
    ) -> LLMResult:
        """Gọi model, chuẩn hóa kết quả, retry cho 429/5xx, log mọi lần gọi."""
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
                status = e.status_code
                latency_ms = int((time.perf_counter() - t0) * 1000)
                retryable = status in _RETRYABLE_STATUS
                self._log_event(
                    call_id=call_id,
                    attempt=attempt,
                    request=request_kwargs,
                    error=f"APIStatusError:{status}:{e}",
                    latency_ms=latency_ms,
                    retryable=retryable,
                )
                if retryable and attempt <= self.max_retries:
                    self._sleep_backoff(attempt)
                    continue
                raise LLMClientError(
                    f"[{self.target_id}] lỗi HTTP {status} sau {attempt} lần thử: {e}"
                ) from e
            except (openai.APIConnectionError, openai.APITimeoutError) as e:
                latency_ms = int((time.perf_counter() - t0) * 1000)
                self._log_event(
                    call_id=call_id,
                    attempt=attempt,
                    request=request_kwargs,
                    error=f"{type(e).__name__}:{e}",
                    latency_ms=latency_ms,
                    retryable=True,
                )
                if attempt <= self.max_retries:
                    self._sleep_backoff(attempt)
                    continue
                raise LLMClientError(
                    f"[{self.target_id}] lỗi kết nối sau {attempt} lần thử: {e}"
                ) from e
            except openai.APIError as e:
                # Lỗi 4xx không nằm trong _RETRYABLE_STATUS (400, 401, 403...) — không retry.
                latency_ms = int((time.perf_counter() - t0) * 1000)
                self._log_event(
                    call_id=call_id,
                    attempt=attempt,
                    request=request_kwargs,
                    error=f"APIError:{e}",
                    latency_ms=latency_ms,
                    retryable=False,
                )
                raise LLMClientError(f"[{self.target_id}] lỗi không retry được: {e}") from e

            latency_ms_total = int((time.perf_counter() - t_start) * 1000)
            result = self._normalize(response, attempt=attempt, latency_ms=latency_ms_total)
            self._log_event(
                call_id=call_id,
                attempt=attempt,
                request=request_kwargs,
                response=response,
                result=result,
                latency_ms=latency_ms_total,
                retryable=False,
            )
            return result

    # ------------------------------------------------------------------
    # Nội bộ
    # ------------------------------------------------------------------
    def _sleep_backoff(self, attempt: int) -> None:
        # Backoff mũ + jitter đầy đủ (full jitter): sleep = uniform(0, min(max, base * 2^(attempt-1)))
        cap = min(self.backoff_max_s, self.backoff_base_s * (2 ** (attempt - 1)))
        time.sleep(random.uniform(0, cap))

    def _normalize(self, response: Any, *, attempt: int, latency_ms: int) -> LLMResult:
        choice = response.choices[0]
        message = choice.message
        usage = getattr(response, "usage", None)

        tool_calls: list[ToolCall] = []
        for tc in getattr(message, "tool_calls", None) or []:
            raw_args = tc.function.arguments
            try:
                parsed_args = json.loads(raw_args) if raw_args else {}
                parse_error = False
            except json.JSONDecodeError:
                parsed_args = None
                parse_error = True
            tool_calls.append(
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=parsed_args,
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
            attempts=attempt,
            finish_reason=choice.finish_reason,
            raw_response=response,
        )

    def _log_event(
        self,
        *,
        call_id: str,
        attempt: int,
        request: dict[str, Any],
        latency_ms: int,
        retryable: bool,
        response: Any = None,
        result: LLMResult | None = None,
        error: str | None = None,
    ) -> None:
        if not self.log_path:
            return
        record: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "run_id": self.run_id,
            "call_id": call_id,
            "attempt": attempt,
            "target_id": self.target_id,
            "model": self.model,
            "latency_ms": latency_ms,
            "n_messages": len(request.get("messages", [])),
            "has_tools": bool(request.get("tools")),
        }
        if error is not None:
            record["ok"] = False
            record["error"] = error
            record["retryable"] = retryable
        else:
            record["ok"] = True
            record["tokens_in"] = result.tokens_in if result else None
            record["tokens_out"] = result.tokens_out if result else None
            record["finish_reason"] = result.finish_reason if result else None
            record["tool_calls"] = (
                [
                    {"name": tc.name, "parse_error": tc.parse_error}
                    for tc in result.tool_calls
                ]
                if result
                else []
            )
            record["text_preview"] = (result.text or "")[:200] if result else None

        if self.log_bodies:
            # Nguyên văn request/response. Bắt buộc để truy được vì sao MỘT payload
            # cụ thể kích hoạt được hay bị chặn — `text_preview` 200 ký tự ở trên
            # chỉ đủ để lướt, không đủ làm bằng chứng.
            record["request"] = _jsonable(request)
            if response is not None:
                record["response"] = _jsonable(response)

        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
