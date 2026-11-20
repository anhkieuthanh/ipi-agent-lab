"""Chạy khối tấn công thích ứng B5 (RQ5): chuỗi ≤ 3 vòng trên ô S_adp × 5 preset × A2.

Kế hoạch ở `attack.adaptive_block.plan_adaptive`; một chuỗi chạy bằng `attack.adaptive.run_chain`
(ranh giới PH1: kẻ tấn công chỉ thấy `final_answer`, hộp thư, phiếu và hit listener của nó). Kẻ tấn
công viết lại payload bằng khối `attacker` của `config/models.yaml` (`blocks.B5.attacker_model`).
Biến thể prompt `active` (`baseline`) như mọi khối ngoài B1.

Trước khi mở lô, script từ chối khi: cây làm việc chưa commit; B5 còn trường null (`cells.selected`
điền bằng `scripts/select_cells.py --block B5`); đã có lô khác đang chạy (`batch_lock`). Sau mỗi
chuỗi `BudgetGuard` so chi phí phiên (model đích + attacker) với `--estimate-usd`; vượt 120% thì
dừng. Một tiến trình: MailHog dùng chung, kẻ tấn công đọc hộp thư làm phản hồi.

Kết quả ở `results/attack_matrix/<batch_id>/`: `trace.sqlite`, `chains.jsonl` (một dòng mỗi chuỗi
đã xong), `manifest.json`; lô thật xuất `results/tables/<batch_id>_{runs,chains}.csv`.

    uv run python scripts/run_adaptive.py --block B5 --plan-only
    uv run python scripts/run_adaptive.py --block B5 --dry-run --presets d1_only --chains-per-cell 1 \\
        --estimate-usd 2
    uv run python scripts/run_adaptive.py --block B5 --estimate-usd 25
    uv run python scripts/run_adaptive.py --block B5 --batch-id attack-B5-... --estimate-usd 10
"""

from __future__ import annotations

import argparse
import csv
import json
import signal
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402
from sqlmodel import Session, delete, select  # noqa: E402

from agent.core import load_core_params  # noqa: E402
from agent.llm_client import ATTACKER_ID, LLMClient  # noqa: E402
from agent.prompts import load_prompt_config, template_hash  # noqa: E402
from attack.adaptive import (  # noqa: E402
    AdaptiveChainSpec,
    LLMAdaptiveAttacker,
    check_adaptive_invariants,
    run_chain,
)
from attack.adaptive_block import ChainPlan, plan_adaptive  # noqa: E402
from attack.runner import (  # noqa: E402
    HARNESS_PREFIX,
    AttackRunnerError,
    RunContext,
    build_defenses,
    export_runs_csv,
    load_carriers,
    load_corpus,
)
from eval.canary import sweep_stale_run_dirs  # noqa: E402
from eval.experiment import load_experiment, unresolved, validate  # noqa: E402
from eval.utility_baseline import build_harness_tools  # noqa: E402
from obs.canary_listener import fetch_hits  # noqa: E402
from obs.cost import budget_from_env, load_prices, spend_from_log  # noqa: E402
from obs.parallel import stop_file  # noqa: E402
from obs.trace import (  # noqa: E402
    Run,
    Step,
    compute_env_hash,
    lab_git_commit,
    open_store,
    uncommitted_changes,
)
from obs.worker import BatchLockedError, batch_lock  # noqa: E402

MODELS = ROOT / "config" / "models.yaml"
TOOLS = ROOT / "config" / "tools.yaml"
LOG = ROOT / "logs" / "llm_client.jsonl"
BATCH_ROOT = ROOT / "results" / "attack_matrix"
TABLES = ROOT / "results" / "tables"
LOCK = ROOT / "logs" / "batch.lock"
CHAIN_FIELDS = [
    "chain_id", "target_id", "channel", "technique", "goal", "preset", "payload_id",
    "carrier_task_id", "repeat_idx", "success", "success_round", "stop_reason", "n_rounds",
    "outcomes", "rewrites", "run_ids",
]


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _log_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _listener_base(http_tool) -> str:
    """Gốc URL của canary listener (đọc hit theo run) — cùng sink mà `http_request` chuyển tới."""
    parts = urlsplit(http_tool.config.external_sink_url)
    return f"{parts.scheme}://{parts.netloc}"


def _done_chains(path: Path) -> dict[str, dict]:
    if not path.is_file():
        return {}
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return {r["chain_id"]: r for r in rows}


def _drop_partial_chains(engine, batch_id: str, done: set[str]) -> int:
    """Xóa vòng đã ghi của chuỗi dở dang (lô bị ngắt giữa chuỗi): chuỗi chạy lại từ vòng một."""
    with Session(engine) as s:
        runs = s.exec(
            select(Run.run_id, Run.adaptive_chain_id).where(
                Run.batch_id == batch_id, Run.adaptive_chain_id.is_not(None)  # type: ignore[union-attr]
            )
        ).all()
        stale = [rid for rid, cid in runs if cid not in done]
        if stale:
            s.exec(delete(Step).where(Step.run_id.in_(stale)))  # type: ignore[attr-defined]
            s.exec(delete(Run).where(Run.run_id.in_(stale)))  # type: ignore[attr-defined]
            s.commit()
    return len(stale)


def _row(plan: ChainPlan, res) -> dict:
    return {
        "chain_id": res.chain_id,
        **{k: getattr(plan, k) for k in ("target_id", "channel", "technique", "goal", "preset",
                                         "payload_id", "carrier_task_id", "repeat_idx")},
        "success": res.success,
        "success_round": res.success_round,
        "stop_reason": res.stop_reason,
        "n_rounds": len(res.rounds),
        "outcomes": "|".join(f"{r.outcome or 'parse_error'}:{r.blocked_by or ''}"
                             for r in res.rounds),
        # 1 = vòng kẻ tấn công viết lại được payload; 0 = giữ payload gốc (vòng 1, hoặc attacker
        # trả rỗng/trùng). Lọc vòng 0 > 1 khi tính ARR (STT-57).
        "rewrites": "|".join("1" if r.rewrite_applied else "0" for r in res.rounds),
        "run_ids": "|".join(r.run_id for r in res.rounds),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--block", required=True, help="khối tấn công thích ứng (B5)")
    parser.add_argument("--batch-id", help="tiếp tục một lô đã có")
    parser.add_argument("--estimate-usd", type=float, help="dự toán chi phí phiên (USD)")
    parser.add_argument("--plan-only", action="store_true", help="in số chuỗi, không gọi API")
    dry = parser.add_argument_group("chạy thử (chỉ cùng --dry-run)")
    dry.add_argument("--dry-run", action="store_true", help="lô thử, tiền tố dryrun-")
    dry.add_argument("--presets", nargs="+", help="tập con preset của khối")
    dry.add_argument("--chains-per-cell", type=int, help="số chuỗi mỗi ô × preset")
    dry.add_argument("--max-chains", type=int, help="chỉ chạy n chuỗi đầu của kế hoạch")
    dry.add_argument("--allow-dirty", action="store_true", help="cho chạy trên cây chưa commit")
    args = parser.parse_args()

    narrowed = any([args.presets, args.chains_per_cell, args.max_chains, args.allow_dirty])
    if narrowed and not args.dry_run:
        parser.error("các cờ thu hẹp chỉ dùng với --dry-run")
    if args.batch_id and args.dry_run != args.batch_id.startswith("dryrun-"):
        parser.error("--dry-run phải đi với batch_id tiền tố dryrun- và ngược lại")

    load_dotenv(ROOT / ".env")
    exp = load_experiment()
    problems = validate(exp) + unresolved(exp, args.block)
    if problems:
        print(f"experiment.yaml chưa sẵn sàng cho {args.block}:\n  " + "\n  ".join(problems))
        return 2
    block = exp.unit(args.block)
    if args.presets and set(args.presets) - set(block.presets):
        parser.error(f"--presets phải thuộc {list(block.presets)}")
    corpus, carriers = load_corpus(), load_carriers()
    try:
        plans = plan_adaptive(exp, args.block, corpus=corpus, carriers=carriers,
                              seed=exp.raw["run_order"]["seed"], presets=args.presets,
                              chains_per_cell=args.chains_per_cell)
    except AttackRunnerError as e:
        print(str(e))
        return 2
    if args.max_chains:
        plans = plans[: args.max_chains]

    prefix = f"dryrun-attack-{args.block}" if args.dry_run else f"attack-{args.block}"
    batch_id = args.batch_id or f"{prefix}-{_stamp()}"
    batch_dir = BATCH_ROOT / batch_id
    chains_path = batch_dir / "chains.jsonl"
    done = _done_chains(chains_path)
    todo = [p for p in plans if p.chain_id not in done]
    print(f"{batch_id}: {len(plans)} chuỗi theo kế hoạch, {len(done)} đã xong, còn {len(todo)}"
          f" (≤ {len(todo) * (block.max_rounds or 3)} run)")
    if args.plan_only:
        return 0
    if args.estimate_usd is None:
        parser.error("cần --estimate-usd (dự toán lô) để mở lô")

    signal.signal(signal.SIGTERM, signal.default_int_handler)
    try:
        with batch_lock(LOCK):
            return _run(args, exp, block, corpus, carriers, plans, todo, done, batch_id, batch_dir,
                        chains_path)
    except BatchLockedError as e:
        print(f"Không mở lô: {e}")
        return 2


def _run(args, exp, block, corpus, carriers, plans, todo, done, batch_id, batch_dir,
         chains_path) -> int:
    commit = lab_git_commit()
    if commit.endswith("-dirty") and not args.allow_dirty:
        print(f"Cây làm việc chưa commit ({commit}) — commit rồi chạy lại:")
        print("\n".join(f"  {line}" for line in uncommitted_changes()))
        return 2
    batch_dir.mkdir(parents=True, exist_ok=True)
    engine = open_store(batch_dir / "trace.sqlite")
    dropped = _drop_partial_chains(engine, batch_id, set(done))
    if dropped:
        print(f"Đã xóa {dropped} vòng của chuỗi dở dang phiên trước — chạy lại từ vòng một.")
    swept = sweep_stale_run_dirs()
    if swept:
        print(f"Đã dọn {len(swept)} thư mục run cũ còn sót.")

    targets = list(block.targets)
    attacker_id = block.attacker_model or ATTACKER_ID
    prices = load_prices(MODELS, [*targets, attacker_id])
    guard = budget_from_env(args.estimate_usd)
    since = _log_ts()
    presets = list(dict.fromkeys(p.preset for p in plans))
    defenses = build_defenses(presets)
    snapshot = dict(zip(presets, defenses, strict=True))
    tools = build_harness_tools()
    ctx = RunContext(
        engine=engine,
        batch_id=batch_id,
        env_hash=compute_env_hash(template_hash(), TOOLS, commit),
        harness_version=f"{HARNESS_PREFIX}{commit}",
        models={t: LLMClient(t, config_path=MODELS, log_path=LOG, run_id=batch_id)
                for t in targets},
        tools=tools,
        corpus_by_id={p["id"]: p for p in corpus},
        carriers_by_id={c["id"]: c for c in carriers},
        core_params=load_core_params(),
        kb_top_k=exp.fixed["kb_top_k"],
        defenses=defenses,
    )
    attacker = LLMAdaptiveAttacker(
        client=LLMClient(attacker_id, config_path=MODELS, log_path=LOG, run_id=batch_id)
    )
    listener = _listener_base(tools.http)

    def hits(run_id: str) -> list[dict]:
        return [asdict(h) for h in fetch_hits(listener, run_id)]

    prompt_cfg = load_prompt_config()
    manifest = {
        "task": "STT-57",
        "block": args.block,
        "batch_id": batch_id,
        "dry_run": args.dry_run,
        "lab_git_commit": commit,
        "env_hash": ctx.env_hash,
        "prompt_variant": prompt_cfg.active,
        "prompt_knobs": prompt_cfg.knobs(),
        "models": {t: m.model for t, m in ctx.models.items()},
        "attacker_model": attacker.client.model,
        "cells": block.cells,
        "presets": presets,
        "max_rounds": block.max_rounds,
        "n_planned_chains": len(plans),
        "estimate_usd": args.estimate_usd,
        "started_at_utc": _stamp(),
        "spent_scope": "session",
        "since_ts": since,
    }

    def spent() -> float:
        return sum(spend_from_log(LOG, prices, run_ids=[batch_id], since_ts=since).values())

    status = "ok"
    stop = stop_file(batch_dir)
    t0 = time.monotonic()
    try:
        for i, plan in enumerate(todo, start=1):
            if stop.exists():
                print("DỪNG: có file STOP của lô.", flush=True)
                status = "interrupted"
                break
            spec = AdaptiveChainSpec(
                target_id=plan.target_id,
                channel=plan.channel,
                goal=plan.goal,
                defense_config=snapshot[plan.preset],
                carrier_task_id=plan.carrier_task_id,
                base_payload=ctx.corpus_by_id[plan.payload_id],
                chain_id=plan.chain_id,
            )
            res = run_chain(spec, ctx, attacker, max_rounds=block.max_rounds or 3,
                            hit_fetcher=hits)
            row = _row(plan, res)
            with chains_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            cost = spent()
            status = guard.status(cost)
            verdict = f"THÀNH CÔNG vòng {res.success_round}" if res.success else res.stop_reason
            print(f"[{i}/{len(todo)}] {plan.target_id} {plan.preset} "
                  f"{plan.channel}·{plan.technique}·{plan.goal} {plan.payload_id} → {verdict}"
                  f" · {cost:.2f} USD · {status} · {(time.monotonic() - t0) / 60:.1f} phút",
                  flush=True)
            if status == "stop":
                print("DỪNG: chi phí phiên vượt 120% dự toán hoặc chạm hạn mức tổng.")
                break
    except KeyboardInterrupt:
        status = "interrupted"
        print("Bị ngắt — chuỗi dở dang chạy lại từ vòng một ở phiên sau.", flush=True)
    finally:
        manifest["finished_at_utc"] = _stamp()
        manifest["spent_usd"] = spent()
        manifest["budget_status"] = status
        path = batch_dir / "manifest.json"
        sessions = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
        path.write_text(json.dumps([*sessions, manifest], ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")

    check_adaptive_invariants(engine, batch_id)
    tables = batch_dir if args.dry_run else TABLES
    runs_csv = export_runs_csv(engine, batch_id, tables / f"{batch_id}_runs.csv")
    chains_csv = tables / f"{batch_id}_chains.csv"
    with chains_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CHAIN_FIELDS)
        w.writeheader()
        w.writerows(_done_chains(chains_path).values())
    print(f"  runs: {runs_csv.relative_to(ROOT)}\n  chains: {chains_csv.relative_to(ROOT)}")
    print(f"Kết thúc: {manifest['spent_usd']:.2f} USD · {status}")
    return {"ok": 0, "stop": 3}.get(status, 2)


if __name__ == "__main__":
    raise SystemExit(main())
