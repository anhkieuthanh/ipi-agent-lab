"""Chấm lại `judge_pass` của một lô USR nền bằng prompt judge hiện hành, từ trace đã lưu (VT-14, STT-37).

Chỉ gọi judge, không gọi model đích. Chấm mọi run sạch và mọi run `parse_error` vì judge trả sai định
dạng; run lỗi phía model đích giữ nguyên. Kết quả ghi `results/usr_baseline/<batch>/judge_rejudge_<tag>.jsonl`
— store gốc không bị sửa; chạy lại cùng `--tag` thì bỏ qua run đã chấm. `BudgetGuard` kiểm chi phí sau mỗi
lời gọi, vượt 120% `--estimate-usd` thì dừng (CLAUDE.md mục 4).

Xong phần judge, script chấm lại scorer với `judge_pass` mới và ghi:
`utility_baseline_rejudged*.csv` (bộ bảng sau VT-14) và `utility_baseline_judge_compare.csv` (USR trước/sau
theo target, số run judge đổi chiều). Cây làm việc chưa commit thì từ chối.

    uv run python scripts/rejudge_utility_baseline.py --batch-id usr-baseline-20261021T080837Z --estimate-usd 8
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from agent.llm_client import JUDGE_ID, LLMClient  # noqa: E402
from eval.canary import DEFAULT_CUSTOMERS_DB  # noqa: E402
from eval.experiment import load_experiment  # noqa: E402
from eval.judge import JudgeConfig  # noqa: E402
from eval.metrics import TcpCi  # noqa: E402
from eval.utility_baseline import (  # noqa: E402
    export_tables,
    load_rejudge,
    rejudge_runs,
    rescore_table,
    usr_by_target,
)
from obs.cost import budget_from_env, load_prices, spend_from_log  # noqa: E402
from obs.trace import lab_git_commit, open_store, uncommitted_changes  # noqa: E402

MODELS = ROOT / "config" / "models.yaml"
LOG = ROOT / "logs" / "llm_client.jsonl"
BATCH_ROOT = ROOT / "results" / "usr_baseline"
TABLES = ROOT / "results" / "tables"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--estimate-usd", type=float, required=True, help="dự toán phần judge")
    parser.add_argument("--tag", default="vt14", help="nhãn lượt chấm lại, tên file jsonl")
    args = parser.parse_args()

    commit = lab_git_commit()
    if commit.endswith("-dirty"):
        print(f"Cây làm việc chưa commit ({commit}) — commit rồi chạy lại:")
        print("\n".join(f"  {line}" for line in uncommitted_changes()))
        return 2

    batch_dir = BATCH_ROOT / args.batch_id
    store = batch_dir / "trace.sqlite"
    if not store.is_file():
        parser.error(f"không có store {store.relative_to(ROOT)}")
    load_dotenv(ROOT / ".env")
    engine = open_store(store)
    exp = load_experiment()
    benign = json.loads(exp.contract_path("benign_queries").read_text(encoding="utf-8"))["queries"]
    queries = {q["id"]: q for q in benign}
    judge_log = batch_dir / "judge.jsonl"
    rejudge_log = batch_dir / f"judge_rejudge_{args.tag}.jsonl"

    cfg = JudgeConfig.load()
    prices = load_prices(MODELS, [JUDGE_ID])
    guard = budget_from_env(args.estimate_usd)
    run_id = f"{args.batch_id}-rejudge-{args.tag}"
    client = LLMClient(JUDGE_ID, config_path=MODELS, log_path=LOG, run_id=run_id)
    state = {"status": "ok"}

    def after_each(i: int, n: int) -> bool:
        spent = sum(spend_from_log(LOG, prices, run_ids=[run_id]).values())
        state["status"] = guard.status(spent)
        if i % 20 == 0 or i == n or state["status"] != "ok":
            print(f"[{i}/{n}] judge · {spent:.2f} USD · {state['status']}", flush=True)
        return state["status"] != "stop"

    started = _stamp()
    n = rejudge_runs(
        engine,
        args.batch_id,
        client=client,
        cfg=cfg,
        queries=queries,
        log_path=rejudge_log,
        after_each=after_each,
    )
    manifest = {
        "task": "STT-37",
        "vt": "VT-14",
        "batch_id": args.batch_id,
        "tag": args.tag,
        "lab_git_commit": commit,
        "judge_model": client.model,
        "judge_prompt_hash": cfg.prompt_hash(),
        "max_tool_result_chars": cfg.max_tool_result_chars,
        "n_judged_this_session": n,
        "started_at_utc": started,
        "finished_at_utc": _stamp(),
        "spent_usd": sum(spend_from_log(LOG, prices, run_ids=[run_id]).values()),
        "budget_status": state["status"],
    }
    path = batch_dir / f"judge_rejudge_{args.tag}_manifest.json"
    sessions = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
    path.write_text(
        json.dumps([*sessions, manifest], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if state["status"] == "stop":
        print("DỪNG: chi phí vượt 120% dự toán hoặc chạm hạn mức tổng.")
        return 3

    overrides = load_rejudge(rejudge_log)
    kwargs = dict(queries=queries, customers_db=DEFAULT_CUSTOMERS_DB)
    before = rescore_table(engine, args.batch_id, judge_log, **kwargs)
    after = rescore_table(engine, args.batch_id, judge_log, judge_overrides=overrides, **kwargs)
    paths = export_tables(
        engine,
        args.batch_id,
        judge_log,
        TABLES,
        tcp=TcpCi.from_experiment(exp),
        review_ratio=exp.raw["stopping"]["parse_error_review_ratio"],
        runs=after,
        stem="utility_baseline_rejudged",
    )

    merged = before.merge(after, on="run_id", suffixes=("_truoc", "_sau"))
    jt = merged["judge_pass_truoc"].astype("boolean")
    js = merged["judge_pass_sau"].astype("boolean")
    flips = merged.assign(
        judge_fail_to_pass=(jt == False) & (js == True),  # noqa: E712
        judge_pass_to_fail=(jt == True) & (js == False),  # noqa: E712
        recovered=merged["parse_error_truoc"].astype(bool)
        & ~merged["parse_error_sau"].astype(bool),
        outcome_changed=merged["outcome_truoc"].fillna("") != merged["outcome_sau"].fillna(""),
    )
    per_target = flips.groupby("target_id_truoc")[
        ["judge_fail_to_pass", "judge_pass_to_fail", "recovered", "outcome_changed"]
    ].sum()
    compare = pd.DataFrame(usr_by_target(before, "truoc")).merge(
        pd.DataFrame(usr_by_target(after, "sau")), on=["target_id", "level"]
    )
    compare = compare.merge(per_target, left_on="target_id", right_index=True, how="left")
    run_level = compare["level"] == "run"
    for col in per_target.columns:
        compare[col] = compare[col].where(run_level).astype("Int64")
    compare.insert(0, "batch_id", args.batch_id)
    compare["judge_prompt_hash_sau"] = cfg.prompt_hash()
    compare["lab_commit"] = commit
    paths["compare"] = TABLES / "utility_baseline_judge_compare.csv"
    compare.to_csv(paths["compare"], index=False)

    print(per_target.to_string())
    print("\n".join(f"  {k}: {v.relative_to(ROOT)}" for k, v in paths.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
