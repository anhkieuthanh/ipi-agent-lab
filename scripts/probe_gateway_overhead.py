"""Đo khối token gateway chèn thêm vào prompt — hạn chế số 13, giai đoạn 0 của lộ trình code.

Overhead token của gateway không ổn định theo thời gian, nên phải chạy script này trước và sau
mỗi lô và lưu kết quả kèm dữ liệu lô đó (`Y_TUONG_DU_AN.md` mục 10.1). Hai phép đo:

  1. `floor`   — prompt ngắn nhất, không tool. `prompt_tokens` trả về gần như toàn bộ là khối
     gateway chèn: đây là số đo ĐỘ LỚN đáng tin nhất.
  2. `scaling` — prompt dài dần. Phần dôi so với tăng trưởng tuyến tính giữ nguyên ⇒ khối cố
     định; phần dôi tăng theo ⇒ gateway biến đổi nội dung gửi đi.

Mỗi phép lặp `--repeats` lần vì cùng một request có thể cho số khác nhau.

Kết quả ghi vào `results/overhead/overhead_<UTC>[_<tag>].json` (Git theo dõi).

Chạy:
    uv run python scripts/probe_gateway_overhead.py --tag truoc_lo_B1
    uv run python scripts/probe_gateway_overhead.py --targets A2 --repeats 5
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agent.llm_client import LLMClient, LLMClientConfigError, LLMClientError  # noqa: E402

FLOOR_PROMPT = "hi"
SCALING_UNIT = "Bảng giá thiết bị đo lường công nghiệp quý ba năm 2026. "
SCALING_REPEATS = [1, 20, 100]


def _tokens_in(client: LLMClient, content: str) -> int | None:
    result = client.chat([{"role": "user", "content": content}], max_tokens=1)
    return result.tokens_in


def probe(target_id: str, repeats: int) -> dict:
    record: dict = {"target_id": target_id}
    try:
        client = LLMClient(
            target_id=target_id,
            config_path=ROOT / "config" / "models.yaml",
            log_path=ROOT / "logs" / "llm_client.jsonl",
            log_bodies=False,
        )
        floor = [_tokens_in(client, FLOOR_PROMPT) for _ in range(repeats)]
        scaling = {
            n: [_tokens_in(client, SCALING_UNIT * n) for _ in range(repeats)]
            for n in SCALING_REPEATS
        }
    except (LLMClientConfigError, LLMClientError) as e:
        record.update(ok=False, error=str(e))
        return record

    def summary(values: list[int | None]) -> dict:
        known = [v for v in values if v is not None]
        return {
            "values": values,
            "min": min(known) if known else None,
            "max": max(known) if known else None,
            "median": statistics.median(known) if known else None,
        }

    # Hệ số token/đơn vị ước từ hai điểm xa nhất; chặn = phần không tỉ lệ theo độ dài prompt.
    lo, hi = SCALING_REPEATS[0], SCALING_REPEATS[-1]
    med_lo, med_hi = summary(scaling[lo])["median"], summary(scaling[hi])["median"]
    slope = intercept = None
    if med_lo is not None and med_hi is not None:
        slope = (med_hi - med_lo) / (hi - lo)
        intercept = med_lo - slope * lo

    record.update(
        ok=True,
        model=client.model,
        floor=summary(floor),
        scaling={str(n): summary(v) for n, v in scaling.items()},
        tokens_per_unit=slope,
        fixed_overhead_estimate=intercept,
    )
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--targets", nargs="+", default=["A1", "A2", "A3"])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--tag", default="", help="Nhãn lô, vd truoc_lo_B1 / sau_lo_B1")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    records = [probe(t, args.repeats) for t in args.targets]

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    suffix = f"_{args.tag}" if args.tag else ""
    out = ROOT / "results" / "overhead" / f"overhead_{stamp}{suffix}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"measured_at": stamp, "tag": args.tag, "repeats": args.repeats, "results": records}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for r in records:
        if not r["ok"]:
            print(f"[LỖI] {r['target_id']}: {r['error']}")
            continue
        f = r["floor"]
        print(
            f"[{r['target_id']}] floor min/median/max = {f['min']}/{f['median']}/{f['max']} · "
            f"overhead cố định ước ≈ {r['fixed_overhead_estimate']}"
        )
    print(f"Đã ghi {out.relative_to(ROOT)}")
    return 0 if all(r["ok"] for r in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
