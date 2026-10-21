"""LLM judge chấm `judge_pass` cho run lành tính — STT-37, `Y_TUONG_DU_AN.md` mục 12.3.

`pass ⟺ judge_pass ∧ hard_fact_pass`: judge quyết pass/fail theo `judge_rubric` của câu, scorer giữ
quyền veto dữ kiện cứng. Module này chỉ sinh `judge_pass`; scorer nhận nó qua `ScoreContext` và
không tự gọi model.

    cfg = JudgeConfig.load()
    client = LLMClient(JUDGE_ID)
    verdict = judge_run(client, query_spec, final_answer, rec.steps, cfg=cfg)
    score(rec, ScoreContext(runtime=..., judge_pass=verdict.judge_pass,
                            judge_model=verdict.judge_model))

Ba quy ước:

- **Không có câu trả lời cuối** (run hết `max_steps`, câu rỗng) ⇒ `judge_pass = False`, KHÔNG gọi
  judge, `judge_model = None`: không có gì để chấm, và không ghi tên model cho một phán quyết nó
  không đưa ra.
- **Judge trả lời không parse được** (không phải JSON `{"pass": bool, "reason": str}`, hoặc chạm
  `max_tokens`) ⇒ `JudgeError`, không retry. Runner để lỗi lan ra trong `with TraceRecorder`, run
  thành `parse_error` loại (c) của mục 12.4 và rời `N_clean`.
- **Judge thấy những gì agent đã làm**: tool-call đã thực thi kèm kết quả thô (bước `tool`), tool-call
  bị chặn (bước `defense`), câu trả lời cuối. Tiêu chí kiểu "đúng thông tin của đúng khách hàng" chỉ
  chấm được khi judge đối chiếu với kết quả công cụ. Judge cũng nhận ngày tham chiếu agent thấy trong
  system prompt (`fixed.reference_date`) — thiếu nó, câu tính hạn bị đánh trượt oan.

Văn bản prompt và giới hạn cắt nằm ở `config/prompts.yaml` khối `judge`; model ở `config/models.yaml`
khối `judge`. `JudgeConfig.prompt_hash()` băm khối prompt để bản CSV tách lượt chấm trước/sau khi sửa.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

__all__ = [
    "JudgeConfig",
    "JudgeConfigError",
    "JudgeError",
    "JudgeVerdict",
    "build_messages",
    "format_tool_calls",
    "judge_run",
    "parse_verdict",
]

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = REPO_ROOT / "config" / "prompts.yaml"

_KEYS = frozenset(
    {"system", "user_template", "max_tool_result_chars", "max_answer_chars", "max_tokens"}
)
_PLACEHOLDERS = {"reference_date", "query", "rubric", "tool_calls", "answer"}
_FENCE = re.compile(r"^```(?:json)?\s*(?P<body>.*?)\s*```$", re.DOTALL)
TRUNCATED = "…[đã cắt]"
NO_TOOL_CALLS = "(không gọi công cụ nào)"


class JudgeConfigError(ValueError):
    """Khối `judge` của prompts.yaml sai hợp đồng."""


class JudgeError(RuntimeError):
    """Judge trả lời không chấm được — lỗi tầng harness, run thành `parse_error` (mục 12.4 (c))."""


@dataclass(frozen=True)
class JudgeConfig:
    system: str
    user_template: str
    max_tool_result_chars: int
    max_answer_chars: int
    max_tokens: int
    #: "Hôm nay" của agent (dd/mm/yyyy), từ `fixed.reference_date` của experiment.yaml.
    reference_date: str

    @classmethod
    def load(
        cls, path: str | Path = DEFAULT_PATH, experiment_path: str | Path | None = None
    ) -> JudgeConfig:
        raw = (yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}).get("judge")
        if not isinstance(raw, dict):
            raise JudgeConfigError(f"{path}: thiếu khối 'judge'")
        problems = [f"khóa lạ judge.{k}" for k in sorted(set(raw) - _KEYS)]
        problems += [f"thiếu judge.{k}" for k in sorted(_KEYS - set(raw))]
        if problems:
            raise JudgeConfigError(f"{path}: " + "; ".join(problems))
        for key in ("system", "user_template"):
            if not isinstance(raw[key], str) or not raw[key].strip():
                problems.append(f"judge.{key} phải là chuỗi khác rỗng")
        for key in ("max_tool_result_chars", "max_answer_chars", "max_tokens"):
            value = raw[key]
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                problems.append(f"judge.{key} phải là số nguyên dương")
        if not problems:
            found = set(re.findall(r"(?<!\{)\{(\w+)\}(?!\})", raw["user_template"]))
            if found != _PLACEHOLDERS:
                problems.append(
                    f"judge.user_template phải có đúng biến {sorted(_PLACEHOLDERS)}, có {sorted(found)}"
                )
        if problems:
            raise JudgeConfigError(f"{path}: " + "; ".join(problems))
        from eval.experiment import DEFAULT_PATH as EXPERIMENT_PATH
        from eval.experiment import load_experiment

        ref = load_experiment(experiment_path or EXPERIMENT_PATH).fixed.get("reference_date")
        if ref is None:
            raise JudgeConfigError("experiment.yaml: fixed.reference_date chưa chốt")
        today = date.fromisoformat(str(ref)).strftime("%d/%m/%Y")
        return cls(**{k: raw[k] for k in _KEYS}, reference_date=today)

    def prompt_hash(self) -> str:
        """sha256 của khối judge — đổi prompt hay giới hạn cắt thì hash đổi."""
        blob = json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class JudgeVerdict:
    judge_pass: bool
    judge_model: str | None
    reason: str
    called: bool  # False: không có câu trả lời cuối, không gọi judge


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + TRUNCATED


def _step_value(step: Any, name: str) -> Any:
    return step[name] if isinstance(step, dict) else getattr(step, name)


def format_tool_calls(steps: list[Any], *, max_result_chars: int) -> str:
    """Tool-call của run theo thứ tự, từ bước `tool` (đã chạy) và `defense` (bị chặn) của trace."""
    lines: list[str] = []
    ordered = sorted(steps, key=lambda s: _step_value(s, "step_idx"))
    calls = [s for s in ordered if _step_value(s, "kind") in ("tool", "defense")]
    for n, step in enumerate(calls, start=1):
        kind = _step_value(step, "kind")
        name = _step_value(step, "tool_name")
        args = _step_value(step, "tool_args") or "{}"
        lines.append(f"{n}. {name} {args}")
        if kind == "defense":
            lines.append("   → bị chặn, không thực thi")
        else:
            result = _step_value(step, "tool_result") or ""
            lines.append(f"   → {_cut(result, max_result_chars)}")
    return "\n".join(lines) if lines else NO_TOOL_CALLS


def build_messages(
    *, query: str, rubric: str, tool_calls: str, answer: str, cfg: JudgeConfig
) -> list[dict[str, str]]:
    """Messages dạng OpenAI cho judge. Hàm thuần."""
    user = cfg.user_template.format(
        reference_date=cfg.reference_date,
        query=query,
        rubric=rubric,
        tool_calls=tool_calls,
        answer=_cut(answer, cfg.max_answer_chars),
    )
    return [{"role": "system", "content": cfg.system}, {"role": "user", "content": user}]


def parse_verdict(text: str | None) -> tuple[bool, str]:
    """`(pass, reason)` từ câu trả lời judge. Chỉ nhận một đối tượng JSON, có thể bọc rào ```json."""
    body = (text or "").strip()
    fenced = _FENCE.match(body)
    if fenced:
        body = fenced["body"]
    try:
        obj = json.loads(body)
    except json.JSONDecodeError as e:
        raise JudgeError(f"judge không trả JSON: {body[:200]!r}") from e
    if not isinstance(obj, dict) or set(obj) != {"pass", "reason"}:
        raise JudgeError(f"judge trả JSON sai khóa: {body[:200]!r}")
    if not isinstance(obj["pass"], bool) or not isinstance(obj["reason"], str):
        raise JudgeError(f"judge trả JSON sai kiểu: {body[:200]!r}")
    return obj["pass"], obj["reason"]


def judge_run(
    client: Any,
    query_spec: dict[str, Any],
    final_answer: str | None,
    steps: list[Any],
    *,
    cfg: JudgeConfig,
) -> JudgeVerdict:
    """Chấm một run lành tính. `client` là `LLMClient(JUDGE_ID)` hoặc bản giả cùng `chat()`."""
    if not final_answer or not final_answer.strip():
        return JudgeVerdict(False, None, "không có câu trả lời cuối", called=False)
    messages = build_messages(
        query=query_spec["user_query_vi"],
        rubric=query_spec["expected_answer"]["judge_rubric"],
        tool_calls=format_tool_calls(steps, max_result_chars=cfg.max_tool_result_chars),
        answer=final_answer,
        cfg=cfg,
    )
    result = client.chat(messages, max_tokens=cfg.max_tokens)
    if result.finish_reason == "length":
        raise JudgeError("judge chạm max_tokens, câu trả lời cụt")
    passed, reason = parse_verdict(result.text)
    return JudgeVerdict(passed, client.model, reason, called=True)
