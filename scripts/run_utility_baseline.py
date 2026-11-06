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
    # Lô thật trên 3 tiến trình song song; chạy lại cùng --batch-id vẫn tiếp tục được
    uv run python scripts/run_utility_baseline.py --estimate-usd <dự toán> --workers 3
    # Chỉ xuất lại CSV từ store của một lô
    uv run python scripts/run_utility_baseline.py --batch-id usr-baseline-... --export-only

SONG SONG (`--workers N`, `obs.parallel` — cùng cơ chế `run_matrix.py`): phần còn lại chia cho N tiến
trình con, mỗi con có kho phiếu + collection Qdrant riêng, ghi `trace-s<i>.sqlite` và
`judge-s<i>.jsonl`; mẹ gộp vào `trace.sqlite` / `judge.jsonl` của lô. Run lành tính không đọc lại
MailHog nên dùng chung MailHog an toàn. Mỗi lúc chỉ một lô (`obs.worker.batch_lock`).
"""

from __future__ import annotations

import argparse
import json
import signal
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
from obs.parallel import (  # noqa: E402
    EXIT_BUDGET,
    EXIT_STOPPED,
    merge_leftover_shards,
    run_sharded,
    shard_path,
    stop_file,
)
from obs.trace import (  # noqa: E402
    compute_env_hash,
    lab_git_commit,
    open_store,
    uncommitted_changes,
)
from obs.worker import WORKER_ENV, BatchLockedError, batch_lock, worker_id  # noqa: E402

MODELS = ROOT / "config" / "models.yaml"
TOOLS = ROOT / "config" / "tools.yaml"
LOG = ROOT / "logs" / "llm_client.jsonl"
BATCH_ROOT = ROOT / "results" / "usr_baseline"
TABLES = ROOT / "results" / "tables"
LOCK = ROOT / "logs" / "batch.lock"


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
    parser.add_argument("--workers", type=int, default=1, help="số tiến trình chạy song song")
    parser.add_argument("--shard", help=argparse.SUPPRESS)  # "i/N", do tiến trình mẹ truyền
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers phải ≥ 1")
    if args.shard and not args.batch_id:
        parser.error("--shard chỉ do tiến trình mẹ truyền, kèm --batch-id")
    if args.workers > 1 and not args.shard and worker_id() is not None:
        parser.error(f"{WORKER_ENV} đã đặt sẵn — tiến trình mẹ phải chạy với collection/kho gốc")

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
    judge_log = batch_dir / "judge.jsonl"
    tables_dir = batch_dir / "tables" if args.dry_run else TABLES
    specs = plan_runs(targets, query_ids, repeats=repeats, seed=exp.raw["run_order"]["seed"])
    run = dict(args=args, exp=exp, benign=benign, targets=targets, repeats=repeats,
               query_ids=query_ids, specs=specs, batch_id=batch_id, batch_dir=batch_dir,
               store=store, judge_log=judge_log, tables_dir=tables_dir)

    if args.plan_only or args.export_only:
        engine = open_store(store)
        done = done_specs(engine, batch_id)
        print(f"{batch_id}: {len(specs)} run theo kế hoạch, {len(done)} đã có, "
              f"còn {len(specs) - len(done)}")
        if args.export_only:
            _export(engine, **run)
        return 0
    if args.estimate_usd is None:
        parser.error("cần --estimate-usd (dự toán lô) để mở lô")

    signal.signal(signal.SIGTERM, signal.default_int_handler)  # SIGTERM → KeyboardInterrupt
    if args.shard:  # con chạy dưới khóa của mẹ
        return _run_shard(**run)
    try:
        with batch_lock(LOCK):
            return _run_batch(**run)
    except BatchLockedError as e:
        print(f"Không mở lô: {e}")
        return 2


def _judge_shard(batch_dir: Path, i: int) -> Path:
    return batch_dir / f"judge-s{i}.jsonl"


def _merge_judge_shards(judge_log: Path) -> None:
    """Nối `judge-s<i>.jsonl` vào `judge.jsonl` rồi xóa shard (gọi SAU khi trace đã gộp)."""
    shards = sorted(judge_log.parent.glob("judge-s*.jsonl"))
    if not shards:
        return
    with judge_log.open("a", encoding="utf-8") as out:
        for sh in shards:
            text = sh.read_text(encoding="utf-8")
            if text and not text.endswith("\n"):
                text += "\n"
            out.write(text)
    for sh in shards:
        sh.unlink()


def _export(engine, *, exp, benign, batch_id, judge_log, tables_dir, **_) -> None:
    paths = export_tables(
        engine,
        batch_id,
        judge_log,
        tables_dir,
        tcp=TcpCi.from_experiment(exp),
        review_ratio=exp.raw["stopping"]["parse_error_review_ratio"],
        queries={q["id"]: q for q in benign},
    )
    print("\n".join(f"  {k}: {v.relative_to(ROOT)}" for k, v in paths.items()))


def _check_commit(args) -> str | None:
    commit = lab_git_commit()
    if commit.endswith("-dirty") and not args.allow_dirty:
        print(f"Cây làm việc chưa commit ({commit}) — commit rồi chạy lại:")
        print("\n".join(f"  {line}" for line in uncommitted_changes()))
        return None
    return commit


def _context(*, exp, benign, targets, batch_id, engine, commit, judge_log) -> RunContext:
    return RunContext(
        engine=engine,
        batch_id=batch_id,
        env_hash=compute_env_hash(template_hash(), TOOLS, commit),
        harness_version=f"{HARNESS_PREFIX}{commit}",
        models={t: LLMClient(t, config_path=MODELS, log_path=LOG, run_id=batch_id) for t in targets},
        judge_client=LLMClient(JUDGE_ID, config_path=MODELS, log_path=LOG, run_id=batch_id),
        judge_cfg=JudgeConfig.load(),
        tools=build_harness_tools(),
        queries={q["id"]: q for q in benign},
        task_types={qid: tt for tt, ids in exp.raw["benign_task_types"].items() for qid in ids},
        core_params=load_core_params(),
        judge_log=judge_log,
    )


def _spent(prices, batch_id: str) -> float:
    return sum(spend_from_log(LOG, prices, run_ids=[batch_id]).values())


def _append_manifest(batch_dir: Path, manifest: dict) -> None:
    # Mỗi lần chạy (kể cả chạy tiếp lô bị ngắt) thêm một phiên; không ghi đè phiên trước.
    path = batch_dir / "manifest.json"
    sessions = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
    path.write_text(
        json.dumps([*sessions, manifest], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _run_shard(*, args, exp, benign, targets, specs, batch_id, batch_dir, store, **_) -> int:
    """Tiến trình con: phần `todo[i::N]`, ghi trace/judge shard riêng; mẹ gộp, ghi manifest, xuất."""
    i, n = (int(x) for x in args.shard.split("/"))
    done = done_specs(open_store(store), batch_id)
    todo = [s for s in specs if s not in done][i::n]
    commit = _check_commit(args)
    if commit is None:
        return 2
    prices = load_prices(MODELS, [*targets, JUDGE_ID])
    guard = budget_from_env(args.estimate_usd)
    ctx = _context(exp=exp, benign=benign, targets=targets, batch_id=batch_id,
                   engine=open_store(shard_path(batch_dir, i)), commit=commit,
                   judge_log=_judge_shard(batch_dir, i))
    stop = stop_file(batch_dir)
    t0 = time.monotonic()
    for k, spec in enumerate(todo, start=1):
        # Kiểm TRƯỚC khi nhận run: con khác/mẹ đã ra lệnh dừng, hoặc ngân sách đã chạm ngưỡng.
        if stop.exists():
            print("DỪNG: có file STOP của lô.", flush=True)
            return EXIT_STOPPED
        if guard.status(_spent(prices, batch_id)) == "stop":
            print("DỪNG trước run: chi phí lô vượt 120% dự toán hoặc chạm hạn mức tổng.", flush=True)
            return EXIT_BUDGET
        run_one(spec, ctx)
        print(
            f"[s{i} {k}/{len(todo)}] {spec.target_id} {spec.benign_query_id} r{spec.repeat_idx}"
            f" · {_spent(prices, batch_id):.2f} USD · {(time.monotonic() - t0) / 60:.1f} phút",
            flush=True,
        )
    return 0


def _run_batch(*, args, exp, benign, targets, repeats, query_ids, specs, batch_id, batch_dir,
               store, judge_log, tables_dir) -> int:
    merged = merge_leftover_shards(store) if store.is_file() else []
    if merged:
        print(f"Đã gộp {len(merged)} shard còn sót của lần chạy trước vào {store.relative_to(ROOT)}.")
    _merge_judge_shards(judge_log)
    engine = open_store(store)
    done = done_specs(engine, batch_id)
    todo = [s for s in specs if s not in done]
    print(f"{batch_id}: {len(specs)} run theo kế hoạch, {len(done)} đã có, còn {len(todo)}")

    commit = _check_commit(args)
    if commit is None:
        return 2
    prices = load_prices(MODELS, [*targets, JUDGE_ID])
    guard = budget_from_env(args.estimate_usd)
    ctx = _context(exp=exp, benign=benign, targets=targets, batch_id=batch_id, engine=engine,
                   commit=commit, judge_log=judge_log)
    parallel = args.workers > 1 and len(todo) > 1
    if not parallel:  # song song: run_sharded dọn dưới khóa, kèm tài nguyên worker
        swept = sweep_stale_run_dirs()
        if swept:
            print(f"Đã dọn {len(swept)} thư mục run cũ còn sót.")
    manifest = {
        "task": "STT-37",
        "batch_id": batch_id,
        "dry_run": args.dry_run,
        "lab_git_commit": commit,
        "env_hash": ctx.env_hash,
        "judge_model": ctx.judge_client.model,
        "judge_prompt_hash": ctx.judge_cfg.prompt_hash(),
        "models": {t: m.model for t, m in ctx.models.items()},
        "targets": targets,
        "repeats": repeats,
        "query_ids": query_ids,
        "n_planned": len(specs),
        "estimate_usd": args.estimate_usd,
        "workers": args.workers if parallel else 1,
        "started_at_utc": _stamp(),
    }
    batch_dir.mkdir(parents=True, exist_ok=True)
    run = dict(exp=exp, benign=benign, batch_id=batch_id, judge_log=judge_log,
               tables_dir=tables_dir)
    if parallel:
        return _run_parallel(args, batch_dir, store, manifest, prices, guard, engine,
                             len(todo), run)

    status = "ok"
    t0 = time.monotonic()
    try:
        for i, spec in enumerate(todo, start=1):
            run_one(spec, ctx)
            spent = _spent(prices, batch_id)
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
        manifest["spent_usd"] = _spent(prices, batch_id)
        manifest["budget_status"] = status
        _append_manifest(batch_dir, manifest)

    _export(engine, **run)
    return 3 if status == "stop" else 0


def _run_parallel(args, batch_dir, store, manifest, prices, guard, engine, n_todo, run) -> int:
    n, batch_id = args.workers, run["batch_id"]
    engine.dispose()  # mẹ không ghi store trong lúc con chạy; gộp thay file store ở cuối
    child_argv = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--batch-id", batch_id]
    print(f"{n} tiến trình con, {n_todo} run", flush=True)
    res = run_sharded(batch_id=batch_id, batch_dir=batch_dir, store=store, n=n,
                      child_argv=child_argv, cwd=ROOT, log_path=LOG, prices=prices, guard=guard,
                      sweep=sweep_stale_run_dirs)
    if not res.save_errors:
        try:
            _merge_judge_shards(run["judge_log"])
        except Exception as e:  # noqa: BLE001 — shard judge còn trên đĩa, lần chạy sau gộp tiếp
            res.save_errors.append(f"gộp judge.jsonl: {e!r}")
    try:
        spent = _spent(prices, batch_id)
    except Exception as e:  # noqa: BLE001
        spent = None
        res.save_errors.append(f"đọc chi phí: {e!r}")
    manifest.update({
        "finished_at_utc": _stamp(),
        "spent_usd": spent,
        "budget_status": res.status,
        "worker_ids": [f"{batch_id}-{i}" for i in range(n)],
        "shard_exit_codes": res.exit_codes,
        "kb_worker_collections": res.kb_copies,
        "cleanup_errors": res.cleanup_errors,
        "save_status": "error" if res.save_errors else "ok",
        "save_errors": res.save_errors,
    })
    _append_manifest(batch_dir, manifest)
    if res.cleanup_errors:
        print("Lỗi dọn tài nguyên (ghi trong manifest):", *res.cleanup_errors, sep="\n  ", flush=True)
    if res.save_errors:
        print("LỖI LƯU KẾT QUẢ (ghi trong manifest):", *res.save_errors, sep="\n  ", flush=True)
    else:
        _export(open_store(store), **run)
    print(f"Kết thúc: {spent if spent is None else f'{spent:.2f}'} USD · {res.status}"
          f" · lưu {manifest['save_status']} · mã thoát con {res.exit_codes}", flush=True)
    if res.save_errors or res.status not in ("ok", "stop"):
        return 2
    return 3 if res.status == "stop" else 0


if __name__ == "__main__":
    raise SystemExit(main())
