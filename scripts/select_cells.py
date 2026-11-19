"""Áp quy tắc chọn ô (S_def cho B2 từ B1, S_adp cho B5 từ B2) lên một lô nguồn — ghi bằng chứng JSON.

Quy tắc và tham số đọc từ `config/experiment.yaml` (`blocks.<khối>.cells`), không tham số dòng
lệnh nào đổi được quy tắc. Kết quả ghi vào `results/cell_select/<khối>_<UTC>.json` (Git theo dõi);
`cells.selected` và `cells.source_batch` của config điền theo đúng file đó — `--write-config` điền
thay hai dòng `null` của khối, giữ nguyên chú thích của file.

Chạy (không gọi API):
    uv run python scripts/select_cells.py --block B2 --source-batch attack-B1-baseline-20261118T090849Z
    uv run python scripts/select_cells.py --block B5 --source-batch attack-B2-... --write-config
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from attack.runner import build_defenses, snapshot_json  # noqa: E402
from eval.cell_select import (  # noqa: E402
    CellSelectError,
    cell_stats,
    dsr_stats,
    select_s_adp,
    select_s_def,
)
from eval.experiment import load_experiment  # noqa: E402
from interfaces import NoDefense  # noqa: E402

OUT = ROOT / "results" / "cell_select"
CONFIG = ROOT / "config" / "experiment.yaml"


def write_config(block_id: str, source_batch: str, selected: list[list[str]]) -> None:
    """Điền `source_batch` và `selected` (đang `null`) trong khối `blocks.<block_id>.cells`."""
    lines = CONFIG.read_text(encoding="utf-8").splitlines(keepends=True)
    start = next(i for i, ln in enumerate(lines) if ln.rstrip() == f"  {block_id}:")
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].startswith("  ") and not lines[i].startswith("   ")
                and lines[i].strip()), len(lines))
    hits = {}
    for i in range(start, end):
        key = lines[i].strip()
        if key in ("source_batch: null", "selected: null"):
            hits[key.split(":")[0]] = i
    if set(hits) != {"source_batch", "selected"}:
        raise SystemExit(f"blocks.{block_id}.cells không còn source_batch/selected null để điền")
    line = lines[hits["selected"]]
    indent = line[: len(line) - len(line.lstrip())]
    lines[hits["source_batch"]] = f"{indent}source_batch: {source_batch}\n"
    lines[hits["selected"]] = f"{indent}selected:\n" + "".join(
        f"{indent}  - [{', '.join(c)}]\n" for c in selected
    )
    CONFIG.write_text("".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--block", required=True, help="khối chọn ô theo quy tắc (B2, B5)")
    parser.add_argument("--source-batch", required=True, help="lô của khối nguồn")
    parser.add_argument("--write-config", action="store_true",
                        help="điền cells.selected/source_batch vào experiment.yaml")
    args = parser.parse_args()

    exp = load_experiment()
    block = exp.unit(args.block)
    cells = block.cells or {}
    if not args.source_batch.startswith(f"attack-{cells.get('from_block')}-"):
        parser.error(f"lô nguồn của {args.block} phải là lô attack-{cells.get('from_block')}-…")
    store = ROOT / "results" / "attack_matrix" / args.source_batch / "trace.sqlite"
    targets = [t for t in block.targets if t is not None]
    if cells.get("rule") == "S_adp":
        return _s_adp(args, exp, block, cells, store, targets)
    if cells.get("rule") != "S_def":
        parser.error(f"khối {args.block} không chọn ô theo quy tắc")
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
    if args.write_config:
        write_config(args.block, args.source_batch, record["selected"])
        print(f"Đã điền blocks.{args.block}.cells vào {CONFIG.relative_to(ROOT)}")
    return 0


def _s_adp(args, exp, block, cells, store, targets) -> int:
    source = exp.unit(cells["from_block"])
    singles = [p for p in source.presets if p.endswith("_only")]
    presets = dict(zip(build_defenses(singles), singles, strict=True))  # ảnh chụp JSON → tên
    candidates = [tuple(c) for c in source.cells["selected"]]
    try:
        stats = dsr_stats(store, targets, presets, candidates,
                          off_config=snapshot_json(NoDefense()))
        chosen, short = select_s_adp(stats, min_dsr_blind=float(cells["min_dsr_blind"]),
                                     max_cells=int(cells["max_cells"]))
    except CellSelectError as e:
        print(f"Không chọn được: {e}")
        return 2
    n_pass = sum(c.best >= float(cells["min_dsr_blind"]) for c in stats)
    print(f"{args.source_batch}: {len(stats)} ô S_def, {n_pass} ô có DSR đơn lẻ ≥ "
          f"{cells['min_dsr_blind']}" + (" — thiếu ô đạt, lấy DSR cao nhất" if short else ""))
    for i, c in enumerate(chosen, 1):
        per = " ".join(f"{p} {1 - s / n:.2f}" for p, (s, n) in sorted(c.by_preset.items()) if n)
        print(f"  {i}. {'·'.join(c.cell)}  DSR {per}  ASR(off) {c.off_asr:.2f}")

    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = OUT / f"{args.block}_{stamp}.json"
    record = {
        "block": args.block, "rule": cells["rule"], "min_dsr_blind": cells["min_dsr_blind"],
        "max_cells": cells["max_cells"], "rank_by": cells.get("rank_by"), "targets": targets,
        "source_batch": args.source_batch, "n_cells": len(stats), "n_passing": n_pass,
        "short": short, "selected": [list(c.cell) for c in chosen],
        "stats": [{"cell": list(c.cell), "by_preset": c.by_preset, "off": c.off,
                   "best_dsr": c.best, "off_asr": c.off_asr} for c in stats],
    }
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Đã ghi {path.relative_to(ROOT)}")
    if args.write_config:
        write_config(args.block, args.source_batch, record["selected"])
        print(f"Đã điền blocks.{args.block}.cells vào {CONFIG.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
