"""Sinh tập payload biến thể bằng mutator (STT-43): luật + model (opus-5) + lọc trùng embedding.

Nạp seed từ `src/attack/payloads/` (tập payload tay T1–T5), chạy `attack.mutator.mutate` rồi ghi
các biến thể MỚI ra `data/payloads_mutated.json`. KHÔNG ghi đè seed; tập sinh để riêng namespace.

Đây là bước SOẠN payload: tập còn phải qua pilot `defense=OFF` (`activation_check`, STT-60) mới vào
ma trận — file này chưa phải tập đã khóa `v-attack-1.0`. Nhánh model dùng sampling của claude-opus-5
nên tập sinh KHÔNG tất định giữa các lần chạy; mỗi biến thể model ghi xuất xứ ở trường `mutation`.

Chạy:
    uv run python scripts/gen_mutated_payloads.py              # luật + model + dedup
    uv run python scripts/gen_mutated_payloads.py --no-model   # chỉ luật + dedup (không gọi API)

Cần `.env`: ANTHROPIC_API_KEY, ATTACKER_MODEL=claude-opus-5 (khi có model). Không ghi khóa API.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
load_dotenv(ROOT / ".env")

from attack.mutator import LLMParaphraser, load_mutator_config, mutate  # noqa: E402
from attack.payloads.schema import load_payloads, load_task_meta  # noqa: E402

SEEDS_DIR = ROOT / "src" / "attack" / "payloads"
OUT_PATH = ROOT / "data" / "payloads_mutated.json"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-model", action="store_true", help="bỏ nhánh model, chỉ luật + dedup")
    ap.add_argument("--out", type=Path, default=OUT_PATH)
    args = ap.parse_args(argv)

    meta = load_task_meta()
    cfg = load_mutator_config(ROOT / "config" / "mutator.yaml")
    seeds, rep = load_payloads(SEEDS_DIR, meta=meta)
    if not rep.all_ok:
        sys.exit(f"seed không hợp lệ, dừng: {rep.errors_by_id}")

    paraphraser = None if args.no_model else LLMParaphraser()
    kept, report = mutate(seeds, cfg=cfg, meta=meta, paraphraser=paraphraser)

    n_model = sum(1 for v in kept if v.get("mutation", {}).get("by") == "model")
    print(
        f"seed={report.n_seed}  sinh={report.n_generated}  "
        f"loại_schema={report.n_rejected_schema}  trùng={report.n_deduped}  giữ={report.n_kept}  "
        f"(trong đó model={n_model}, luật={report.n_kept - n_model})"
    )
    if report.rejected:
        print(f"  loại bởi schema: {sorted(report.rejected)}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps({"payloads": kept}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"ghi {len(kept)} biến thể -> {args.out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
