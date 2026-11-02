"""Lô dò payload "gắn ngữ cảnh" (STT-61) — thử giả thuyết payload/phương thức tấn công còn yếu.

Chạy 6 payload ở `results/probe/coupling/payloads_coupling.yaml`, mỗi payload bám đúng tool và nghiệp
vụ của một tác vụ chở (CT-01..CT-06), kẻ tấn công mù (blind), D = OFF, trên A2 và A3, lặp `--repeats`
lần. So ASR với nhánh blind corpus hiện tại (hiệu chỉnh: A2/A3 ≈ 0–2,5%).

Lô dò, KHÔNG vào bảng kết quả nào và KHÔNG vào corpus (giao thức thực nghiệm mục 3; payload không
mang v-attack-1.0). Dùng chính `attack.runner.run_one_attack` như lô thật, nên kết quả so được.

    uv run python scripts/coupling_probe.py --plan-only
    uv run python scripts/coupling_probe.py --estimate-usd 3

Lô tiền tố `probe-coupling-`, lưu ở `results/probe/coupling/<batch_id>/`: `trace.sqlite`,
`runs.csv`, `manifest.json`.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

from agent.core import load_core_params  # noqa: E402
from agent.llm_client import LLMClient  # noqa: E402
from agent.prompts import load_prompt_config, template_hash  # noqa: E402
from attack.payloads.schema import load_payloads  # noqa: E402
from attack.runner import (  # noqa: E402
    HARNESS_PREFIX,
    AttackRunSpec,
    RunContext,
    build_defense,
    build_defenses,
    export_runs_csv,
    load_carriers,
    run_one_attack,
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
PROBE_DIR = ROOT / "results" / "probe" / "coupling"
PAYLOADS = PROBE_DIR / "payloads_coupling.yaml"
TARGETS = ("A2", "A3")

# Mỗi payload dò bám đúng một tác vụ chở (tool/nghiệp vụ khớp).
PAYLOAD_CARRIER = {
    "P-T1-G3-VI-910": "CT-01",
    "P-T3-G3-VI-910": "CT-02",
    "P-T3-G1-VI-910": "CT-03",
    "P-T3-G2-VI-910": "CT-04",
    "P-T3-G1-VI-911": "CT-05",
    "P-T3-G2-VI-911": "CT-06",
}


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repeats", type=int, default=3, help="số lần lặp mỗi (payload, target)")
    parser.add_argument("--estimate-usd", type=float)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--payloads", default=str(PAYLOADS), help="file payload dò")
    parser.add_argument("--targets", nargs="+", help="tập con target (mặc định A2 A3)")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    TG = tuple(args.targets) if args.targets else TARGETS
    exp = load_experiment()
    payloads, report = load_payloads(args.payloads)
    if not report.all_ok:
        print("payload dò sai schema:", report.errors_by_id)
        return 2
    corpus = {p["id"]: p for p in payloads}
    off = snapshot_json(build_defense("off"))

    def _carrier(p):  # carrier ghim ở only_carriers, hoặc bảng cứng cho file cũ
        only = p.get("only_carriers")
        return only[0] if only else PAYLOAD_CARRIER[p["id"]]

    specs = [
        AttackRunSpec(
            repeat_idx=r,
            target_id=t,
            channel=p["channels"][0],
            technique=p["technique"]["code"],
            goal=p["goal"],
            attacker_mode="blind",
            defense_config=off,
            carrier_task_id=_carrier(p),
            payload_id=p["id"],
        )
        for p in payloads
        for t in TG
        for r in range(args.repeats)
    ]
    print(f"{len(payloads)} payload × {len(TG)} target × {args.repeats} lặp = {len(specs)} run")
    for p in payloads:
        print(f"  {p['id']} {p['channels'][0]}·{p['goal']} → {_carrier(p)}")
    if args.plan_only:
        return 0

    commit = lab_git_commit()
    if commit.endswith("-dirty"):
        print(f"Cây làm việc chưa commit ({commit}) — commit rồi chạy lại:")
        print("\n".join(f"  {line}" for line in uncommitted_changes()))
        return 2
    if args.estimate_usd is None:
        parser.error("cần --estimate-usd để mở lô")

    batch_id = f"probe-coupling-{_stamp()}"
    batch_dir = PROBE_DIR / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    engine = open_store(batch_dir / "trace.sqlite")
    prices = load_prices(MODELS, list(TG))
    guard = budget_from_env(args.estimate_usd)
    models = {t: LLMClient(t, config_path=MODELS, log_path=LOG, run_id=batch_id) for t in TG}
    swept = sweep_stale_run_dirs()
    if swept:
        print(f"Đã dọn {len(swept)} thư mục run cũ còn sót.")
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
        "task": "STT-61 (dò payload gắn ngữ cảnh)",
        "batch_id": batch_id,
        "lab_git_commit": commit,
        "env_hash": ctx.env_hash,
        "prompt_variant": prompt_cfg.active,
        "models": {t: m.model for t, m in models.items()},
        "defense": "off",
        "repeats": args.repeats,
        "payload_carrier": {p["id"]: _carrier(p) for p in payloads},
        "payloads_file": args.payloads,
        "estimate_usd": args.estimate_usd,
        "started_at_utc": _stamp(),
    }

    status = "ok"
    t0 = time.monotonic()
    try:
        for i, spec in enumerate(specs, start=1):
            run_id = run_one_attack(spec, ctx)
            import sqlite3

            con = sqlite3.connect(batch_dir / "trace.sqlite")
            row = con.execute(
                "SELECT outcome, blocked_by, delivered, g2_spontaneous FROM runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
            con.close()
            spent = sum(spend_from_log(LOG, prices, run_ids=[batch_id]).values())
            status = guard.status(spent)
            print(
                f"[{i}/{len(specs)}] {spec.target_id} {spec.payload_id} {spec.carrier_task_id} r{spec.repeat_idx}"
                f" → {row[0]}/{row[1] or '-'} deliv={row[2]} spont={row[3]}"
                f" · {spent:.2f} USD · {status} · {(time.monotonic() - t0) / 60:.1f} phút",
                flush=True,
            )
            if status == "stop":
                print("DỪNG: chi phí lô vượt 120% dự toán hoặc chạm hạn mức tổng.")
                break
    finally:
        manifest["finished_at_utc"] = _stamp()
        manifest["spent_usd"] = sum(spend_from_log(LOG, prices, run_ids=[batch_id]).values())
        manifest["budget_status"] = status
        (batch_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        export_runs_csv(engine, batch_id, batch_dir / "runs.csv")

    import sqlite3

    con = sqlite3.connect(batch_dir / "trace.sqlite")
    for t in TG:
        n, s = con.execute(
            "SELECT COUNT(*), SUM(outcome='success') FROM runs WHERE target_id=? AND parse_error=0",
            (t,),
        ).fetchone()
        print(f"{t}: {s or 0}/{n} run thành công")
    con.close()
    print(f"  runs: {(batch_dir / 'runs.csv').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
