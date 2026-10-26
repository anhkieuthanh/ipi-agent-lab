"""Soát lô pilot STT-60: ASR theo target, kiểm trường tự động, chọn 10 trace để mở tay.

Đọc `results/raw/pilot/<batch_id>/trace.sqlite` (lô do `run_matrix.py --pilot` sinh), ghi vào cùng
thư mục:

    asr_by_target.csv     ASR_e2e/ASR_cond + Wilson 95% mỗi target, vai trò (cổng/chỉ đo), so cổng
    asr_by_axis.csv       ASR mỗi target theo kênh, kỹ thuật, mục tiêu — mô tả, không kết luận
    field_check.csv       mỗi run một dòng: cờ thiếu trường / mâu thuẫn nhãn (kiểm bằng máy)
    payload_activation.csv  mỗi payload: số run, số thành công ở D=OFF — ứng viên loại theo
                          `payload_taxonomy.md` mục 5 (TA quyết, script không loại)
    review_sheet.csv      10 trace mở tay, cột Đ/S để TA điền
    review/<run_id>.md    từng bước của 10 trace đó, đọc thay cho trace viewer

Không gọi API. Số pilot không vào bảng kết quả nào (giao thức thực nghiệm mục 3).

    uv run python scripts/pilot_review.py --batch-id pilot-B1-<UTC>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from eval.experiment import load_experiment  # noqa: E402
from eval.metrics import wilson  # noqa: E402
from obs.trace import BLOCKED_BY, Step, export_runs, open_store  # noqa: E402

PILOT_ROOT = ROOT / "results" / "raw" / "pilot"
N_REVIEW = 10

# Trường run tấn công phải có giá trị sau khi chấm (`docs/04. Design/04. Trace schema.md`).
REQUIRED = [
    "batch_id",
    "run_kind",
    "target_id",
    "model_id",
    "response_model",
    "harness",
    "harness_version",
    "env_hash",
    "defense_config",
    "carrier_task_id",
    "payload_id",
    "technique",
    "goal",
    "channel",
    "attacker_mode",
    "lang",
    "run_canaries",
    "delivered",
    "outcome",
    "finished_at",
]
ATTACK_OUTCOMES = {"success", "failed", "blocked"}


def _asr_row(cell: pd.DataFrame) -> dict:
    clean = cell[~cell["parse_error"].astype(bool)]
    n = len(clean)
    s = int((clean["outcome"] == "success").sum())
    d = int(clean["delivered"].fillna(False).astype(bool).sum())
    lo, hi = wilson(s, n) if n else (None, None)
    row = {
        "n_raw": len(cell),
        "n_excl": len(cell) - n,
        "n": n,
        "s": s,
        "d": d,
        "asr_e2e": s / n if n else None,
        "asr_e2e_lo": lo,
        "asr_e2e_hi": hi,
        "asr_cond": s / d if d else None,
    }
    for b in BLOCKED_BY:
        row[f"blocked_{b}"] = int((clean["blocked_by"] == b).sum())
    return row


def asr_by_target(runs: pd.DataFrame, pilot: dict) -> pd.DataFrame:
    lo_gate, hi_gate = pilot["asr_gate"]
    rows = []
    for target, cell in runs.groupby("target_id", sort=True):
        role = "cổng" if target in pilot["targets"] else "chỉ đo"
        r = {"target_id": target, "vai_tro": role} | _asr_row(cell)
        asr = r["asr_e2e"]
        if asr is None:
            r["so_cong"] = "không có run hợp lệ"
        elif asr < lo_gate:
            r["so_cong"] = "dưới cổng"
        elif asr > hi_gate:
            r["so_cong"] = "trên cổng"
        else:
            r["so_cong"] = "trong cổng"
        rows.append(r)
    return pd.DataFrame(rows)


def asr_by_axis(runs: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for axis in ("channel", "technique", "goal", "carrier_task_id"):
        for (target, value), cell in runs.groupby(["target_id", axis], sort=True):
            rows.append({"target_id": target, "truc": axis, "gia_tri": value} | _asr_row(cell))
    return pd.DataFrame(rows)


def field_check(runs: pd.DataFrame, steps: pd.DataFrame) -> pd.DataFrame:
    n_steps = steps.groupby("run_id").size()
    rows = []
    for r in runs.itertuples(index=False):
        flags = [f"thiếu:{c}" for c in REQUIRED if pd.isna(getattr(r, c)) or getattr(r, c) == ""]
        if r.outcome not in ATTACK_OUTCOMES:
            flags.append(f"outcome lạ:{r.outcome}")
        if r.outcome == "blocked" and pd.isna(r.blocked_by):
            flags.append("blocked thiếu blocked_by")
        if r.channel in ("K2a", "K2b") and r.delivered is not True:
            flags.append("K2 mà delivered≠true")
        if r.outcome == "success" and r.delivered is False:
            flags.append("success mà delivered=false")
        if r.blocked_by == "defense":
            flags.append("blocked_by=defense ở D=OFF")
        if r.g1_hit and pd.isna(r.g1_channel):
            flags.append("g1_hit thiếu g1_channel")
        hits = {"G1": r.g1_hit, "G2": r.g2_hit, "G3": r.g3_hit}
        if r.outcome == "success" and not hits.get(r.goal):
            flags.append(f"success mà {r.goal.lower()}_hit=false")
        if r.parse_error:
            flags.append(f"parse_error:{r.parse_error_reason}")
        if not r.parse_error and n_steps.get(r.run_id, 0) == 0:
            flags.append("không có bước nào")
        if not json.loads(r.run_canaries or "[]"):
            flags.append("run_canaries rỗng")
        rows.append(
            {
                "run_id": r.run_id,
                "target_id": r.target_id,
                "channel": r.channel,
                "technique": r.technique,
                "goal": r.goal,
                "carrier_task_id": r.carrier_task_id,
                "payload_id": r.payload_id,
                "outcome": r.outcome,
                "blocked_by": r.blocked_by,
                "delivered": r.delivered,
                "n_steps": int(n_steps.get(r.run_id, 0)),
                "co": "; ".join(flags),
            }
        )
    return pd.DataFrame(rows)


def payload_activation(runs: pd.DataFrame) -> pd.DataFrame:
    clean = runs[~runs["parse_error"].astype(bool)]
    rows = []
    for pid, cell in clean.groupby("payload_id", sort=True):
        by_t = {t: int((c["outcome"] == "success").sum()) for t, c in cell.groupby("target_id")}
        s = sum(by_t.values())
        rows.append(
            {
                "payload_id": pid,
                "technique": cell["technique"].iloc[0],
                "goal": cell["goal"].iloc[0],
                "channels": ",".join(sorted(cell["channel"].unique())),
                "n": len(cell),
                "s": s,
                "s_theo_target": json.dumps(by_t, ensure_ascii=False),
                "ung_vien_loai": s == 0,
            }
        )
    return pd.DataFrame(rows)


def pick_review(fc: pd.DataFrame, k: int, seed: int) -> pd.DataFrame:
    """Chọn `k` trace phủ nhiều nhất: target, kênh, outcome, mục tiêu, tác vụ chở; ưu tiên run có
    cờ và run K1 không tới (delivered=false). Tất định theo `seed`."""
    pool = fc.sample(frac=1, random_state=seed).to_dict("records")
    seen: dict[str, set] = {
        a: set()
        for a in ("target_id", "channel", "outcome", "goal", "carrier_task_id", "technique")
    }
    picked: list[dict] = []

    def gain(r: dict) -> int:
        g = sum(r[a] not in seen[a] for a in seen)
        if r["co"]:
            g += 2
        if (
            r["channel"] == "K1"
            and r["delivered"] is False
            and not any(p["channel"] == "K1" and p["delivered"] is False for p in picked)
        ):
            g += 2
        return g

    while pool and len(picked) < k:
        best = max(pool, key=gain)
        pool.remove(best)
        picked.append(best)
        for a in seen:
            seen[a].add(best[a])
    out = pd.DataFrame(picked)
    for col in ("du_truong", "delivered_dung", "phat_hien_hop_ly", "ghi_chu_TA"):
        out[col] = ""
    return out


def dump_trace(run: pd.Series, steps: pd.DataFrame, out: Path) -> None:
    # NaN của pandas thành None, để ô trống không in thành "nan".
    run = run.astype(object).where(run.notna(), None)
    steps = steps.astype(object).where(steps.notna(), None)
    lines = [
        f"# {run.run_id}",
        "",
        f"- target: {run.target_id} ({run.model_id} → {run.response_model})",
        f"- ô: {run.channel} · {run.technique} · {run.goal} · {run.carrier_task_id}"
        f" · payload {run.payload_id} ({run.lang})",
        f"- delivered: {run.delivered} · outcome: {run.outcome} · blocked_by: {run.blocked_by}",
        f"- g1_hit: {run.g1_hit} ({run.g1_channel}) · leak_attempted: {run.leak_attempted}"
        f" · g2_hit: {run.g2_hit} ({run.g2_severity}) · g3_hit: {run.g3_hit}"
        f" · loop_flag: {run.loop_flag}",
        f"- parse_error: {run.parse_error} {run.parse_error_reason or ''}",
        f"- env_hash: {run.env_hash} · harness: {run.harness_version}",
        f"- canary: {run.run_canaries}",
        "",
    ]
    for s in steps.sort_values("step_idx").itertuples(index=False):
        lines.append(
            f"## Bước {s.step_idx} — {s.kind}"
            + (f" · {s.tool_name}" if s.tool_name else "")
            + (f" · finish={s.finish_reason}" if s.finish_reason else "")
        )
        for label, val in (
            ("llm_text", s.llm_text),
            ("tool_args", s.tool_args),
            ("tool_result", s.tool_result),
        ):
            if val:
                lines += [f"**{label}**", "", "```", str(val), "```", ""]
        if s.defense_hits and s.defense_hits != "[]":
            lines += [f"**defense_hits** `{s.defense_hits}`", ""]
    lines += ["## final_answer", "", "```", str(run.final_answer or ""), "```", ""]
    out.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--batch-id", required=True)
    args = parser.parse_args()

    batch_dir = PILOT_ROOT / args.batch_id
    store = batch_dir / "trace.sqlite"
    if not store.is_file():
        parser.error(f"không có store {store.relative_to(ROOT)}")
    exp = load_experiment()
    pilot = exp.raw["pilot"]
    engine = open_store(store)
    runs = export_runs(engine, batch_id=args.batch_id)
    runs = runs[runs["run_kind"] == "attack"]
    with Session(engine) as session:
        steps = pd.DataFrame(
            [s.model_dump() for s in session.exec(select(Step)).all()],
            columns=list(Step.model_fields),
        )
    steps = steps[steps["run_id"].isin(runs["run_id"])]

    by_target = asr_by_target(runs, pilot)
    by_target.to_csv(batch_dir / "asr_by_target.csv", index=False)
    asr_by_axis(runs).to_csv(batch_dir / "asr_by_axis.csv", index=False)
    fc = field_check(runs, steps)
    fc.to_csv(batch_dir / "field_check.csv", index=False)
    pa = payload_activation(runs)
    pa.to_csv(batch_dir / "payload_activation.csv", index=False)
    review = pick_review(fc, N_REVIEW, seed=exp.raw["run_order"]["seed"])
    review.to_csv(batch_dir / "review_sheet.csv", index=False)
    rdir = batch_dir / "review"
    rdir.mkdir(exist_ok=True)
    for rid in review["run_id"]:
        run = runs[runs["run_id"] == rid].iloc[0]
        dump_trace(run, steps[steps["run_id"] == rid], rdir / f"{rid}.md")

    cols = [
        "target_id",
        "vai_tro",
        "n",
        "n_excl",
        "s",
        "d",
        "asr_e2e",
        "asr_e2e_lo",
        "asr_e2e_hi",
        "asr_cond",
        "blocked_model_refusal",
        "so_cong",
    ]
    print(by_target[cols].to_string(index=False))
    print(f"\nrun có cờ: {(fc['co'] != '').sum()}/{len(fc)}")
    print(f"payload: {len(pa)} · ứng viên loại (0 thành công): {int(pa['ung_vien_loai'].sum())}")
    print(f"10 trace mở tay: {(batch_dir / 'review_sheet.csv').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
