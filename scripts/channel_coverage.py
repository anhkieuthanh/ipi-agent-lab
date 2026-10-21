"""Bảng phủ kênh K1 × K2a/K2b của corpus payload, kiểm chỉ tiêu ≥80% — STT-41.

Đặc tả: `docs/04. Design/payload_taxonomy.md` mục 2.3. Với phân kênh `k` ∈ {K2a, K2b}: tử số là số
kỹ thuật có ít nhất một payload hợp lệ dựng được ở CẢ K1 và `k`; mẫu số (theo ma trận) là số kỹ thuật
có trong corpus VÀ dựng được ở `k` theo mục 2.1 (ô ✗ là ràng buộc kiến trúc, không tính là thiếu).
Bảng ghi thêm tỉ lệ thô (mẫu số là mọi kỹ thuật trong corpus) để thấy phần bị loại bởi kiến trúc.

"Dựng được ở kênh" = payload qua validator (`load_payloads`) VÀ `render_for_channel` không lỗi ở kênh.

Ghi `results/tables/channel_coverage.csv` (đường dẫn ở `config/channel_render.yaml` khóa coverage).
Mã thoát 0 khi mọi phân kênh đạt `min_ratio`, 1 khi có phân kênh hụt (hoặc có payload sai schema).

    uv run python scripts/channel_coverage.py
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from attack.payloads.render import (  # noqa: E402
    ChannelRenderError,
    load_render_config,
    render_for_channel,
)
from attack.payloads.schema import CHANNEL_EXCLUDED, load_payloads  # noqa: E402

PAYLOAD_DIR = ROOT / "src" / "attack" / "payloads"


def _builds(p: dict[str, Any], channel: str, cfg: dict[str, Any]) -> bool:
    if channel not in (p.get("channels") or []):
        return False
    try:
        render_for_channel(p, channel, cfg=cfg)
    except ChannelRenderError:
        return False
    return True


def coverage(items: list[dict[str, Any]], *, cfg: dict[str, Any]) -> dict[str, Any]:
    """Tính phủ trên các payload ĐÃ hợp lệ. Trả khối summary + chi tiết theo (phân kênh, kỹ thuật)."""
    cov = cfg["coverage"]
    present = sorted({p["technique"]["code"] for p in items})
    rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []

    for sub in cov["subchannels"]:
        excluded = CHANNEL_EXCLUDED.get(sub, frozenset())
        covered_techs: list[str] = []
        denom_matrix = 0
        for tech in present:
            group = [p for p in items if p["technique"]["code"] == tech]
            buildable = tech not in excluded          # ô ✓ của mục 2.1
            n_k1 = sum(_builds(p, "K1", cfg) for p in group)
            n_sub = sum(_builds(p, sub, cfg) for p in group)
            n_both = sum(_builds(p, "K1", cfg) and _builds(p, sub, cfg) for p in group)
            is_covered = n_both >= 1
            if buildable:
                denom_matrix += 1
                if is_covered:
                    covered_techs.append(tech)
            rows.append({
                "subchannel": sub,
                "technique": tech,
                "buildable": int(buildable),
                "n_payloads": len(group),
                "n_k1": n_k1,
                "n_sub": n_sub,
                "n_both": n_both,
                "covered": int(is_covered),
            })
        n_covered = len(covered_techs)
        denom_raw = len(present)
        ratio_matrix = n_covered / denom_matrix if denom_matrix else 0.0
        ratio_raw = n_covered / denom_raw if denom_raw else 0.0
        summaries.append({
            "subchannel": sub,
            "covered": n_covered,
            "denom_matrix": denom_matrix,
            "denom_raw": denom_raw,
            "ratio_matrix": round(ratio_matrix, 4),
            "ratio_raw": round(ratio_raw, 4),
            "min_ratio": cov["min_ratio"],
            "passed": int(ratio_matrix >= cov["min_ratio"]),
            "covered_techniques": "|".join(covered_techs),
        })
    return {"rows": rows, "summaries": summaries}


_ROW_COLS = ["subchannel", "technique", "buildable", "n_payloads", "n_k1", "n_sub", "n_both", "covered"]
_SUM_COLS = [
    "subchannel", "covered", "denom_matrix", "denom_raw", "ratio_matrix", "ratio_raw",
    "min_ratio", "passed", "covered_techniques",
]


def write_csv(result: dict[str, Any], path: Path) -> None:
    """Hai khối trong một CSV: dòng '# summary'/'# per_technique' phân tách, cùng mục đích báo cáo."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["# summary"])
        csv.DictWriter(f, fieldnames=_SUM_COLS).writeheader()
        for s in result["summaries"]:
            csv.DictWriter(f, fieldnames=_SUM_COLS).writerow(s)
        w.writerow([])
        w.writerow(["# per_technique"])
        dw = csv.DictWriter(f, fieldnames=_ROW_COLS)
        dw.writeheader()
        for r in result["rows"]:
            dw.writerow(r)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--payloads", default=str(PAYLOAD_DIR), help="thư mục/file payload")
    args = parser.parse_args(argv)

    cfg = load_render_config()
    items, report = load_payloads(args.payloads)
    if not report.all_ok:
        print(f"Payload sai schema, không tính phủ ({len(report.errors_by_id)} id):")
        for pid, errs in report.errors_by_id.items():
            print(f"  {pid}: {errs[0]}")
        return 1

    result = coverage(items, cfg=cfg)
    out = ROOT / cfg["coverage"]["output"]
    write_csv(result, out)

    print(f"Corpus {report.total} payload · bảng phủ → {out.relative_to(ROOT)}")
    all_pass = True
    for s in result["summaries"]:
        mark = "ĐẠT" if s["passed"] else "HỤT"
        print(
            f"  {s['subchannel']}: {s['covered']}/{s['denom_matrix']} kỹ thuật dựng được "
            f"= {s['ratio_matrix']:.0%} (ngưỡng {s['min_ratio']:.0%}) [{mark}] "
            f"· thô {s['covered']}/{s['denom_raw']} = {s['ratio_raw']:.0%}"
        )
        all_pass = all_pass and bool(s["passed"])
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
