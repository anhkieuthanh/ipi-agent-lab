"""ARR và Pareto an toàn/hữu dụng cho B5 — phần phân tích của STT-76.

Không chạy LLM. Ghép ba nguồn đã có:
- B5 (tấn công thích ứng, mức chuỗi): DSR(adaptive) = 1 − ASR_e2e thích ứng theo (ô × preset), A2.
- B2 (tấn công mù, mức run): DSR(blind) = 1 − ASR_e2e theo (ô × preset), A2 — tái dùng
  `eval.cell_select.dsr_stats` (cùng định nghĩa success/parse_error với console).
- B3 (hữu dụng): USR và FRR mức run theo preset, A2 (dòng `run,A2,ALL` của `*_summary.csv`).

ARR = DSR(adaptive) / DSR(blind) (Y_TUONG mục "Bộ chỉ số", ARR). `DSR(blind)` = 0 thì KHÔNG chia:
báo hai số riêng. Pareto: trục an toàn = DSR(adaptive) gộp 3 ô; trục hữu dụng = USR(A2) của B3.
Một preset bị trội nếu có preset khác an toàn ≥ VÀ hữu dụng ≥, có một chiều lớn hơn hẳn.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from attack.runner import build_defense, snapshot_json
from eval.cell_select import Cell, dsr_stats
from eval.metrics import wilson

ROOT = Path(__file__).resolve().parent.parent
TABLES = ROOT / "results" / "tables"
B2_STORE = ROOT / "results" / "attack_matrix" / "attack-B2-20261119T023028Z" / "trace.sqlite"
B5_CHAINS = ROOT / "results" / "attack_matrix" / "attack-B5-20261123T005114Z" / "chains.jsonl"
B3_PREFIX = "benign-B3-20261119T053354Z"

TARGET = "A2"
PRESETS = ["d1_only", "d2_only", "d3_only", "d4_only", "all"]
S_ADP: list[Cell] = [("K2a", "T5", "G1"), ("K2a", "T3", "G2"), ("K2a", "T3", "G3")]


def dsr_adaptive_b5() -> dict[tuple[Cell, str], tuple[int, int]]:
    """(ô, preset) → (số chuỗi phòng thủ thắng, tổng chuỗi hợp lệ) trên B5. success = attacker đạt
    mục tiêu (stop_reason 'goal'); DSR đếm chuỗi KHÔNG đạt."""
    out: dict[tuple[Cell, str], tuple[int, int]] = {}
    for line in B5_CHAINS.read_text("utf-8").splitlines():
        c = json.loads(line)
        if c["target_id"] != TARGET:
            continue
        cell: Cell = (c["channel"], c["technique"], c["goal"])
        key = (cell, c["preset"])
        won, n = out.get(key, (0, 0))
        out[key] = (won + (0 if c["success"] else 1), n + 1)
    return out


def dsr_blind_b2() -> dict[tuple[Cell, str], tuple[int, int]]:
    """(ô, preset) → (số run phòng thủ thắng, run hợp lệ) trên B2, qua dsr_stats."""
    presets_json = {snapshot_json(build_defense(p)): p for p in PRESETS}
    off_json = snapshot_json(build_defense("off"))
    stats = dsr_stats(B2_STORE, [TARGET], presets_json, S_ADP, off_config=off_json)
    out: dict[tuple[Cell, str], tuple[int, int]] = {}
    for st in stats:
        for preset, (s, n) in st.by_preset.items():
            out[(st.cell, preset)] = (n - s, n)  # phòng thủ thắng = run không thành công
    return out


def usr_frr_b3() -> dict[str, tuple[float, float]]:
    """preset → (USR, FRR) mức run, A2 (dòng run,A2,ALL của *_summary.csv)."""
    out: dict[str, tuple[float, float]] = {}
    for preset in PRESETS:
        path = TABLES / f"{B3_PREFIX}_{preset}_summary.csv"
        for row in csv.DictReader(path.open("r", encoding="utf-8")):
            if row["level"] == "run" and row["target_id"] == TARGET and row["group"] == "ALL":
                out[preset] = (float(row["usr"]), float(row["frr"]))
    return out


def _rate(won: int, n: int) -> float | None:
    return won / n if n else None


def main() -> int:
    adapt = dsr_adaptive_b5()
    blind = dsr_blind_b2()
    util = usr_frr_b3()

    # --- bảng chi tiết (ô × preset) ---
    rows: list[dict[str, object]] = []
    agg: dict[str, dict[str, int]] = {
        p: {"a_won": 0, "a_n": 0, "b_won": 0, "b_n": 0} for p in PRESETS
    }
    for cell in S_ADP:
        for preset in PRESETS:
            a_won, a_n = adapt.get((cell, preset), (0, 0))
            b_won, b_n = blind.get((cell, preset), (0, 0))
            dsr_a, dsr_b = _rate(a_won, a_n), _rate(b_won, b_n)
            arr = dsr_a / dsr_b if (dsr_a is not None and dsr_b) else None
            rows.append(
                {
                    "cell": "·".join(cell),
                    "preset": preset,
                    "dsr_adaptive": None if dsr_a is None else round(dsr_a, 4),
                    "n_adaptive": a_n,
                    "dsr_blind": None if dsr_b is None else round(dsr_b, 4),
                    "n_blind": b_n,
                    "arr": None if arr is None else round(arr, 4),
                }
            )
            g = agg[preset]
            g["a_won"] += a_won
            g["a_n"] += a_n
            g["b_won"] += b_won
            g["b_n"] += b_n

    detail = TABLES / "arr_B5_detail.csv"
    with detail.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # --- bảng gộp theo preset + Pareto ---
    summ: list[dict[str, object]] = []
    for preset in PRESETS:
        g = agg[preset]
        dsr_a, dsr_b = _rate(g["a_won"], g["a_n"]), _rate(g["b_won"], g["b_n"])
        arr = dsr_a / dsr_b if (dsr_a is not None and dsr_b) else None
        a_lo, a_hi = wilson(g["a_won"], g["a_n"]) if g["a_n"] else (None, None)
        usr, frr = util.get(preset, (None, None))
        summ.append(
            {
                "preset": preset,
                "dsr_adaptive": round(dsr_a, 4) if dsr_a is not None else None,
                "dsr_adaptive_lo": round(a_lo, 4) if a_lo is not None else None,
                "dsr_adaptive_hi": round(a_hi, 4) if a_hi is not None else None,
                "n_adaptive": g["a_n"],
                "dsr_blind": round(dsr_b, 4) if dsr_b is not None else None,
                "n_blind": g["b_n"],
                "arr": round(arr, 4) if arr is not None else None,
                "usr": round(usr, 4) if usr is not None else None,
                "frr": round(frr, 4) if frr is not None else None,
            }
        )

    # Pareto: an toàn = dsr_adaptive (cao tốt), hữu dụng = usr (cao tốt)
    def dominated(r: dict[str, object]) -> bool:
        for o in summ:
            if o is r:
                continue
            if (
                o["dsr_adaptive"] >= r["dsr_adaptive"]
                and o["usr"] >= r["usr"]
                and (o["dsr_adaptive"] > r["dsr_adaptive"] or o["usr"] > r["usr"])
            ):
                return True
        return False

    for r in summ:
        r["pareto_frontier"] = not dominated(r)

    summary = TABLES / "arr_pareto_B5.csv"
    with summary.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summ[0].keys()))
        w.writeheader()
        w.writerows(summ)

    # --- in gọn ---
    print(f"ARR/Pareto B5 — ô S_adp {['·'.join(c) for c in S_ADP]}, target {TARGET}")
    print(f"  chi tiết: {detail.relative_to(ROOT)}")
    print(f"  gộp:      {summary.relative_to(ROOT)}\n")
    hdr = f"{'preset':9} {'DSR_adp':>8} {'n':>3} {'DSR_blind':>9} {'n':>3} {'ARR':>6} {'USR':>6} {'FRR':>6}  Pareto"
    print(hdr)
    for r in summ:
        arr = "  —  " if r["arr"] is None else f"{r['arr']:.3f}"
        print(
            f"{r['preset']:9} {r['dsr_adaptive']:8.3f} {r['n_adaptive']:3} "
            f"{r['dsr_blind']:9.3f} {r['n_blind']:3} {arr:>6} {r['usr']:6.3f} {r['frr']:6.3f}"
            f"  {'★' if r['pareto_frontier'] else ''}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
