"""Chạy cổng kiểm chứng bộ chấm 8/8 và ghi bằng chứng — STT-36, quy tắc cứng #5.

Đặc tả: `docs/04. Design/07. Chỉ số đo.md` mục 10.1. Đạt cổng cần cả ba: 8/8 ca đúng mọi trường đáp
án; chấm mỗi ca 100 lần cùng kết quả; chạy trên một commit xác định của `ipi-agent-lab`. Script ghi
`results/scorer_gate/gate_<UTC>.json` (Git theo dõi) gồm commit, băm file ca thử và config chấm, kết
quả từng ca — để số vào báo cáo truy nguồn được.

Cây làm việc có thay đổi chưa commit thì commit ghi được không ứng với mã đã chạy: script từ chối,
trừ khi truyền `--allow-dirty` (bằng chứng khi đó mang `verdict = not_evidence`, chỉ dùng thử).

    uv run python scripts/run_scorer_gate.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from eval.scorer import DEFENSES_PATH, EXPERIMENT_PATH  # noqa: E402
from eval.scorer_gate import CASES_PATH, CUSTOMERS_DB, run_gate  # noqa: E402
from obs.trace import lab_git_commit  # noqa: E402

OUT_DIR = ROOT / "results" / "scorer_gate"
HASHED = [CASES_PATH, EXPERIMENT_PATH, DEFENSES_PATH, CUSTOMERS_DB, ROOT / "data" / "carrier_tasks.json"]


def _uncommitted() -> list[str]:
    """Thay đổi chưa commit, KỂ CẢ file chưa track — `lab_git_commit()` chỉ xét file đã theo dõi,
    nên mã cổng mới viết chưa `git add` vẫn cho commit sạch mà không ứng với mã đã chạy."""
    out = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all", "--", "src", "tests", "config",
         "data", "scripts"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--allow-dirty", action="store_true", help="chạy thử trên cây chưa commit")
    args = parser.parse_args()

    commit = lab_git_commit()
    pending = _uncommitted()
    dirty = commit.endswith("-dirty") or bool(pending)
    if dirty and not args.allow_dirty:
        print(f"Cây làm việc có thay đổi chưa commit ({commit}). Commit trước rồi chạy lại:")
        print("\n".join(f"  {line}" for line in pending))
        return 2

    report = run_gate()
    verdict = "not_evidence" if dirty else ("pass" if report.passed else "fail")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    evidence = {
        "gate": "scorer_8_of_8",
        "spec": "docs/04. Design/07. Chỉ số đo.md mục 10",
        "run_at_utc": stamp,
        "lab_git_commit": commit,
        "uncommitted": pending,
        "python": platform.python_version(),
        "inputs_sha256": {str(p.relative_to(ROOT)): _sha256(p) for p in HASHED},
        "repeats_per_case": report.repeats,
        "n_passed": report.n_passed,
        "n_cases": len(report.cases),
        "all_deterministic": all(c.deterministic for c in report.cases),
        "verdict": verdict,
        "cases": [
            {**asdict(c), "mismatches": {k: list(v) for k, v in c.mismatches.items()}}
            for c in report.cases
        ],
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"gate_{stamp}.json"
    out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for c in report.cases:
        mark = "ĐẠT " if c.passed and c.deterministic else "TRƯỢT"
        print(f"  [{mark}] ca {c.id}: {c.checks}" + (f" — lệch {c.mismatches}" if c.mismatches else ""))
    print(f"{report.n_passed}/{len(report.cases)} ca · tất định: {evidence['all_deterministic']} · "
          f"commit {commit} · verdict {verdict}")
    print(f"Bằng chứng: {out.relative_to(ROOT)}")
    return 0 if verdict == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
