"""Tìm run của một lô có lời gọi LLM do model ngoài bản pin trả lời (STT-71).

`runs.response_model` chỉ giữ model của lời gọi cuối, nên run có lời gọi giữa chừng bị gateway trả
nhầm model (A2 nhận glm-5.3 của A1, 2026-11-19) không lộ ra ở trace. Script đọc
`logs/llm_client.jsonl` (cột `run_id` của log là `batch_id`), ghép từng lời gọi thành công với bước
`llm` trong `trace.sqlite` theo bộ (tokens_in, tokens_out, latency_ms), rồi liệt kê run có ít nhất
một lời gọi mà `response_model` nằm ngoài `accepted_response_models` của target
(`config/models.yaml`). Chỉ đọc, không sửa store.

    uv run python scripts/find_offpin_runs.py --trace results/attack_matrix/<lô>/trace.sqlite \
        --batch-id <lô> [--out ids.txt]
"""

from __future__ import annotations

import argparse
import collections
import json
import sqlite3
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "logs" / "llm_client.jsonl"
MODELS = ROOT / "config" / "models.yaml"


def accepted_models() -> dict[str, set[str]]:
    targets = yaml.safe_load(MODELS.read_text("utf-8"))["targets"]
    return {t: set(s.get("accepted_response_models") or [s["model_id"]]) for t, s in targets.items()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--trace", required=True, type=Path)
    ap.add_argument("--batch-id", required=True)
    ap.add_argument("--log", type=Path, default=LOG)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    accepted = accepted_models()
    con = sqlite3.connect(args.trace)
    rows = con.execute(
        "SELECT s.run_id, r.target_id, s.tokens_in, s.tokens_out, s.latency_ms "
        "FROM steps s JOIN runs r USING(run_id) WHERE s.kind = 'llm' AND r.batch_id = ?",
        (args.batch_id,),
    ).fetchall()
    index: dict[tuple, set[str]] = collections.defaultdict(set)
    for run_id, target, t_in, t_out, lat in rows:
        index[(target, t_in, t_out, lat)].add(run_id)

    bad: set[str] = set()
    n_calls = n_off = n_unmatched = n_ambiguous = 0
    needle = f'"run_id": "{args.batch_id}"'
    with args.log.open(encoding="utf-8") as f:
        for line in f:
            if needle not in line or '"ok": true' not in line:
                continue
            rec = json.loads(line)
            target = rec.get("target_id")
            if target not in accepted:
                continue  # judge/attacker: không phải target
            n_calls += 1
            key = (target, rec.get("tokens_in"), rec.get("tokens_out"), rec.get("latency_ms"))
            run_ids = index.get(key)
            if not run_ids:
                n_unmatched += 1
                continue
            if len(run_ids) > 1:
                n_ambiguous += 1
            if rec.get("response_model") not in accepted[target]:
                n_off += 1
                bad.update(run_ids)

    # Run có model cuối ngoài bản pin nhưng không ghép được lời gọi nào vẫn phải tính.
    for run_id, target, served in con.execute(
        "SELECT run_id, target_id, response_model FROM runs WHERE batch_id = ?", (args.batch_id,)
    ):
        if target in accepted and served not in accepted[target]:
            bad.add(run_id)

    print(
        f"{args.batch_id}: {len(rows)} bước llm · {n_calls} lời gọi target · {n_off} ngoài bản pin · "
        f"{n_unmatched} không ghép được · {n_ambiguous} ghép nhiều run · {len(bad)} run lẫn"
    )
    if args.out:
        args.out.write_text("\n".join(sorted(bad)) + ("\n" if bad else ""), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
