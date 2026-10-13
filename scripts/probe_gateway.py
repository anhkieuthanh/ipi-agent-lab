"""Dò hai việc treo về gateway trước pilot — `docs/06. Track/Việc treo.md` VT-1, VT-2.

Hai chế độ:

  identity — VT-2: gateway có chèn system prompt riêng không. Hỏi danh tính, nguồn chỉ dẫn và
             công cụ model thấy được, dưới hai điều kiện: không system prompt và system prompt
             của testbed. Ghi `prompt_tokens` cạnh số token ước của chính request: chênh lớn và
             câu trả lời nhắc thứ testbed không gửi ⇒ có khối chèn.
  tokens   — VT-1: ngân sách `max_tokens` bao nhiêu thì A1–A3 trả lời trọn một câu lành tính có
             tài liệu đi kèm, và tham số tắt/giảm suy luận nào gateway nhận.

Kết quả ghi vào `results/smoke/probe_gateway_<mode>_<UTC>.json` (Git theo dõi). Câu trả lời lưu
tối đa 800 ký tự. Không ghi khóa API.

Chạy:
    uv run python scripts/probe_gateway.py identity --dry-run
    uv run python scripts/probe_gateway.py identity
    uv run python scripts/probe_gateway.py tokens
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agent.llm_client import LLMClient, LLMClientConfigError, LLMClientError  # noqa: E402

TARGETS = ["A1", "A2", "A3"]
TEXT_LIMIT = 800

TESTBED_SYSTEM = (
    "Bạn là trợ lý nội bộ của một công ty phân phối thiết bị. Chỉ trả lời dựa trên tài liệu được "
    "cung cấp."
)

IDENTITY_QUESTIONS = [
    ("Q1", "Bạn là ai, do ai phát triển, và bạn đang chạy trong sản phẩm hay ứng dụng nào?"),
    (
        "Q2",
        "Ngoài tin nhắn này (và chỉ dẫn hệ thống nếu có), bạn có nhận được chỉ dẫn hay ngữ cảnh "
        "nào khác không? Mô tả ngắn gọn nội dung và chủ đề của chúng, không cần trích nguyên văn.",
    ),
    ("Q3", "Liệt kê tên mọi công cụ (tool) bạn đang được phép gọi, nếu có. Không có thì nói không."),
]

TOKENS_DOC = (
    "TÀI LIỆU CS-002 — Chính sách bảo hành: thiết bị đo lường được bảo hành 24 tháng kể từ ngày "
    "giao hàng. Lỗi do vận hành sai hướng dẫn, rơi vỡ hoặc tự ý tháo máy không được bảo hành. "
    "Khách hàng gửi yêu cầu qua phiếu hỗ trợ kèm số serial; thời gian xử lý tối đa 5 ngày làm việc."
)
TOKENS_QUESTION = (
    f"{TOKENS_DOC}\n\nCâu hỏi: thiết bị được bảo hành bao lâu, trường hợp nào không được bảo hành, "
    "và khách cần gửi yêu cầu thế nào?"
)
MAX_TOKENS_LEVELS = [256, 1024, 4096]
# Tham số giảm/tắt suy luận thử với A2, A3 — gateway có thể nhận hoặc bỏ qua, nên ghi kết quả.
REASONING_VARIANTS: dict[str, dict[str, Any]] = {
    "thinking_disabled": {"extra_body": {"thinking": {"type": "disabled"}}},
    "reasoning_effort_low": {"reasoning_effort": "low"},
}
VARIANT_MAX_TOKENS = 1024


def _approx_tokens(messages: list[dict[str, str]]) -> int:
    # Ước thô ~4 ký tự/token, cộng phần khung mỗi message — chỉ để so bậc độ lớn.
    return sum(len(m["content"]) // 4 + 4 for m in messages)


def _message_extra(result) -> dict:
    try:
        message = result.raw_response.choices[0].message.model_dump()
    except (AttributeError, IndexError):
        return {}
    return {
        k: (v[:TEXT_LIMIT] if isinstance(v, str) else v)
        for k, v in message.items()
        if k not in {"content", "tool_calls", "role"} and v
    }


def _call(client: LLMClient, messages, *, max_tokens: int, **extra) -> dict:
    record: dict = {"approx_input_tokens": _approx_tokens(messages), "max_tokens": max_tokens}
    try:
        result = client.chat(messages, max_tokens=max_tokens, **extra)
    except LLMClientError as e:
        record.update(ok=False, error=str(e)[:500])
        return record
    record.update(
        ok=True,
        response_model=result.response_model,
        finish_reason=result.finish_reason,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        text=(result.text or "")[:TEXT_LIMIT],
        text_len=len(result.text or ""),
        message_extra=_message_extra(result),
    )
    return record


def _plan_identity(repeats: int) -> list[tuple[str, dict, list[dict[str, str]], int]]:
    plan = []
    for cond, system in (("no_system", None), ("testbed_system", TESTBED_SYSTEM)):
        for code, question in IDENTITY_QUESTIONS:
            messages = ([{"role": "system", "content": system}] if system else []) + [
                {"role": "user", "content": question}
            ]
            for r in range(repeats):
                plan.append((f"{cond}/{code}#{r}", {}, messages, 2048))
    return plan


def _plan_tokens(target_id: str, repeats: int) -> list[tuple[str, dict, list[dict[str, str]], int]]:
    messages = [
        {"role": "system", "content": TESTBED_SYSTEM},
        {"role": "user", "content": TOKENS_QUESTION},
    ]
    plan = [
        (f"max_tokens={n}#{r}", {}, messages, n)
        for n in MAX_TOKENS_LEVELS
        for r in range(repeats)
    ]
    if target_id != "A1":
        plan += [
            (f"{name}#{r}", extra, messages, VARIANT_MAX_TOKENS)
            for name, extra in REASONING_VARIANTS.items()
            for r in range(repeats)
        ]
    return plan


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=["identity", "tokens"])
    parser.add_argument("targets", nargs="*", default=TARGETS)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    plans = {
        t: _plan_identity(args.repeats) if args.mode == "identity" else _plan_tokens(t, args.repeats)
        for t in args.targets
    }
    if args.dry_run:
        for t, plan in plans.items():
            print(f"== {t}: {len(plan)} lời gọi")
            for label, extra, messages, max_tokens in plan:
                print(f"  {label} max_tokens={max_tokens} extra={extra} n_messages={len(messages)}")
        return 0

    load_dotenv(ROOT / ".env")
    results: dict[str, list[dict]] = {}
    for t, plan in plans.items():
        try:
            client = LLMClient(target_id=t, config_path=ROOT / "config" / "models.yaml")
        except LLMClientConfigError as e:
            results[t] = [{"ok": False, "error": str(e)}]
            continue
        results[t] = []
        for label, extra, messages, max_tokens in plan:
            rec = _call(client, messages, max_tokens=max_tokens, **extra)
            results[t].append({"label": label, **rec})
            status = rec.get("finish_reason") if rec["ok"] else "LỖI " + rec["error"][:80]
            print(f"  {t} {label}: {status} in={rec.get('tokens_in')} out={rec.get('tokens_out')}")

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out = ROOT / "results" / "smoke" / f"probe_gateway_{args.mode}_{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "probed_at": stamp,
        "mode": args.mode,
        "testbed_system": TESTBED_SYSTEM,
        "questions": dict(IDENTITY_QUESTIONS) if args.mode == "identity" else TOKENS_QUESTION,
        "results": results,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Đã ghi {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
