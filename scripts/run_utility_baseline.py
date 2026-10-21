"""Chạy lượt USR nền (STT-37): 60 câu lành tính × A1–A3 × 3 lần, phòng thủ tắt.

Tham số lượt ở `config/experiment.yaml` khóa `utility_baseline`; logic ở `src/eval/utility_baseline.py`.
Số này là mốc TRƯỚC hiệu chỉnh độ khó (giao thức mục 8, N6).

Trước khi mở lô, script từ chối khi: cây làm việc chưa commit; `utility_baseline` còn trường null;
đơn giá của target hay judge còn null (`config/models.yaml`); `COST_BUDGET_USD_TOTAL` chưa set;
model trong `.env` lệch bản đã pin. Sau mỗi run, `BudgetGuard` so chi phí lô với `--estimate-usd`;
vượt 120% hay chạm hạn mức tổng thì dừng (CLAUDE.md mục 4).

Kết quả của một lô nằm ở `results/usr_baseline/<batch_id>/`: `trace.sqlite` (bảng runs/steps),
`judge.jsonl` (lý do của judge), `manifest.json`. Lô thật xuất ba CSV vào `results/tables/`; lô thử
(`--dry-run`, tiền tố `dryrun-`) xuất vào thư mục lô, không bao giờ ghi `results/tables/`.

    # Xem số run, không gọi API
    uv run python scripts/run_utility_baseline.py --plan-only
    # Chạy thử 1 câu mỗi nhóm × 3 model × 1 lần để đo token/run trước khi dự toán
    uv run python scripts/run_utility_baseline.py --dry-run --per-group 1 --repeats 1 --estimate-usd 2
    # Lô thật; chạy lại cùng --batch-id để tiếp tục lô bị ngắt
    uv run python scripts/run_utility_baseline.py --estimate-usd <dự toán>
    # Chỉ xuất lại CSV từ store của một lô
    uv run python scripts/run_utility_baseline.py --batch-id usr-baseline-... --export-only
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

from agent.core import load_core_params  # noqa: E402
from agent.llm_client import JUDGE_ID, LLMClient  # noqa: E402
from agent.prompts import template_hash  # noqa: E402
from eval.canary import sweep_stale_run_dirs  # noqa: E402
from eval.experiment import load_experiment, unresolved, validate  # noqa: E402
from eval.judge import JudgeConfig  # noqa: E402
from eval.metrics import TcpCi  # noqa: E402
from eval.utility_baseline import (  # noqa: E402
    HARNESS_PREFIX,
    UNIT_ID,
    RunContext,
    build_harness_tools,
    done_specs,
    export_tables,
    plan_runs,
    run_one,
)
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
BATCH_ROOT = ROOT / "results" / "usr_baseline"
TABLES = ROOT / "results" / "tables"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _select_queries(queries: list[dict], ids: list[str] | None, per_group: int | None) -> list[str]:
    if ids:
        known = {q["id"] for q in queries}
        unknown = sorted(set(ids) - known)
        if unknown:
            raise SystemExit(f"Câu không có trong bộ đo: {unknown}")
        return ids
    if per_group:
        taken: dict[str, list[str]] = defaultdict(list)
        for q in queries:
            if len(taken[q["group"]]) < per_group:
                taken[q["group"]].append(q["id"])
        return [qid for ids_ in taken.values() for qid in ids_]
    return [q["id"] for q in queries]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--batch-id", help="tiếp tục / xuất lại một lô đã có")
    parser.add_argument("--estimate-usd", type=float, help="dự toán chi phí của lô (USD)")
    parser.add_argument("--plan-only", action="store_true", help="in số run, không gọi API")
    parser.add_argument("--export-only", action="store_true", help="chỉ xuất CSV từ store")
    dry = parser.add_argument_group("chạy thử (chỉ cùng --dry-run)")
    dry.add_argument("--dry-run", action="store_true", help="lô thử, tiền tố dryrun-")
    dry.add_argument("--targets", nargs="+", help="tập con target của utility_baseline")
    dry.add_argument("--queries", nargs="+", help="tập con mã câu")
    dry.add_argument("--per-group", type=int, help="lấy n câu đầu mỗi nhóm U1–U5")
    dry.add_argument("--repeats", type=int, help="số lần lặp thay cho config")
    dry.add_argument("--allow-dirty", action="store_true", help="cho chạy trên cây chưa commit")
    args = parser.parse_args()

    narrowed = any([args.targets, args.queries, args.per_group, args.repeats, args.allow_dirty])
    if narrowed and not args.dry_run:
        parser.error(
            "--targets/--queries/--per-group/--repeats/--allow-dirty chỉ dùng với --dry-run"
        )
    if args.batch_id and args.dry_run != args.batch_id.startswith("dryrun-"):
        parser.error("--dry-run phải đi với batch_id tiền tố dryrun- và ngược lại")

    load_dotenv(ROOT / ".env")
    exp = load_experiment()
    problems = validate(exp) + unresolved(exp, UNIT_ID)
    if problems:
        print("experiment.yaml chưa sẵn sàng:\n  " + "\n  ".join(problems))
        return 2
    unit = exp.unit(UNIT_ID)
    targets = args.targets or list(unit.targets)
    if set(targets) - set(unit.targets):
        parser.error(f"--targets phải thuộc {list(unit.targets)}")
    repeats = args.repeats or unit.repeats
    benign = json.loads(exp.contract_path("benign_queries").read_text(encoding="utf-8"))["queries"]
    query_ids = _select_queries(benign, args.queries, args.per_group)

    prefix = "dryrun-usr-baseline" if args.dry_run else "usr-baseline"
    batch_id = args.batch_id or f"{prefix}-{_stamp()}"
    batch_dir = BATCH_ROOT / batch_id
    store = batch_dir / "trace.sqlite"
    if (args.plan_only or args.export_only) and not store.is_file():
        if args.export_only:
            parser.error(f"không có store {store.relative_to(ROOT)}")
        specs = plan_runs(targets, query_ids, repeats=repeats, seed=exp.raw["run_order"]["seed"])
        print(f"{batch_id}: {len(specs)} run theo kế hoạch, chưa chạy run nào")
        return 0
    engine = open_store(store)
    judge_log = batch_dir / "judge.jsonl"
    tables_dir = batch_dir / "tables" if args.dry_run else TABLES
    tcp = TcpCi.from_experiment(exp)
    review_ratio = exp.raw["stopping"]["parse_error_review_ratio"]

    specs = plan_runs(targets, query_ids, repeats=repeats, seed=exp.raw["run_order"]["seed"])
    done = done_specs(engine, batch_id)
    todo = [s for s in specs if s not in done]
    print(f"{batch_id}: {len(specs)} run theo kế hoạch, {len(done)} đã có, còn {len(todo)}")
    if args.plan_only:
        return 0
    if args.export_only:
        paths = export_tables(
            engine, batch_id, judge_log, tables_dir, tcp=tcp, review_ratio=review_ratio
        )
        print("\n".join(f"  {k}: {v.relative_to(ROOT)}" for k, v in paths.items()))
        return 0

    commit = lab_git_commit()
    if commit.endswith("-dirty") and not args.allow_dirty:
        print(f"Cây làm việc chưa commit ({commit}) — commit rồi chạy lại:")
        print("\n".join(f"  {line}" for line in uncommitted_changes()))
        return 2
    if args.estimate_usd is None:
        parser.error("cần --estimate-usd (dự toán lô) để mở lô")
    prices = load_prices(MODELS, [*targets, JUDGE_ID])
    guard = budget_from_env(args.estimate_usd)

    models = {t: LLMClient(t, config_path=MODELS, log_path=LOG, run_id=batch_id) for t in targets}
    judge = LLMClient(JUDGE_ID, config_path=MODELS, log_path=LOG, run_id=batch_id)
    judge_cfg = JudgeConfig.load()
    env_hash = compute_env_hash(template_hash(), TOOLS, commit)
    task_types = {qid: tt for tt, ids in exp.raw["benign_task_types"].items() for qid in ids}
    swept = sweep_stale_run_dirs()
    if swept:
        print(f"Đã dọn {len(swept)} thư mục run cũ còn sót.")

    ctx = RunContext(
        engine=engine,
        batch_id=batch_id,
        env_hash=env_hash,
        harness_version=f"{HARNESS_PREFIX}{commit}",
        models=models,
        judge_client=judge,
        judge_cfg=judge_cfg,
        tools=build_harness_tools(),
        queries={q["id"]: q for q in benign},
        task_types=task_types,
        core_params=load_core_params(),
        judge_log=judge_log,
    )
    manifest = {
        "task": "STT-37",
        "batch_id": batch_id,
        "dry_run": args.dry_run,
        "lab_git_commit": commit,
        "env_hash": env_hash,
        "judge_model": judge.model,
        "judge_prompt_hash": judge_cfg.prompt_hash(),
        "models": {t: m.model for t, m in models.items()},
        "targets": targets,
        "repeats": repeats,
        "query_ids": query_ids,
        "n_planned": len(specs),
        "estimate_usd": args.estimate_usd,
        "started_at_utc": _stamp(),
    }
    batch_dir.mkdir(parents=True, exist_ok=True)

    status = "ok"
    t0 = time.monotonic()
    try:
        for i, spec in enumerate(todo, start=1):
            run_one(spec, ctx)
            spent = sum(spend_from_log(LOG, prices, run_ids=[batch_id]).values())
            status = guard.status(spent)
            print(
                f"[{i}/{len(todo)}] {spec.target_id} {spec.benign_query_id} r{spec.repeat_idx}"
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
        # Mỗi lần chạy (kể cả chạy tiếp lô bị ngắt) thêm một phiên; không ghi đè phiên trước.
        path = batch_dir / "manifest.json"
        sessions = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
        path.write_text(
            json.dumps([*sessions, manifest], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    paths = export_tables(
        engine, batch_id, judge_log, tables_dir, tcp=tcp, review_ratio=review_ratio
    )
    print("\n".join(f"  {k}: {v.relative_to(ROOT)}" for k, v in paths.items()))
    return 3 if status == "stop" else 0


if __name__ == "__main__":
    raise SystemExit(main())
