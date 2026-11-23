"""Chạy khối B6 — đối chiếu harness `none` (core-a) và `HN-OW` (opencode) trên cùng mẫu (STT-79).

Đơn tiến trình: HN-OW chạy opencode (tiến trình con) + MailHog dùng chung nên không song song.
Mỗi mẫu (payload, tác vụ chở) bốc từ kế hoạch run của B2 (off/A2) chạy một lần dưới mỗi harness.

    uv run python scripts/run_harness.py --plan-only
    uv run python scripts/run_harness.py --dry-run --samples 2 --estimate-usd 1
    uv run python scripts/run_harness.py --estimate-usd 6

Ngân sách gộp: nhánh `none` từ `logs/llm_client.jsonl`; nhánh `HN-OW` không qua LLMClient nên tính
từ token ghi trong trace × đơn giá A2. Vượt 120% dự toán thì dừng (quy tắc vận hành CLAUDE.md mục 4).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agent.core import load_core_params  # noqa: E402
from agent.llm_client import LLMClient  # noqa: E402
from agent.prompts import build_system_prompt, load_prompt_config, template_hash  # noqa: E402
from attack.harness_ow import HarnessOutageError  # noqa: E402
from attack.runner import (  # noqa: E402
    HARNESS_PREFIX,
    AttackRunnerError,
    RunContext,
    build_defenses,
    done_specs,
    export_runs_csv,
    load_carriers,
    load_corpus,
    plan_b6,
    run_one_attack,
)
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
BATCH_ROOT = ROOT / "results" / "harness_matrix"
TABLES = ROOT / "results" / "tables"
TARGET = "A2"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _hnow_spend(store: Path, batch_id: str, price) -> float:
    """USD của nhánh HN-OW: token trong trace × đơn giá A2 (không qua llm_client.jsonl)."""
    if not store.is_file():
        return 0.0
    with sqlite3.connect(store) as con:
        row = con.execute(
            "SELECT COALESCE(SUM(tokens_in),0), COALESCE(SUM(tokens_out),0) FROM runs "
            "WHERE batch_id = ? AND harness = 'HN-OW'",
            (batch_id,),
        ).fetchone()
    return price.cost(int(row[0]), int(row[1]))


def _trim_samples(specs, n_samples: int):
    """Giữ `n_samples` mẫu đầu (theo cặp payload·carrier), cả hai harness — cho --dry-run."""
    pairs: list[tuple[str, str]] = []
    for s in specs:
        key = (s.payload_id, s.carrier_task_id)
        if key not in pairs:
            pairs.append(key)
    keep = set(pairs[:n_samples])
    return [s for s in specs if (s.payload_id, s.carrier_task_id) in keep]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--batch-id", help="tiếp tục / xuất lại một lô đã có")
    ap.add_argument("--estimate-usd", type=float, help="dự toán chi phí lô (USD)")
    ap.add_argument("--plan-only", action="store_true", help="in số run, không gọi API")
    ap.add_argument("--export-only", action="store_true", help="chỉ xuất CSV từ store")
    ap.add_argument("--dry-run", action="store_true", help="lô thử, tiền tố dryrun-")
    ap.add_argument("--samples", type=int, help="số mẫu (chỉ --dry-run) thay cho samples của khối")
    ap.add_argument("--allow-dirty", action="store_true", help="cho chạy trên cây chưa commit")
    args = ap.parse_args()

    if args.samples is not None and not args.dry_run:
        ap.error("--samples chỉ dùng với --dry-run")
    if args.batch_id and args.dry_run != args.batch_id.startswith("dryrun-"):
        ap.error("--dry-run phải đi với batch_id tiền tố dryrun- và ngược lại")

    load_dotenv(ROOT / ".env")
    exp = load_experiment()
    if problems := validate(exp) + unresolved(exp, "B6"):
        print("experiment.yaml chưa sẵn sàng cho B6:\n  " + "\n  ".join(problems))
        return 2
    variant = load_prompt_config().active

    corpus = load_corpus()
    carriers = load_carriers()
    seed = exp.raw["run_order"]["seed"]
    try:
        specs = plan_b6(exp, corpus=corpus, carriers=carriers, seed=seed)
    except AttackRunnerError as e:
        print(str(e))
        return 2
    if args.samples is not None:
        specs = _trim_samples(specs, args.samples)

    prefix = "dryrun-harness-B6" if args.dry_run else "harness-B6"
    batch_id = args.batch_id or f"{prefix}-{_stamp()}"
    batch_dir = BATCH_ROOT / batch_id
    store = batch_dir / "trace.sqlite"
    tables_dir = batch_dir if args.dry_run else TABLES
    runs_csv = tables_dir / f"{batch_id}_runs.csv"

    if (args.plan_only or args.export_only) and not store.is_file():
        if args.export_only:
            ap.error(f"không có store {store}")
        import collections
        by_h = collections.Counter(s.harness for s in specs)
        print(f"{batch_id}: {len(specs)} run theo kế hoạch ({dict(by_h)}), chưa chạy run nào")
        return 0
    if args.plan_only or args.export_only:
        engine = open_store(store)
        done = done_specs(engine, batch_id)
        print(f"{batch_id}: {len(specs)} run kế hoạch, {len(done)} đã có, còn {len(specs) - len(done)}")
        if args.export_only:
            print(f"  runs: {export_runs_csv(engine, batch_id, runs_csv).relative_to(ROOT)}")
        return 0
    if args.estimate_usd is None:
        ap.error("cần --estimate-usd (dự toán lô) để mở lô")

    commit = lab_git_commit()
    if commit.endswith("-dirty") and not args.allow_dirty:
        print(f"Cây làm việc chưa commit ({commit}) — commit rồi chạy lại:")
        print("\n".join(f"  {line}" for line in uncommitted_changes()))
        return 2

    batch_dir.mkdir(parents=True, exist_ok=True)
    engine = open_store(store)
    prices = load_prices(MODELS, targets=[TARGET])
    guard = budget_from_env(args.estimate_usd)
    since_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ctx = RunContext(
        engine=engine,
        batch_id=batch_id,
        env_hash=compute_env_hash(template_hash(variant), TOOLS, commit),
        system_prompt=partial(build_system_prompt, variant=variant),
        harness_version=f"{HARNESS_PREFIX}{commit}",
        models={TARGET: LLMClient(TARGET, config_path=MODELS, log_path=LOG, run_id=batch_id)},
        tools=build_harness_tools(),
        corpus_by_id={p["id"]: p for p in corpus},
        carriers_by_id={c["id"]: c for c in carriers},
        core_params=load_core_params(),
        kb_top_k=exp.fixed["kb_top_k"],
        defenses=build_defenses(["off"]),
    )

    done = done_specs(engine, batch_id)
    todo = [s for s in specs if s not in done]
    print(f"{batch_id}: {len(specs)} run, {len(done)} đã có, chạy {len(todo)}")
    t0 = datetime.now()
    outage = False
    for i, spec in enumerate(todo, 1):
        try:
            run_one_attack(spec, ctx)
        except HarnessOutageError as e:
            print(f"DỪNG (outage gateway/harness): {e}. Phần đã chạy giữ nguyên; nạp credit rồi "
                  f"xóa run HN-OW hỏng và chạy lại cùng --batch-id {batch_id}.")
            outage = True
            break
        none_spend = spend_from_log(LOG, prices, since_ts=since_ts).get(TARGET, 0.0)
        spent = none_spend + _hnow_spend(store, batch_id, prices[TARGET])
        status = guard.status(spent)
        mins = (datetime.now() - t0).total_seconds() / 60
        print(f"[{i}/{len(todo)}] {spec.harness:5} {spec.channel}·{spec.technique}·{spec.goal}"
              f" · {spent:.2f} USD · {status} · {mins:.1f} phút", flush=True)
        if status == "stop":
            print(f"DỪNG: chi phí {spent:.2f} USD vượt ngưỡng (dự toán {args.estimate_usd}).")
            break

    runs_csv.parent.mkdir(parents=True, exist_ok=True)
    export_runs_csv(engine, batch_id, runs_csv)
    (batch_dir / "manifest.json").write_text(
        json.dumps(
            {"batch_id": batch_id, "harness_version": f"{HARNESS_PREFIX}{commit}",
             "env_hash": ctx.env_hash, "n_specs": len(specs), "seed": seed},
            ensure_ascii=False, indent=2,
        ),
        "utf-8",
    )
    final_spend = spend_from_log(LOG, prices, since_ts=since_ts).get(TARGET, 0.0) + _hnow_spend(
        store, batch_id, prices[TARGET]
    )
    print(f"Kết thúc: {final_spend:.2f} USD")
    print(f"  runs: {runs_csv.relative_to(ROOT)}")
    return 3 if outage else 0


if __name__ == "__main__":
    raise SystemExit(main())
