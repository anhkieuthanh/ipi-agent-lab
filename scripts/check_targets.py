#!/usr/bin/env python3
"""Đo tỉ lệ tool-calling hợp lệ của 3 model đích — bằng chứng cho W1-11 và W2-02.

Gộp hai script cũ (`test_target_models.py` gọi thẳng `openai.OpenAI`, và
`smoke_test_llm_client.py` gọi 1 lần qua `LLMClient`) làm một, vì hai DoD chỉ
khác nhau ở số lần lặp chứ không khác phép đo:

  - **W1-11**: "3/3 model trả `tool_calls` hợp lệ. Tỉ lệ đúng định dạng của
    model local được ghi lại" → chạy N=10 lần/target, lấy tỉ lệ.
  - **W2-02**: "đổi target chỉ bằng đổi 1 chuỗi; 3/3 model gọi được tool" →
    chính script này đi qua `LLMClient(target_id=...)`, không đụng `openai`
    trực tiếp, nên chạy được tức là lớp chuẩn hóa/retry/log dùng chung hoạt
    động với cả 3 target.

Gọi qua `LLMClient` còn có tác dụng phụ quan trọng: mọi lần gọi được ghi vào
`logs/llm_client.jsonl`, tức bằng chứng cho DoD tự tích lũy chứ không phải chép
tay từ màn hình.

Cách chạy (cần `.env` đã điền — xem `.env.example`, và LM Studio bật cổng 1234
cho target `local`):

    cd ipi-agent-lab
    uv run python scripts/check_targets.py                 # cả 3 target, 10 lần
    uv run python scripts/check_targets.py --targets local # chỉ model local
    uv run python scripts/check_targets.py --trials 3      # chạy nhanh khi debug

Đầu ra: bảng Markdown dán thẳng vào `docs/technical_notes/local_model_notes.md`
mục "Kết quả đo", kèm file JSON chi tiết từng lần gọi ở
`logs/w1_11_tool_call_results.json`.

Lưu ý về phép đo: `LLMClient` chỉ retry lỗi tầng vận chuyển (429/5xx/timeout),
KHÔNG retry khi model trả sai định dạng — nên tỉ lệ ở đây là tỉ lệ đúng định
dạng thật của model, không bị lớp retry làm đẹp.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agent.llm_client import (  # noqa: E402
    LLMClient,
    LLMClientConfigError,
    LLMClientError,
    LLMResult,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TARGETS = ["api1", "api2", "local"]
DEFAULT_TRIALS = 10
RESULT_PATH = REPO_ROOT / "logs" / "w1_11_tool_call_results.json"

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Lấy thời tiết hiện tại của một thành phố.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "Tên thành phố, vd 'Hà Nội'"},
                    "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
                },
                "required": ["city"],
            },
        },
    }
]

PROMPT = (
    "Cho tôi biết thời tiết hiện tại ở Đà Nẵng, đơn vị celsius. "
    "Dùng công cụ được cung cấp để trả lời."
)


def validate(result: LLMResult) -> tuple[bool, str]:
    """Một lần gọi được tính HỢP LỆ khi và chỉ khi cả 4 điều kiện dưới đây đúng.

    Đây là định nghĩa "đúng định dạng" mà `local_model_notes.md` báo cáo, và
    cũng là điều kiện mà harness W3 dựa vào để phân biệt "model không chịu gọi
    tool" với "model gọi tool nhưng hỏng cú pháp" (nhãn `parse_error` của W1-10,
    run mang nhãn này bị loại khỏi mẫu ASR).
    """
    if not result.tool_calls:
        return False, "khong_co_tool_calls"
    call = result.tool_calls[0]
    if call.name != "get_weather":
        return False, f"sai_ten_ham:{call.name}"
    if call.parse_error:
        return False, "json_khong_hop_le"
    if "city" not in (call.arguments or {}):
        return False, "thieu_truong_bat_buoc:city"
    return True, "ok"


def run_target(target_id: str, trials: int) -> dict:
    print(f"\n=== target_id={target_id} ===")
    try:
        client = LLMClient(target_id=target_id)
    except LLMClientConfigError as e:
        print(f"  BỎ QUA (chưa cấu hình): {e}")
        return {"status": "skip", "reason": str(e), "trials": []}

    print(f"  label={client.label} model={client.model} base_url={client.base_url}")
    records = []
    for i in range(1, trials + 1):
        try:
            result = client.chat(
                messages=[{"role": "user", "content": PROMPT}], tools=TOOLS, temperature=0
            )
        except LLMClientError as e:
            records.append({"i": i, "ok": False, "reason": f"loi_goi:{e}", "latency_ms": None})
            print(f"  [{i:2d}/{trials}] LỖI GỌI: {e}")
            continue
        ok, reason = validate(result)
        records.append(
            {
                "i": i,
                "ok": ok,
                "reason": reason,
                "latency_ms": result.latency_ms,
                "attempts": result.attempts,
                "tokens_in": result.tokens_in,
                "tokens_out": result.tokens_out,
            }
        )
        print(f"  [{i:2d}/{trials}] ok={ok} reason={reason} latency={result.latency_ms}ms")

    return {
        "status": "ran",
        "model": client.model,
        "label": client.label,
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "trials": records,
    }


def merge_with_previous(results: dict[str, dict]) -> dict[str, dict]:
    """Gộp kết quả lần này với file cũ, KHÔNG để mất số đo đã có.

    File kết quả là BẰNG CHỨNG cho DoD W1-11, mà ba target hiếm khi sẵn sàng
    cùng lúc: LM Studio phải bật tay, khóa API phải có trong `.env`. Ghi đè
    thẳng thì một lần chạy thiếu target sẽ xóa mất lượt đo đã tốn công có.

    Hai đường làm mất số, phải bịt cả hai:
      1. Target có trong `--targets` nhưng `skip` (thiếu biến môi trường).
      2. Target KHÔNG có trong `--targets` — ví dụ `--targets local` thì api1,
         api2 biến mất hoàn toàn khỏi `results`, không rơi vào nhánh (1).

    Bản đo cũ được giữ lại kèm `from_previous_run` và `measured_at` để người
    đọc biết các dòng trong bảng không nhất thiết cùng một lần chạy.
    """
    if not RESULT_PATH.exists():
        return results

    try:
        previous = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[cảnh báo] không đọc được {RESULT_PATH} ({e}) — bỏ qua bước merge.")
        return results

    prev_results = previous.get("results", {})
    prev_stamp = previous.get("generated_at")

    def keep_old(target_id: str, old: dict, skip_reason: str | None) -> dict:
        kept = dict(old)
        kept["from_previous_run"] = True
        kept["measured_at"] = old.get("measured_at", prev_stamp)
        if skip_reason is not None:
            kept["skip_reason_this_run"] = skip_reason
        print(f"[merge] `{target_id}` không đo lần này — giữ lại số đo {kept['measured_at']}.")
        return kept

    merged: dict[str, dict] = {}
    for target_id, data in results.items():
        old = prev_results.get(target_id)
        if data["status"] == "skip" and old and old.get("status") == "ran":
            merged[target_id] = keep_old(target_id, old, data.get("reason"))
        else:
            merged[target_id] = data

    # (2) Target vắng mặt khỏi lần chạy này.
    for target_id, old in prev_results.items():
        if target_id not in merged and old.get("status") == "ran":
            merged[target_id] = keep_old(target_id, old, None)

    # Giữ thứ tự khai báo trong config để bảng không nhảy dòng giữa các lần chạy.
    order = {tid: i for i, tid in enumerate(DEFAULT_TARGETS)}
    return dict(sorted(merged.items(), key=lambda kv: order.get(kv[0], len(order))))


def summarize(results: dict[str, dict], trials: int) -> int:
    """In bảng Markdown + trả về số target đạt (≥1 lần hợp lệ)."""
    print("\n\n===== BẢNG DÁN VÀO docs/technical_notes/local_model_notes.md =====\n")
    print("| Target | Model | Hợp lệ / Tổng | Tỉ lệ | Latency trung vị (ms) | Đo lúc |")
    print("|---|---|---|---|---|---|")
    n_pass = 0
    for target_id, data in results.items():
        if data["status"] == "skip":
            print(f"| `{target_id}` | — | — | — | — | chưa cấu hình |")
            continue
        oks = [t for t in data["trials"] if t["ok"]]
        lats = sorted(t["latency_ms"] for t in data["trials"] if t["latency_ms"] is not None)
        median = lats[len(lats) // 2] if lats else None
        rate = 100 * len(oks) / len(data["trials"]) if data["trials"] else 0.0
        if oks:
            n_pass += 1
        stamp = (data.get("measured_at") or "—")[:19].replace("T", " ")
        if data.get("from_previous_run"):
            stamp += " (lượt trước)"
        print(
            f"| `{target_id}` | `{data['model']}` | {len(oks)}/{len(data['trials'])} | "
            f"{rate:.0f}% | {median if median is not None else '—'} | {stamp} |"
        )

    print(f"\nDoD W1-11 / W2-02: {n_pass}/{len(results)} target trả tool_calls hợp lệ "
          f"ít nhất 1 lần trong {trials} lần thử (yêu cầu 3/3).")
    return n_pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", nargs="+", default=DEFAULT_TARGETS,
                        help=f"target_id trong config/models.yaml (mặc định: {DEFAULT_TARGETS})")
    parser.add_argument("--trials", type=int, default=DEFAULT_TRIALS,
                        help=f"số lần gọi mỗi target (mặc định: {DEFAULT_TRIALS})")
    args = parser.parse_args()

    results = {tid: run_target(tid, args.trials) for tid in args.targets}
    results = merge_with_previous(results)
    n_pass = summarize(results, args.trials)

    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                # Số lần của LẦN CHẠY NÀY. Không suy ra được cỡ mẫu của target
                # giữ lại từ lượt trước (`from_previous_run`) — cỡ mẫu thật của
                # mỗi target là len(results[tid]["trials"]).
                "trials_this_run": args.trials,
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Chi tiết từng lần gọi: {RESULT_PATH}")

    # Exit code khác 0 khi chưa đủ 3/3 — để dùng được trong checklist tự động.
    return 0 if n_pass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
