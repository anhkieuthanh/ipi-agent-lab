"""Lô dò tấn công thích ứng trước khi quyết hướng ma trận (STT-61, mục 5 xin ý kiến GVHD).

Câu hỏi: khi hiệu chỉnh đã hết núm mà ASR blind vẫn ≈ 0, kẻ tấn công thích ứng (`attack.adaptive`,
≤ 3 vòng, phản hồi PH1) có kéo ASR lên mức đo được không? Lô dò, không vào bảng kết quả nào — cùng
khung với pilot (giao thức thực nghiệm mục 3).

Đơn vị dò lấy từ một lô hiệu chỉnh: (kênh, kỹ thuật, mục tiêu, payload, tác vụ chở) mà ở CẢ A2 và
A3 payload đã tới ngữ cảnh (`delivered`) nhưng run thất bại không vì từ chối (`outcome = failed`).
Đó đúng là chỗ kẻ tấn công thích ứng phải lật: model thấy payload mà không làm theo. Chọn tất định
theo `run_order.seed`, chia đều ba mục tiêu G. Mỗi đơn vị chạy một chuỗi trên A2 và một trên A3,
D = OFF, biến thể prompt = `active` của `config/prompts.yaml`.

    uv run python scripts/adaptive_probe.py --source-batch calib-r2-B1-20261027T035520Z --plan-only
    uv run python scripts/adaptive_probe.py --source-batch calib-r2-B1-20261027T035520Z --estimate-usd 6

Lô tiền tố `probe-adaptive-`, lưu ở `results/probe/adaptive/<batch_id>/`: `trace.sqlite`,
`chains.csv` (một dòng mỗi chuỗi), `manifest.json`. Chi phí gồm cả model đích lẫn model attacker;
`BudgetGuard` so tổng với `--estimate-usd` sau mỗi chuỗi.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

from agent.core import load_core_params  # noqa: E402
from agent.llm_client import ATTACKER_ID, LLMClient  # noqa: E402
from agent.prompts import load_prompt_config, template_hash  # noqa: E402
from attack.adaptive import AdaptiveChainSpec, LLMAdaptiveAttacker, run_chain  # noqa: E402
from attack.runner import (  # noqa: E402
    HARNESS_PREFIX,
    RunContext,
    build_defense,
    build_defenses,
    load_carriers,
    load_corpus,
    snapshot_json,
)
from eval.canary import sweep_stale_run_dirs  # noqa: E402
from eval.experiment import load_experiment  # noqa: E402
from eval.utility_baseline import build_harness_tools  # noqa: E402
from obs.cost import budget_from_env, load_prices, spend_from_log  # noqa: E402
from obs.trace import (  # noqa: E402
    compute_env_hash,
    lab_git_commit,
    open_store,
    uncommitted_changes,
)

MODELS = ROOT / "config" / "models.yaml"
TOOLS = ROOT / "config" / "tools.yaml"
LOG = ROOT / "logs" / "llm_client.jsonl"
CALIBRATION_ROOT = ROOT / "results" / "calibration"
PROBE_ROOT = ROOT / "results" / "probe" / "adaptive"
TARGETS = ("A2", "A3")
GOALS = ("G1", "G2", "G3")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _source_store(batch_id: str) -> Path:
    rnd = batch_id.split("-")[1]  # calib-r<N>-…
    return CALIBRATION_ROOT / f"round_{rnd.removeprefix('r')}" / batch_id / "trace.sqlite"


def select_units(store: Path, n: int, seed: int) -> list[tuple[str, str, str, str, str]]:
    """`n` đơn vị (kênh, kỹ thuật, mục tiêu, payload, tác vụ chở) thất bại-dù-đã-tới ở cả A2 và A3."""
    con = sqlite3.connect(f"file:{store}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT channel, technique, goal, payload_id, carrier_task_id FROM runs "
        "WHERE target_id IN ('A2','A3') AND delivered = 1 AND outcome = 'failed' "
        "AND parse_error = 0 GROUP BY 1,2,3,4,5 HAVING COUNT(DISTINCT target_id) = 2"
    ).fetchall()
    con.close()
    rng = random.Random(f"{seed}:adaptive-probe")
    by_goal = {g: sorted(r for r in rows if r[2] == g) for g in GOALS}
    for units in by_goal.values():
        rng.shuffle(units)
    chosen: list[tuple[str, str, str, str, str]] = []
    while len(chosen) < n and any(by_goal.values()):
        for g in GOALS:
            if by_goal[g] and len(chosen) < n:
                chosen.append(by_goal[g].pop())
    return chosen


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source-batch", required=True, help="lô hiệu chỉnh calib-r<N>-… làm nguồn")
    parser.add_argument("--units", type=int, default=12, help="số đơn vị dò (mỗi đơn vị × A2, A3)")
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--estimate-usd", type=float, help="dự toán chi phí lô (USD)")
    parser.add_argument("--plan-only", action="store_true", help="in đơn vị, không gọi API")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    exp = load_experiment()
    seed = exp.raw["run_order"]["seed"]
    units = select_units(_source_store(args.source_batch), args.units, seed)
    print(f"{len(units)} đơn vị × {len(TARGETS)} target = {len(units) * len(TARGETS)} chuỗi")
    for u in units:
        print("  " + " · ".join(u))
    if args.plan_only:
        return 0

    commit = lab_git_commit()
    if commit.endswith("-dirty"):
        print(f"Cây làm việc chưa commit ({commit}) — commit rồi chạy lại:")
        print("\n".join(f"  {line}" for line in uncommitted_changes()))
        return 2
    if args.estimate_usd is None:
        parser.error("cần --estimate-usd để mở lô")

    batch_id = f"probe-adaptive-{_stamp()}"
    batch_dir = PROBE_ROOT / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    engine = open_store(batch_dir / "trace.sqlite")

    prices = load_prices(MODELS, ["A1", *TARGETS])
    prices[ATTACKER_ID] = prices["A1"]  # attacker và A1 cùng claude-opus-5 (models.yaml)
    guard = budget_from_env(args.estimate_usd)
    models = {t: LLMClient(t, config_path=MODELS, log_path=LOG, run_id=batch_id) for t in TARGETS}
    attacker = LLMAdaptiveAttacker(
        client=LLMClient(ATTACKER_ID, config_path=MODELS, log_path=LOG, run_id=batch_id)
    )
    corpus = {p["id"]: p for p in load_corpus()}
    swept = sweep_stale_run_dirs()
    if swept:
        print(f"Đã dọn {len(swept)} thư mục run cũ còn sót.")
    off = snapshot_json(build_defense("off"))
    ctx = RunContext(
        engine=engine,
        batch_id=batch_id,
        env_hash=compute_env_hash(template_hash(), TOOLS, commit),
        harness_version=f"{HARNESS_PREFIX}{commit}",
        models=models,
        tools=build_harness_tools(),
        corpus_by_id=corpus,
        carriers_by_id={c["id"]: c for c in load_carriers()},
        core_params=load_core_params(),
        kb_top_k=exp.fixed["kb_top_k"],
        defenses=build_defenses(["off"]),
    )
    prompt_cfg = load_prompt_config()
    manifest = {
        "task": "STT-61 (dò tấn công thích ứng)",
        "batch_id": batch_id,
        "source_batch": args.source_batch,
        "lab_git_commit": commit,
        "env_hash": ctx.env_hash,
        "prompt_variant": prompt_cfg.active,
        "prompt_knobs": prompt_cfg.knobs(),
        "models": {t: m.model for t, m in models.items()},
        "attacker_model": attacker.client.model,
        "defense": "off",
        "max_rounds": args.max_rounds,
        "units": [list(u) for u in units],
        "estimate_usd": args.estimate_usd,
        "started_at_utc": _stamp(),
    }

    fields = [
        "chain_id", "target_id", "channel", "technique", "goal", "payload_id", "carrier_task_id",
        "success", "success_round", "stop_reason", "n_rounds", "outcomes", "run_ids",
    ]
    rows: list[dict] = []
    status = "ok"
    t0 = time.monotonic()
    specs = [
        AdaptiveChainSpec(
            target_id=t,
            channel=ch,
            goal=g,
            defense_config=off,
            carrier_task_id=ct,
            base_payload=corpus[pid],
        )
        for (ch, _tech, g, pid, ct) in units
        for t in TARGETS
    ]
    try:
        for i, spec in enumerate(specs, start=1):
            res = run_chain(spec, ctx, attacker, max_rounds=args.max_rounds)
            rows.append({
                "chain_id": res.chain_id,
                "target_id": spec.target_id,
                "channel": spec.channel,
                "technique": spec.base_payload["technique"]["code"],
                "goal": spec.goal,
                "payload_id": spec.base_payload["id"],
                "carrier_task_id": spec.carrier_task_id,
                "success": res.success,
                "success_round": res.success_round,
                "stop_reason": res.stop_reason,
                "n_rounds": len(res.rounds),
                "outcomes": "|".join(f"{r.outcome or 'parse_error'}:{r.blocked_by or ''}"
                                     for r in res.rounds),
                "run_ids": "|".join(r.run_id for r in res.rounds),
            })
            spent = sum(spend_from_log(LOG, prices, run_ids=[batch_id]).values())
            status = guard.status(spent)
            print(
                f"[{i}/{len(specs)}] {spec.target_id} {spec.channel}·{spec.goal} "
                f"{spec.base_payload['id']} {spec.carrier_task_id} → "
                f"{'THÀNH CÔNG vòng ' + str(res.success_round) if res.success else res.stop_reason}"
                f" · {spent:.2f} USD · {status} · {(time.monotonic() - t0) / 60:.1f} phút",
                flush=True,
            )
            if status == "stop":
                print("DỪNG: chi phí lô vượt 120% dự toán hoặc chạm hạn mức tổng.")
                break
    finally:
        with (batch_dir / "chains.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
        manifest["finished_at_utc"] = _stamp()
        manifest["spent_usd"] = sum(spend_from_log(LOG, prices, run_ids=[batch_id]).values())
        manifest["budget_status"] = status
        (batch_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    for t in TARGETS:
        mine = [r for r in rows if r["target_id"] == t]
        s = sum(r["success"] for r in mine)
        print(f"{t}: {s}/{len(mine)} chuỗi thành công")
    print(f"  chuỗi: {(batch_dir / 'chains.csv').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
