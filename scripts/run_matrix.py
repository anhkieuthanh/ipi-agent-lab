"""Chạy một khối ma trận thực nghiệm tấn công (STT-46). Một lô = một khối.

Logic ở `src/attack/runner.py`; script này là lớp CLI mỏng. Trước khi mở lô, từ chối khi: cây làm
việc chưa commit; khối còn trường null (`unresolved`); đơn giá target còn null (`config/models.yaml`);
`COST_BUDGET_USD_TOTAL` chưa set; model trong `.env` lệch bản đã pin. Sau mỗi run, `BudgetGuard` so
chi phí lô với `--estimate-usd`; vượt 120% hay chạm hạn mức tổng thì dừng (CLAUDE.md mục 4).

CHECKPOINT/RESUME: mỗi run commit ngay vào `trace.sqlite`. Chạy lại cùng `--batch-id` thì bỏ qua đơn
vị đã có — lô bị ngắt chạy tiếp, không chạy lại phần đã xong.

PHẠM VI: chỉ preset `off` chạy được (D1–D4 chưa có). Khối chạy được: B1, B6.

    # Xem số run của một khối, không gọi API
    uv run python scripts/run_matrix.py --block B1 --plan-only
    # Chạy thử phần corpus đã phủ: K1, T1–T5, 2 run/ô, 1 model
    uv run python scripts/run_matrix.py --block B1 --dry-run --channels K1 \
        --techniques T1 T2 T3 T4 T5 --per-cell 2 --targets A3 --estimate-usd 2
    # Lô thật; chạy lại cùng --batch-id để tiếp tục lô bị ngắt
    uv run python scripts/run_matrix.py --block B1 --estimate-usd <dự toán>
    # Chỉ xuất lại CSV từ store của một lô
    uv run python scripts/run_matrix.py --block B1 --batch-id attack-B1-... --export-only
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
from agent.prompts import template_hash  # noqa: E402
from attack.runner import (  # noqa: E402
    HARNESS_PREFIX,
    AttackRunnerError,
    RunContext,
    done_specs,
    export_runs_csv,
    load_carriers,
    load_corpus,
    plan_block,
    run_one_attack,
)
from eval.canary import sweep_stale_run_dirs  # noqa: E402
from eval.experiment import load_experiment, unresolved, validate  # noqa: E402
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
BATCH_ROOT = ROOT / "results" / "attack_matrix"
TABLES = ROOT / "results" / "tables"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--block", required=True, help="mã khối B1…B6")
    parser.add_argument("--batch-id", help="tiếp tục / xuất lại một lô đã có")
    parser.add_argument("--estimate-usd", type=float, help="dự toán chi phí của lô (USD)")
    parser.add_argument("--plan-only", action="store_true", help="in số run, không gọi API")
    parser.add_argument("--export-only", action="store_true", help="chỉ xuất CSV từ store")
    dry = parser.add_argument_group("chạy thử (chỉ cùng --dry-run)")
    dry.add_argument("--dry-run", action="store_true", help="lô thử, tiền tố dryrun-")
    dry.add_argument("--targets", nargs="+", help="tập con target của khối")
    dry.add_argument("--presets", nargs="+", help="tập con preset của khối")
    dry.add_argument("--channels", nargs="+", help="tập con kênh")
    dry.add_argument("--techniques", nargs="+", help="tập con kỹ thuật")
    dry.add_argument("--goals", nargs="+", help="tập con mục tiêu")
    dry.add_argument("--per-cell", type=int, help="số run mỗi ô thay cho n_per_cell")
    dry.add_argument("--allow-dirty", action="store_true", help="cho chạy trên cây chưa commit")
    args = parser.parse_args()

    narrow = [
        args.targets,
        args.presets,
        args.channels,
        args.techniques,
        args.goals,
        args.per_cell,
        args.allow_dirty,
    ]
    if any(narrow) and not args.dry_run:
        parser.error("các cờ thu hẹp chỉ dùng với --dry-run")
    if args.batch_id and args.dry_run != args.batch_id.startswith("dryrun-"):
        parser.error("--dry-run phải đi với batch_id tiền tố dryrun- và ngược lại")

    load_dotenv(ROOT / ".env")
    exp = load_experiment()
    problems = validate(exp) + unresolved(exp, args.block)
    if problems:
        print(f"experiment.yaml chưa sẵn sàng cho {args.block}:\n  " + "\n  ".join(problems))
        return 2

    corpus = load_corpus()
    carriers = load_carriers()
    seed = exp.raw["run_order"]["seed"]
    try:
        specs = plan_block(
            exp,
            args.block,
            corpus=corpus,
            carriers=carriers,
            seed=seed,
            targets=args.targets,
            presets=args.presets,
            n_per_cell=args.per_cell,
            channels=args.channels,
            techniques=args.techniques,
            goals=args.goals,
        )
    except AttackRunnerError as e:
        print(str(e))
        return 2
    targets = sorted({s.target_id for s in specs})

    prefix = f"dryrun-attack-{args.block}" if args.dry_run else f"attack-{args.block}"
    batch_id = args.batch_id or f"{prefix}-{_stamp()}"
    batch_dir = BATCH_ROOT / batch_id
    store = batch_dir / "trace.sqlite"
    tables_dir = batch_dir if args.dry_run else TABLES
    runs_csv = tables_dir / f"{batch_id}_runs.csv"

    if (args.plan_only or args.export_only) and not store.is_file():
        if args.export_only:
            parser.error(f"không có store {store.relative_to(ROOT)}")
        print(f"{batch_id}: {len(specs)} run theo kế hoạch, chưa chạy run nào")
        return 0

    engine = open_store(store)
    done = done_specs(engine, batch_id)
    todo = [s for s in specs if s not in done]
    print(f"{batch_id}: {len(specs)} run theo kế hoạch, {len(done)} đã có, còn {len(todo)}")
    if args.plan_only:
        return 0
    if args.export_only:
        print(f"  runs: {export_runs_csv(engine, batch_id, runs_csv).relative_to(ROOT)}")
        return 0

    commit = lab_git_commit()
    if commit.endswith("-dirty") and not args.allow_dirty:
        print(f"Cây làm việc chưa commit ({commit}) — commit rồi chạy lại:")
        print("\n".join(f"  {line}" for line in uncommitted_changes()))
        return 2
    if args.estimate_usd is None:
        parser.error("cần --estimate-usd (dự toán lô) để mở lô")

    prices = load_prices(MODELS, targets)
    guard = budget_from_env(args.estimate_usd)
    models = {t: LLMClient(t, config_path=MODELS, log_path=LOG, run_id=batch_id) for t in targets}
    env_hash = compute_env_hash(template_hash(), TOOLS, commit)
    swept = sweep_stale_run_dirs()
    if swept:
        print(f"Đã dọn {len(swept)} thư mục run cũ còn sót.")

    ctx = RunContext(
        engine=engine,
        batch_id=batch_id,
        env_hash=env_hash,
        harness_version=f"{HARNESS_PREFIX}{commit}",
        models=models,
        tools=build_harness_tools(),
        corpus_by_id={p["id"]: p for p in corpus},
        carriers_by_id={c["id"]: c for c in carriers},
        core_params=load_core_params(),
        kb_top_k=exp.fixed["kb_top_k"],
    )
    manifest = {
        "task": "STT-46",
        "block": args.block,
        "batch_id": batch_id,
        "dry_run": args.dry_run,
        "lab_git_commit": commit,
        "env_hash": env_hash,
        "models": {t: m.model for t, m in models.items()},
        "targets": targets,
        "n_planned": len(specs),
        "estimate_usd": args.estimate_usd,
        "started_at_utc": _stamp(),
    }
    batch_dir.mkdir(parents=True, exist_ok=True)

    status = "ok"
    t0 = time.monotonic()
    try:
        for i, spec in enumerate(todo, start=1):
            run_one_attack(spec, ctx)
            spent = sum(spend_from_log(LOG, prices, run_ids=[batch_id]).values())
            status = guard.status(spent)
            print(
                f"[{i}/{len(todo)}] {spec.target_id} {spec.channel}·{spec.technique}·{spec.goal}"
                f" {spec.payload_id} r{spec.repeat_idx} · {spent:.2f} USD · {status}"
                f" · {(time.monotonic() - t0) / 60:.1f} phút",
                flush=True,
            )
            if status == "stop":
                print("DỪNG: chi phí lô vượt 120% dự toán hoặc chạm hạn mức tổng.")
                break
    finally:
        manifest["finished_at_utc"] = _stamp()
        manifest["spent_usd"] = sum(spend_from_log(LOG, prices, run_ids=[batch_id]).values())
        manifest["budget_status"] = status
        path = batch_dir / "manifest.json"
        sessions = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
        path.write_text(
            json.dumps([*sessions, manifest], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    print(f"  runs: {export_runs_csv(engine, batch_id, runs_csv).relative_to(ROOT)}")
    return 3 if status == "stop" else 0


if __name__ == "__main__":
    raise SystemExit(main())
