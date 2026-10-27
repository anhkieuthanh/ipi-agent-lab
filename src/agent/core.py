"""Lõi agent Core-A — STT-26, giai đoạn 2 của lộ trình code.

Vòng lặp tool-calling tự viết, không phụ thuộc framework, hiện thực `interfaces.AgentCore`:

    gọi model → với từng tool-call đề xuất:
        PRE_TOOL_EXECUTION (D3) → PRE_EGRESS (D4) → thực thi
        → KB_RETRIEVAL (search_kb) | TOOL_RESULT (tool khác)  (D2)
        → CONTEXT_ASSEMBLY (D1) → nối vào messages
    → lặp, tối đa `max_steps` lần gọi model.

Mô tả tool đi qua CONTEXT_ASSEMBLY (nguồn `tool_description`, K2a) ở đầu mỗi run, trước lời gọi
model đầu tiên. Danh sách tool lấy lại mỗi run (`ToolLayer.list_tools`), không cache, để injector
K2a ghi đè description có tác dụng.

Lõi agent gọi đủ năm hook ở mọi run, kể cả preset `off` (qua `NoDefense`): bật/tắt phòng thủ chỉ
đổi `DefenseLayer`, không đổi call site. Lõi agent không biết cơ chế nào đang bật, không xét tool có
phải egress hay không, không suy ra `task_type` (quy tắc cứng #3).

Logic dừng — `AgentOutcome.stop_reason`:

- `final_answer`: model trả lượt không có tool-call. Văn bản rỗng vẫn là `final_answer` với
  `final_answer=None`; scorer xét `finish_reason = length` để gán `parse_error` (mục 12.4 (d)).
- `max_steps`: đã gọi model `max_steps` lần mà lượt cuối vẫn đề xuất tool-call. Tool-call của lượt
  cuối vẫn được xét gate và thực thi — tác dụng phụ của nó là hành vi cần chấm — nhưng không gọi
  model thêm. `final_answer=None`.
- `parse_error`: có tool-call không parse được thành JSON. Dừng ngay, KHÔNG thực thi tool-call nào
  của lượt đó (kể cả tool-call hợp lệ đi cùng): chạy nửa lượt thì trace không còn ứng với một quyết
  định trọn vẹn của model. Tool-call lỗi không tới hook gate (`HOOK_SPECS[PRE_TOOL_EXECUTION]`).

Tool-call bị gate chặn: không thực thi, model nhận `ToolResult(is_error=True)` mang `reason`, vòng
lặp chạy tiếp, `defense_blocked = True`. Văn bản lỗi đó do harness sinh, không phải nội dung không
tin cậy, nên không qua hook transform.

Trace (`interfaces.Recorder`): một bước `llm` mỗi lần gọi model (hit CONTEXT_ASSEMBLY của mô tả tool
gắn vào bước `llm` đầu tiên), một bước `tool` mỗi tool-call được thực thi, một bước `defense` mỗi
tool-call bị chặn. Bước `tool` ghi kết quả THÔ từ tầng công cụ — bằng chứng cho scorer — còn bản
đã qua D1/D2 là thứ model nhận. Lõi agent không gọi `finish()` và không ghi `blocked_by`
(quy tắc cứng #8): đó là việc của scorer.

Exception từ model (`LLMClientError` sau khi hết retry) hay từ tầng công cụ lan ra ngoài;
`TraceRecorder.__exit__` gắn `parse_error` cho run và vẫn ghi.

`max_steps`, `max_tokens` lấy từ `config/experiment.yaml` khối `fixed` qua `load_core_params()`;
system prompt do bên gọi truyền vào (STT-31).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from interfaces import (
    AgentOutcome,
    ChatModel,
    Decision,
    DefenseHit,
    DefenseLayer,
    ExecutedCall,
    HookStage,
    Recorder,
    SessionState,
    ToolLayer,
    ToolResult,
    source_for_tool,
)

__all__ = ["CoreA", "load_core_params"]

#: Tiền tố nội dung tool-result trả cho model khi gate chặn.
BLOCKED_PREFIX = "Tool-call bị chặn"


def load_core_params(path: str | Path | None = None) -> dict[str, int]:
    """`max_steps`, `max_tokens` từ khối `fixed` của experiment.yaml — không hard-code ở lõi."""
    from eval.experiment import DEFAULT_PATH, load_experiment

    fixed = load_experiment(path or DEFAULT_PATH).fixed
    return {"max_steps": fixed["max_steps"], "max_tokens": fixed["max_tokens"]}


def _hits_json(hits: list[DefenseHit] | tuple[DefenseHit, ...]) -> list[dict[str, Any]]:
    return [h.to_json() for h in hits]


def _default_assistant_message(result: Any) -> dict[str, Any]:
    """Lượt assistant dạng OpenAI cho model không có `assistant_message` riêng."""
    message: dict[str, Any] = {"role": "assistant", "content": result.text}
    if result.tool_calls:
        message["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": tc.arguments_raw},
            }
            for tc in result.tool_calls
        ]
    return message


class CoreA:
    """Vòng lặp tool-calling. Một instance dùng lại được cho nhiều run; trạng thái run nằm ở
    `SessionState` và `messages` cục bộ của `run()`."""

    def __init__(
        self,
        *,
        model: ChatModel,
        tools: ToolLayer,
        defense: DefenseLayer,
        system_prompt: str,
        max_steps: int,
        max_tokens: int,
    ) -> None:
        for name, value in (("max_steps", max_steps), ("max_tokens", max_tokens)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} phải là số nguyên dương, nhận {value!r}")
        self.model = model
        self.tools = tools
        self.defense = defense
        self.system_prompt = system_prompt
        self.max_steps = max_steps
        self.max_tokens = max_tokens
        # LLMClient có assistant_message riêng (giữ block gốc của Messages API); bản giả thì không.
        self._assistant_message = getattr(model, "assistant_message", _default_assistant_message)

    # ------------------------------------------------------------------ run

    def run(self, user_query: str, *, session: SessionState, recorder: Recorder) -> AgentOutcome:
        tools_payload, pending_hits = self._assemble_tools(session)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_query},
        ]
        blocked = False

        for step in range(self.max_steps):
            session.step_idx = step
            result = self.model.chat(
                messages, tools=tools_payload or None, max_tokens=self.max_tokens
            )
            recorder.step(
                kind="llm",
                llm_text=result.text,
                llm_reasoning=getattr(result, "reasoning", None),
                finish_reason=result.finish_reason,
                tool_args=[
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments_raw}
                    for tc in result.tool_calls
                ]
                or None,
                defense_hits=_hits_json(pending_hits),
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                latency_ms=result.latency_ms,
                response_model=result.response_model,
            )
            pending_hits = []

            if not result.tool_calls:
                return self._outcome(
                    result.text or None, "final_answer", step + 1, session, blocked
                )
            if any(tc.parse_error for tc in result.tool_calls):
                return self._outcome(None, "parse_error", step + 1, session, blocked)

            messages.append(self._assistant_message(result))
            for call in result.tool_calls:
                executed, content = self._handle_call(call, session, recorder)
                session.history.append(executed)
                blocked = blocked or not executed.decision.allowed
                messages.append({"role": "tool", "tool_call_id": call.id, "content": content})

        return self._outcome(None, "max_steps", self.max_steps, session, blocked)

    # ------------------------------------------------------------- helpers

    def _assemble_tools(
        self, session: SessionState
    ) -> tuple[list[dict[str, Any]], list[DefenseHit]]:
        """Danh sách tool cho model; mô tả đi qua CONTEXT_ASSEMBLY (K2a)."""
        payload: list[dict[str, Any]] = []
        hits: list[DefenseHit] = []
        for spec in self.tools.list_tools():
            t = self.defense.transform(
                HookStage.CONTEXT_ASSEMBLY,
                spec.description,
                source="tool_description",
                session=session,
            )
            hits.extend(t.hits)
            payload.append(spec.to_openai(description=t.text))
        return payload, hits

    def _gate(self, call: Any, session: SessionState) -> tuple[Decision, list[DefenseHit]]:
        """PRE_TOOL_EXECUTION rồi PRE_EGRESS; dừng ở gate đầu tiên trả `block`."""
        hits: list[DefenseHit] = []
        decision = Decision()
        for stage in (HookStage.PRE_TOOL_EXECUTION, HookStage.PRE_EGRESS):
            decision = self.defense.gate(stage, call, session=session)
            hits.extend(decision.hits)
            if not decision.allowed:
                break
        return decision, hits

    def _handle_call(
        self, call: Any, session: SessionState, recorder: Recorder
    ) -> tuple[ExecutedCall, str]:
        """Một tool-call: gate → thực thi → transform. Trả bản ghi lịch sử và nội dung cho model."""
        decision, hits = self._gate(call, session)

        if not decision.allowed:
            content = f"{BLOCKED_PREFIX}: {decision.reason}" if decision.reason else BLOCKED_PREFIX
            recorder.step(
                kind="defense",
                tool_name=call.name,
                tool_args=call.arguments,
                defense_hits=_hits_json(hits),
            )
            refused = ToolResult(call_id=call.id, name=call.name, content=content, is_error=True)
            return ExecutedCall(call=call, decision=decision, result=refused), content

        raw = self.tools.call_tool(call)
        source = source_for_tool(call.name)
        first = HookStage.KB_RETRIEVAL if source == "kb_chunk" else HookStage.TOOL_RESULT
        text = raw.content
        for stage in (first, HookStage.CONTEXT_ASSEMBLY):
            t = self.defense.transform(stage, text, source=source, session=session)
            hits.extend(t.hits)
            text = t.text

        recorder.step(
            kind="tool",
            tool_name=call.name,
            tool_args=call.arguments,
            tool_result=raw.content,
            defense_hits=_hits_json(hits),
        )
        return ExecutedCall(call=call, decision=decision, result=raw), text

    @staticmethod
    def _outcome(
        answer: str | None, reason: str, n_steps: int, session: SessionState, blocked: bool
    ) -> AgentOutcome:
        return AgentOutcome(
            final_answer=answer,
            stop_reason=reason,
            n_steps=n_steps,
            tool_calls=session.history,
            defense_blocked=blocked,
        )
