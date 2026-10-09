"""Kiểm ba mô hình đích gọi được tool qua gateway — STT-26, giai đoạn 0.

Mỗi target một lời gọi tool-calling tối giản (một tool `search_kb`, một câu hỏi buộc phải tra
cứu). Đạt khi model trả đúng một tool_call `search_kb` với tham số JSON hợp lệ.

Kết quả ghi vào `results/smoke/check_targets_<UTC>.json` — file này được Git theo dõi, làm bằng
chứng điều kiện xong của giai đoạn 0. Gồm `response_model` để đối chiếu bí danh với snapshot
gateway thực sự phục vụ. Không ghi khóa API.

Chạy (tốn 3 lời gọi API ngắn):
    uv run python scripts/check_targets.py            # cả ba target
    uv run python scripts/check_targets.py A2 A3      # chỉ một số target
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agent.llm_client import LLMClient, LLMClientConfigError, LLMClientError  # noqa: E402

TARGETS = ["A1", "A2", "A3"]

SEARCH_KB_TOOL = {
    "type": "function",
    "function": {
        "name": "search_kb",
        "description": "Tra cứu kho tri thức nội bộ của công ty (báo giá, hợp đồng, chính sách).",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Câu truy vấn"}},
            "required": ["query"],
        },
    },
}

MESSAGES = [
    {
        "role": "system",
        "content": "Bạn là trợ lý nội bộ. Luôn dùng công cụ search_kb để tra cứu trước khi trả lời.",
    },
    {"role": "user", "content": "Chính sách bảo hành của công ty kéo dài bao lâu?"},
]


def check(target_id: str) -> dict:
    record: dict = {"target_id": target_id}
    try:
        client = LLMClient(
            target_id=target_id,
            config_path=ROOT / "config" / "models.yaml",
            log_path=ROOT / "logs" / "llm_client.jsonl",
        )
        result = client.chat(MESSAGES, tools=[SEARCH_KB_TOOL], max_tokens=256)
    except (LLMClientConfigError, LLMClientError) as e:
        record.update(ok=False, error=str(e))
        return record

    calls = [
        {"name": tc.name, "arguments": tc.arguments, "parse_error": tc.parse_error}
        for tc in result.tool_calls
    ]
    ok = (
        len(result.tool_calls) == 1
        and result.tool_calls[0].name == "search_kb"
        and not result.tool_calls[0].parse_error
        and bool((result.tool_calls[0].arguments or {}).get("query"))
    )
    record.update(
        ok=ok,
        model=result.model,
        response_model=result.response_model,
        tool_calls=calls,
        text=result.text,
        finish_reason=result.finish_reason,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        latency_ms=result.latency_ms,
        attempts=result.attempts,
    )
    return record


def main(argv: list[str]) -> int:
    load_dotenv(ROOT / ".env")
    targets = argv or TARGETS
    records = [check(t) for t in targets]

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out = ROOT / "results" / "smoke" / f"check_targets_{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"checked_at": stamp, "results": records}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    for r in records:
        status = "ĐẠT " if r["ok"] else "TRƯỢT"
        detail = r.get("error") or f"model={r['model']} response_model={r['response_model']}"
        print(f"[{status}] {r['target_id']}: {detail}")
    print(f"Đã ghi {out.relative_to(ROOT)}")
    return 0 if all(r["ok"] for r in records) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
