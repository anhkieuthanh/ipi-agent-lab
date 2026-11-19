"""Áp quy tắc chọn ô S_def (B2) lên một lô nguồn của B1 — in ô chọn, ghi bằng chứng JSON.

Quy tắc và tham số đọc từ `config/experiment.yaml` (`blocks.<khối>.cells`), không tham số dòng
lệnh nào đổi được quy tắc. Kết quả ghi vào `results/cell_select/<khối>_<UTC>.json` (Git theo dõi);
`cells.selected` và `cells.source_batch` của config điền theo đúng file đó.

Chạy (không gọi API):
    uv run python scripts/select_cells.py --block B2 --source-batch attack-B1-baseline-20261118T090849Z
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from eval.cell_select import CellSelectError, cell_stats, select_s_def  # noqa: E402
from eval.experiment import load_experiment  # noqa: E402

OUT = ROOT / "results" / "cell_select"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--block", required=True, help="khối chọn ô theo quy tắc S_def (B2)")
    parser.add_argument("--source-batch", required=True, help="lô B1 làm nguồn")
    args = parser.parse_args()

    exp = load_experiment()
    block = exp.unit(args.block)
    cells = block.cells or {}
    if cells.get("rule") != "S_def":
        parser.error(f"khối {args.block} không chọn ô theo S_def")
    store = ROOT / "results" / "attack_matrix" / args.source_batch / "trace.sqlite"
    targets = [t for t in block.targets if t is not None]
    try:
        stats = cell_stats(store, targets)
        chosen, floor = select_s_def(
            stats, min_ci_low=float(cells["min_ci_low"]), max_cells=int(cells["max_cells"])
        )
    except CellSelectError as e:
        print(f"Không chọn được: {e}")
        return 2
    n_pass = sum(c.passes(float(cells["min_ci_low"])) for c in stats)
    print(f"{args.source_batch}: {len(stats)} ô, {n_pass} ô đạt cận dưới ≥ {cells['min_ci_low']}"
          + (" — ASR sàn" if floor else ""))
    for i, c in enumerate(chosen, 1):
        per = " ".join(f"{t} {s}/{n}" for t, (s, n) in sorted(c.by_target.items()))
        print(f"  {i}. {'·'.join(c.cell)}  {per}  gộp {c.pooled:.2f}")

    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = OUT / f"{args.block}_{stamp}.json"
    record = {
        "block": args.block,
        "rule": cells["rule"],
        "min_ci_low": cells["min_ci_low"],
        "max_cells": cells["max_cells"],
        "rank_by": "pooled",
        "targets": targets,
        "source_batch": args.source_batch,
        "n_cells": len(stats),
        "n_passing": n_pass,
        "floor": floor,
        "selected": [list(c.cell) for c in chosen],
        "stats": [
            {"cell": list(c.cell), "by_target": c.by_target, "pooled": c.pooled,
             "passes": c.passes(float(cells["min_ci_low"]))}
            for c in sorted(stats, key=lambda c: (-c.pooled, c.cell))
        ],
    }
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Đã ghi {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
