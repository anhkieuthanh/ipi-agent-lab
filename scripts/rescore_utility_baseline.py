"""Chấm lại một lô USR nền bằng scorer hiện hành, từ trace đã lưu — không gọi API (VT-12, STT-37).

Bảng gốc của lô (`utility_baseline*.csv`) giữ nguyên làm bằng chứng của scorer lúc chạy. Script ghi
bộ bảng `utility_baseline_rescored*.csv` cạnh đó và bảng đối chiếu hai số
`utility_baseline_scorer_compare.csv` (USR mức run và mức câu theo target, Wilson 95%, số run đổi
`outcome`). Cây làm việc chưa commit thì từ chối: commit của scorer phải ghi được vào bảng đối chiếu.

    uv run python scripts/rescore_utility_baseline.py --batch-id usr-baseline-20261021T080837Z
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from eval.canary import DEFAULT_CUSTOMERS_DB  # noqa: E402
from eval.experiment import load_experiment  # noqa: E402
from eval.metrics import TcpCi, query_level, rate  # noqa: E402
from eval.utility_baseline import export_tables, rescore_table, run_table  # noqa: E402
from obs.trace import lab_git_commit, open_store, uncommitted_changes  # noqa: E402

BATCH_ROOT = ROOT / "results" / "usr_baseline"
TABLES = ROOT / "results" / "tables"


def _usr_rows(runs: pd.DataFrame, label: str) -> list[dict]:
    clean = runs[~runs["parse_error"].astype(bool)]
    rows = []
    for target, cell in clean.groupby("target_id", sort=True):
        by_run = rate(int((cell["outcome"] == "pass").sum()), len(cell))
        q = query_level(cell.assign(run_kind="benign"))
        by_query = rate(int(q["query_pass"].sum()), len(q))
        for level, r in (("run", by_run), ("query", by_query)):
            rows.append(
                {
                    "target_id": target,
                    "level": level,
                    f"{label}_p": r.x,
                    f"{label}_n": r.n,
                    f"{label}_usr": r.p,
                    f"{label}_usr_lo": r.lo,
                    f"{label}_usr_hi": r.hi,
                }
            )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--batch-id", required=True)
    args = parser.parse_args()

    commit = lab_git_commit()
    if commit.endswith("-dirty"):
        print(f"Cây làm việc chưa commit ({commit}) — commit scorer rồi chạy lại:")
        print("\n".join(f"  {line}" for line in uncommitted_changes()))
        return 2

    batch_dir = BATCH_ROOT / args.batch_id
    store = batch_dir / "trace.sqlite"
    if not store.is_file():
        parser.error(f"không có store {store.relative_to(ROOT)}")
    engine = open_store(store)
    judge_log = batch_dir / "judge.jsonl"
    exp = load_experiment()
    benign = json.loads(exp.contract_path("benign_queries").read_text(encoding="utf-8"))["queries"]
    queries = {q["id"]: q for q in benign}
    out_dir = batch_dir / "tables" if args.batch_id.startswith("dryrun-") else TABLES

    before = run_table(engine, args.batch_id, judge_log)
    after = rescore_table(
        engine, args.batch_id, judge_log, queries=queries, customers_db=DEFAULT_CUSTOMERS_DB
    )
    paths = export_tables(
        engine,
        args.batch_id,
        judge_log,
        out_dir,
        tcp=TcpCi.from_experiment(exp),
        review_ratio=exp.raw["stopping"]["parse_error_review_ratio"],
        runs=after,
        stem="utility_baseline_rescored",
        queries=queries,
    )

    merged = before.merge(after, on="run_id", suffixes=("_goc", "_moi"))
    changed = merged[merged["outcome_goc"].fillna("") != merged["outcome_moi"].fillna("")]
    compare = pd.DataFrame(_usr_rows(before, "goc")).merge(
        pd.DataFrame(_usr_rows(after, "moi")), on=["target_id", "level"]
    )
    compare["n_run_doi_outcome"] = (
        compare["target_id"].map(changed.groupby("target_id_goc").size()).fillna(0).astype(int)
    )
    compare.loc[compare["level"] == "query", "n_run_doi_outcome"] = pd.NA
    compare.insert(0, "batch_id", args.batch_id)
    compare["scorer_lab_commit"] = commit
    paths["compare"] = out_dir / "utility_baseline_scorer_compare.csv"
    compare.to_csv(paths["compare"], index=False)

    print(f"{len(changed)} run đổi outcome:")
    print(changed.groupby(["target_id_goc", "outcome_goc", "outcome_moi"]).size().to_string())
    print("\n".join(f"  {k}: {v.relative_to(ROOT)}" for k, v in paths.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
