"""Đo `delivered` K1 offline bằng cách phát lại truy vấn search_kb thật đã ghi trong trace (STT-60, P2).

Mỗi run K1 của các store đầu vào: tiêm lại tài liệu của payload (theo code HIỆN TẠI của injector,
cùng tác vụ chở), chạy lại đúng các câu `search_kb` agent đã gửi (cùng `k`), rồi tính `delivered`
bằng `injector_k1.observed_delivered` như runner. Không gọi model: đo riêng khâu truy hồi, để so
tài liệu chở trước/sau khi sửa mà không tốn lô chạy thật. Câu truy vấn là của agent khi thấy tài liệu
CŨ — phép đo là xấp xỉ, lô thật vẫn là số chính thức.

Ghi `results/raw/pilot/k1_delivery_replay_<UTC>[_<tag>].csv` (một dòng mỗi run) + in tóm tắt.

    uv run python scripts/k1_delivery_replay.py --tag truoc_p2a \\
        --stores results/raw/pilot/pilot-B1-20261026T034810Z/trace.sqlite
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from attack import injector_k1  # noqa: E402
from attack.runner import load_carriers, load_corpus  # noqa: E402
from eval.experiment import load_experiment  # noqa: E402
from rag.embedder import get_embedder  # noqa: E402
from rag.ingest import RagConfig, connect  # noqa: E402
from rag.retriever import search  # noqa: E402

OUT_DIR = ROOT / "results" / "raw" / "pilot"


def _k1_runs(store: Path) -> list[dict]:
    with sqlite3.connect(f"file:{store.resolve()}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        runs = conn.execute(
            "SELECT run_id, batch_id, target_id, payload_id, carrier_task_id, technique, goal "
            "FROM runs WHERE channel = 'K1' AND run_kind = 'attack' ORDER BY run_id"
        ).fetchall()
        out = []
        for r in runs:
            calls = conn.execute(
                "SELECT tool_args FROM steps WHERE run_id = ? AND kind = 'tool' "
                "AND tool_name = 'search_kb' ORDER BY step_idx",
                (r["run_id"],),
            ).fetchall()
            out.append(dict(r) | {"queries": [json.loads(c["tool_args"]) for c in calls]})
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stores", nargs="+", required=True, type=Path)
    parser.add_argument("--tag", default="")
    args = parser.parse_args()

    default_k = load_experiment().fixed["kb_top_k"]
    corpus = {p["id"]: p for p in load_corpus()}
    carriers = {c["id"]: c for c in load_carriers()}
    cfg = RagConfig.load()
    client, embedder = connect(cfg), get_embedder(cfg.model)

    rows = []
    for store in args.stores:
        for r in _k1_runs(store):
            run_id = f"replay{uuid.uuid4().hex}"
            injected = injector_k1.inject_and_probe(
                corpus[r["payload_id"]],
                carriers[r["carrier_task_id"]],
                run_id,
                k=default_k,
                cfg=cfg,
                client=client,
                embedder=embedder,
            )
            try:
                steps = []
                for q in r["queries"]:
                    hits = search(
                        q["query"],
                        q.get("k") or default_k,
                        cfg=cfg,
                        client=client,
                        embedder=embedder,
                    )
                    content = json.dumps(
                        {"results": [{"doc_id": h.metadata.get("doc_id")} for h in hits]}
                    )
                    steps.append(
                        SimpleNamespace(kind="tool", tool_name="search_kb", tool_result=content)
                    )
                delivered = injector_k1.observed_delivered(steps, injected.doc_ids)
            finally:
                injector_k1.cleanup(run_id, cfg=cfg, client=client)
            rows.append(
                {
                    "source_run_id": r["run_id"],
                    "batch_id": r["batch_id"],
                    "target_id": r["target_id"],
                    "payload_id": r["payload_id"],
                    "carrier_task_id": r["carrier_task_id"],
                    "technique": r["technique"],
                    "goal": r["goal"],
                    "n_queries": len(r["queries"]),
                    "delivered_replay": delivered,
                    "delivered_probe": injected.delivered,
                }
            )

    df = pd.DataFrame(rows)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = OUT_DIR / f"k1_delivery_replay_{stamp}{'_' + args.tag if args.tag else ''}.csv"
    df.to_csv(out, index=False)
    n = len(df)
    print(
        f"run K1: {n} · delivered (phát lại truy vấn thật): {int(df.delivered_replay.sum())}/{n}"
        f" · probe câu hỏi gốc: {int(df.delivered_probe.sum())}/{n}"
    )
    print(df.groupby("carrier_task_id")[["delivered_replay", "delivered_probe"]].sum().to_string())
    print(f"ghi {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
