"""Bảng nền B1 (STT-68) và số liệu trả lời RQ1, RQ2 (STT-70) từ ba lô B1 — không chạy LLM.

Đọc ba lô B1 (guarded · baseline · trusting), ghi vào `results/tables/b1/`:

  asr_variant_target_channel.csv   ASR_e2e, ASR_cond, Wilson 95%, refusal theo biến thể × model × kênh
  rq1_t_chung.csv                  RQ1: K2 (K2a+K2b) so với K1 trên T_chung, theo biến thể × model
  rq2_rank.csv                     RQ2: ASR theo kênh × kỹ thuật × model, cờ thuộc nhóm mạnh nhất
  rq2_stability.csv                RQ2: Kendall τ-b A2↔A3, top-3 của A1 so với top-3 gộp A2+A3
  channel_technique.csv            STT-68: kênh × kỹ thuật (gộp model) theo biến thể
  goal_technique.csv               STT-68: mục tiêu × kỹ thuật (gộp kênh, model)
  lang_carrier.csv                 STT-68: ngôn ngữ payload × tác vụ chở
  heatmap_baseline.svg             ASR_e2e kênh × kỹ thuật theo model, biến thể baseline
  sensitivity.csv                  C5: ASR theo biến thể prompt × model × lớp payload
  sensitivity_pgfplots.tex         C5: hình đường cong độ nhạy (pgfplots, dán vào báo cáo)

Lớp payload của đường cong độ nhạy: G1+G2 gắn ngữ cảnh · G1+G2 không gắn ngữ cảnh · G3 (corpus chỉ có
payload G3 không gắn ngữ cảnh). Tách G3 ra vì so hai lớp payload gộp mọi mục tiêu sẽ trộn lớp với mục
tiêu: payload gắn ngữ cảnh chỉ có ở G1, G2.

    uv run python scripts/b1_tables.py
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from attack.runner import load_corpus  # noqa: E402
from eval.b1_analysis import (  # noqa: E402
    T_CHUNG,
    kendall_tau_b,
    load_runs,
    overlap,
    tally,
    top_group,
)

BATCHES = {
    "guarded": "attack-B1-guarded-20261118T033825Z",
    "baseline": "attack-B1-baseline-20261118T090849Z",
    "trusting": "attack-B1-trusting-20261118T121136Z",
}
TARGETS = ("A1", "A2", "A3")
CHANNELS = ("K1", "K2a", "K2b")
TECHNIQUES = ("T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8")
GOALS = ("G1", "G2", "G3")
VARIANTS = ("guarded", "baseline", "trusting")
SERIES = {"ctx": "G1+G2 gắn ngữ cảnh", "old": "G1+G2 không gắn ngữ cảnh", "g3": "G3"}
OUT = ROOT / "results" / "tables" / "b1"


def _f(x: float | None) -> str:
    return "" if x is None else f"{x:.4f}"


def _rate_cols(prefix: str, c) -> dict:
    ci, cc = c.ci, c.ci_cond
    return {
        f"{prefix}n": c.n, f"{prefix}s": c.s, f"{prefix}d": c.d,
        f"{prefix}asr_e2e": _f(c.asr), f"{prefix}lo": _f(ci and ci[0]), f"{prefix}hi": _f(ci and ci[1]),
        f"{prefix}asr_cond": _f(c.asr_cond), f"{prefix}cond_lo": _f(cc and cc[0]),
        f"{prefix}cond_hi": _f(cc and cc[1]),
    }


def _write(name: str, rows: list[dict]) -> Path:
    path = OUT / name
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return path


def _group(runs, *keys):
    out = defaultdict(list)
    for r in runs:
        out[tuple(r[k] for k in keys)].append(r)
    return out


def _top3(cell: dict) -> list[str]:
    return sorted(cell, key=lambda k: (-cell[k].asr, k))[:3]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    data = {v: load_runs(ROOT / "results" / "attack_matrix" / b / "trace.sqlite")
            for v, b in BATCHES.items()}
    written = []

    rows = []
    for v, runs in data.items():
        g = _group(runs, "target_id", "channel")
        for t in TARGETS:
            for ch in CHANNELS:
                c = tally(g[(t, ch)])
                rows.append({"variant": v, "target_id": t, "channel": ch,
                             **_rate_cols("", c), "refusal": c.refusal})
    written.append(_write("asr_variant_target_channel.csv", rows))

    rows = []
    for v, runs in data.items():
        common = [r for r in runs if r["technique"] in T_CHUNG]
        for t in (*TARGETS, "ALL"):
            mine = common if t == "ALL" else [r for r in common if r["target_id"] == t]
            k1 = tally(r for r in mine if r["channel"] == "K1")
            k2 = tally(r for r in mine if r["channel"] in ("K2a", "K2b"))
            rows.append({
                "variant": v, "target_id": t, **_rate_cols("k1_", k1), **_rate_cols("k2_", k2),
                "k2_gt_k1_e2e": "khác" if overlap(k2.ci, k1.ci) is False else "xu hướng",
                "k2_gt_k1_cond": "khác" if overlap(k2.ci, k1.ci_cond) is False else "xu hướng",
                "k2_minus_k1_e2e": _f((k2.asr or 0) - (k1.asr or 0)),
                "k2_minus_k1_cond": _f((k2.asr or 0) - (k1.asr_cond or 0)),
            })
    written.append(_write("rq1_t_chung.csv", rows))

    rank_rows, stab_rows = [], []
    for v, runs in data.items():
        g = _group(runs, "target_id", "channel", "technique")
        for ch in CHANNELS:
            techs = [t for t in TECHNIQUES if any(g.get((a, ch, t)) for a in TARGETS)]
            asr = {}
            for a in (*TARGETS, "A2+A3"):
                members = ("A2", "A3") if a == "A2+A3" else (a,)
                cell = {t: tally(r for m in members for r in g.get((m, ch, t), []))
                        for t in techs}
                asr[a] = cell
                top = top_group({t: (c.asr, c.ci) for t, c in cell.items()})
                for t, c in cell.items():
                    rank_rows.append({"variant": v, "channel": ch, "target_id": a, "technique": t,
                                      **_rate_cols("", c), "top_group": t in top})
            a2 = [asr["A2"][t].asr for t in techs]
            a3 = [asr["A3"][t].asr for t in techs]
            tau = kendall_tau_b(a2, a3)
            a1_top, pooled_top = _top3(asr["A1"]), _top3(asr["A2+A3"])
            stab_rows.append({
                "variant": v, "channel": ch, "n_techniques": len(techs),
                "kendall_tau_b_a2_a3": _f(tau),
                "stable": "" if tau is None else tau >= 0.6,
                "top_group_a2": " ".join(top_group({t: (c.asr, c.ci) for t, c in asr["A2"].items()})),
                "top_group_a3": " ".join(top_group({t: (c.asr, c.ci) for t, c in asr["A3"].items()})),
                "top_group_a2_a3": " ".join(
                    top_group({t: (c.asr, c.ci) for t, c in asr["A2+A3"].items()})),
                "top3_a1": " ".join(a1_top), "top3_a2_a3": " ".join(pooled_top),
                "a1_top3_shared": len(set(a1_top) & set(pooled_top)),
            })
    written.append(_write("rq2_rank.csv", rank_rows))
    written.append(_write("rq2_stability.csv", stab_rows))

    rows = []
    for v, runs in data.items():
        g = _group(runs, "channel", "technique")
        for ch in CHANNELS:
            for t in TECHNIQUES:
                if g.get((ch, t)):
                    rows.append({"variant": v, "channel": ch, "technique": t,
                                 **_rate_cols("", tally(g[(ch, t)]))})
    written.append(_write("channel_technique.csv", rows))

    rows = []
    for v, runs in data.items():
        g = _group(runs, "goal", "technique")
        for goal in GOALS:
            for t in TECHNIQUES:
                if g.get((goal, t)):
                    rows.append({"variant": v, "goal": goal, "technique": t,
                                 **_rate_cols("", tally(g[(goal, t)]))})
    written.append(_write("goal_technique.csv", rows))

    rows = []
    for v, runs in data.items():
        g = _group(runs, "lang", "carrier_task_id")
        for (lang, ct), part in sorted(g.items()):
            rows.append({"variant": v, "lang": lang, "carrier_task_id": ct,
                         **_rate_cols("", tally(part))})
    written.append(_write("lang_carrier.csv", rows))

    written.append(_heatmap(data["baseline"]))
    written.extend(_sensitivity(data))
    for p in written:
        print(p.relative_to(ROOT))
    return 0


def _series(run: dict, contextual: dict[str, bool]) -> str:
    if run["goal"] == "G3":
        return "g3"
    return "ctx" if contextual[run["payload_id"]] else "old"


def _sensitivity(data) -> list[Path]:
    contextual = {p["id"]: bool(p.get("contextual")) for p in load_corpus()}
    rows = []
    for v in VARIANTS:
        g = defaultdict(list)
        for r in data[v]:
            g[(r["target_id"], _series(r, contextual))].append(r)
        for t in TARGETS:
            for key, label in SERIES.items():
                c = tally(g[(t, key)])
                rows.append({"variant": v, "target_id": t, "series": key, "label": label,
                             **_rate_cols("", c)})
    csv_path = _write("sensitivity.csv", rows)

    # pgfplots: ba khung (một khung mỗi lớp payload), trục x ba biến thể, mỗi model một đường.
    marks = {"A1": "square*", "A2": "*", "A3": "triangle*"}
    lines = ["% Sinh bởi scripts/b1_tables.py — không sửa tay. Cần \\usepackage{pgfplots} và",
             "% \\usepgfplotslibrary{groupplots}.",
             "\\begin{tikzpicture}",
             "\\begin{groupplot}[group style={group size=3 by 1, horizontal sep=1.4cm},",
             "  width=0.36\\textwidth, height=5cm, ymin=0, ymax=0.55,",
             "  symbolic x coords={guarded,baseline,trusting}, xtick=data,",
             "  x tick label style={font=\\small}, ylabel style={font=\\small},",
             "  yticklabel={\\pgfmathparse{100*\\tick}\\pgfmathprintnumber{\\pgfmathresult}\\%},",
             "  legend style={font=\\small}, legend pos=north west]"]
    for i, (key, label) in enumerate(SERIES.items()):
        opts = f"title={{{label}}}"
        if i == 0:
            opts += ", ylabel={ASR đầu-cuối}"
        lines.append(f"\\nextgroupplot[{opts}]")
        for t in TARGETS:
            pts = []
            for v in VARIANTS:
                r = next(x for x in rows if x["variant"] == v and x["target_id"] == t
                         and x["series"] == key)
                asr, lo, hi = float(r["asr_e2e"]), float(r["lo"]), float(r["hi"])
                pts.append(f"({v},{asr:.4f}) += (0,{hi - asr:.4f}) -= (0,{asr - lo:.4f})")
            lines.append(f"\\addplot+[mark={marks[t]}, error bars/.cd, y dir=both, y explicit]")
            lines.append("  coordinates {" + " ".join(pts) + "};")
            if i == 0:
                lines.append(f"\\addlegendentry{{{t}}}")
    lines += ["\\end{groupplot}", "\\end{tikzpicture}"]
    tex_path = OUT / "sensitivity_pgfplots.tex"
    tex_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return [csv_path, tex_path]


def _heatmap(runs) -> Path:
    """SVG: ba ma trận kênh × kỹ thuật (A1, A2, A3), ô ghi s/n, màu theo ASR_e2e; ô không dựng
    được để trống. Không cần thư viện vẽ."""
    g = _group(runs, "target_id", "channel", "technique")
    cw, ch_, left, top, gap = 46, 34, 48, 44, 30
    panel_w = left + cw * len(TECHNIQUES)
    width = panel_w * len(TARGETS) + gap * (len(TARGETS) - 1) + 10
    height = top + ch_ * len(CHANNELS) + 50
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'viewBox="0 0 {width} {height}" '
           f'font-family="Helvetica, Arial, sans-serif" font-size="11">',
           '<rect width="100%" height="100%" fill="#ffffff"/>']
    for k, a in enumerate(TARGETS):
        x0 = k * (panel_w + gap)
        out.append(f'<text x="{x0 + left}" y="16" font-size="13" font-weight="bold">{a}</text>')
        for j, t in enumerate(TECHNIQUES):
            out.append(f'<text x="{x0 + left + j * cw + cw / 2}" y="{top - 8}" '
                       f'text-anchor="middle">{t}</text>')
        for i, chn in enumerate(CHANNELS):
            y = top + i * ch_
            out.append(f'<text x="{x0 + left - 6}" y="{y + ch_ / 2 + 4}" '
                       f'text-anchor="end">{chn}</text>')
            for j, t in enumerate(TECHNIQUES):
                x = x0 + left + j * cw
                part = g.get((a, chn, t))
                if not part:
                    out.append(f'<rect x="{x}" y="{y}" width="{cw}" height="{ch_}" fill="#f2f2f2" '
                               'stroke="#ffffff"/>')
                    continue
                c = tally(part)
                p = c.asr or 0.0
                # thang tuyến tính trắng → xanh đậm, cắt ở 0,6 để phân biệt các ô thấp
                level = min(p / 0.6, 1.0)
                r, gg, b = (int(255 - level * (255 - 22)), int(255 - level * (255 - 78)),
                            int(255 - level * (255 - 140)))
                ink = "#ffffff" if level > 0.55 else "#1a1a1a"
                out.append(f'<rect x="{x}" y="{y}" width="{cw}" height="{ch_}" '
                           f'fill="rgb({r},{gg},{b})" stroke="#ffffff"/>')
                out.append(f'<text x="{x + cw / 2}" y="{y + ch_ / 2 + 4}" text-anchor="middle" '
                           f'fill="{ink}">{c.s}/{c.n}</text>')
    out.append(f'<text x="10" y="{height - 14}" fill="#555555">ASR_e2e, biến thể baseline, D = off, '
               'kẻ tấn công mù; ô xám: kỹ thuật không dựng được trên kênh. Màu bão hòa ở 60%.</text>')
    out.append("</svg>")
    path = OUT / "heatmap_baseline.svg"
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    raise SystemExit(main())
