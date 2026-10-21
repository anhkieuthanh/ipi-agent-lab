"""Lượt USR nền — STT-37, giao thức thực nghiệm mục 3 bước 2.

60 câu lành tính × target × lần lặp, phòng thủ tắt (`NoDefense`). Tham số lấy từ khóa
`utility_baseline` của `config/experiment.yaml`; script `scripts/run_utility_baseline.py` là lớp CLI
mỏng gọi module này. Số này là mốc TRƯỚC hiệu chỉnh độ khó (N6), không là mốc so của B3.

Một run:

    seeded_run (canary TS1/TS2, bản sao customers.db, gắn handler) → xóa tickets.db
    → TraceRecorder: CoreA.run → judge_run → score(ScoreContext(runtime, judge_pass))
    → ghi lý do của judge vào judge.jsonl (không có cột trong `runs`)

Lỗi hạ tầng đã biết (`RECOVERABLE`: model đích hay judge hết retry, judge trả sai định dạng, MailHog
hay Qdrant không với tới) xảy ra trong `with TraceRecorder` nên run được ghi với `parse_error` và lô
chạy tiếp. Mọi lỗi khác — kể cả lỗi lập trình trong harness, scorer — vẫn được ghi `parse_error` nhưng
DỪNG lô: harness lỗi sẽ hiện ra như "model kém" nếu để lô chạy tiếp (`Y_TUONG_DU_AN.md` mục 17,
bài học 4). Dọn canary thất bại cũng dừng lô.

Thứ tự: lặp ngoài; trong mỗi lần lặp, mọi cặp (target, câu) xáo trộn theo `run_order.seed` — trôi
gateway rải đều lên ba model thay vì dồn vào model chạy sau (giao thức mục 2.2). Chạy lại cùng
`batch_id` thì bỏ qua bộ (target, câu, lần lặp) đã có trong store: lô bị ngắt chạy tiếp được.
"""

from __future__ import annotations

import json
import random
import re
import sqlite3
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from agent.core import CoreA
from agent.llm_client import LLMClientError
from agent.prompts import build_system_prompt
from eval.canary import seeded_run
from eval.judge import JudgeConfig, JudgeError, judge_run
from eval.metrics import TcpCi, group_of, query_level, rate, utility_summary
from eval.scorer import ScoreContext, score
from interfaces import NoDefense, SessionState
from obs.trace import Run, RunMeta, TraceRecorder, export_runs
from tools.create_ticket import CreateTicket
from tools.http_request import HttpRequest
from tools.query_customer_db import QueryCustomerDb
from tools.registry import ToolRegistry
from tools.search_kb import SearchKb
from tools.send_email import MailboxError, SendEmail

__all__ = [
    "RECOVERABLE",
    "UNIT_ID",
    "HarnessTools",
    "RunSpec",
    "benign_runtime",
    "build_harness_tools",
    "done_specs",
    "export_tables",
    "plan_runs",
    "review_candidates",
    "run_one",
]

UNIT_ID = "utility_baseline"
HARNESS_PREFIX = "core-a@"

#: Lỗi hạ tầng mà run ghi `parse_error` rồi lô chạy tiếp. Lỗi khác dừng lô.
RECOVERABLE: tuple[type[BaseException], ...] = (
    LLMClientError,
    JudgeError,
    MailboxError,
    ResponseHandlingException,
    UnexpectedResponse,
)

_DB_WHERE_RE = re.compile(r"^customers where (?P<where>.+?)(?:\s*→.*)?$")


@dataclass(frozen=True, order=True)
class RunSpec:
    repeat_idx: int
    target_id: str
    benign_query_id: str


def plan_runs(
    targets: Iterable[str], query_ids: Iterable[str], *, repeats: int, seed: int
) -> list[RunSpec]:
    """Mọi run của lượt, theo thứ tự chạy. Tất định với cùng tham số."""
    targets, query_ids = list(targets), list(query_ids)
    order: list[RunSpec] = []
    for r in range(repeats):
        batch = [RunSpec(r, t, q) for t in targets for q in query_ids]
        random.Random(f"{seed}:{r}").shuffle(batch)
        order.extend(batch)
    return order


def done_specs(engine: Engine, batch_id: str) -> set[RunSpec]:
    """Bộ (lần lặp, target, câu) đã có trong store — kể cả run `parse_error`, không chạy lại."""
    with Session(engine) as s:
        rows = s.exec(
            select(Run.repeat_idx, Run.target_id, Run.benign_query_id).where(
                Run.batch_id == batch_id
            )
        ).all()
    return {RunSpec(*row) for row in rows}


# ---------------------------------------------------------------------------
# Hạ tầng một run
# ---------------------------------------------------------------------------


@dataclass
class HarnessTools:
    """Registry đủ năm tool, giữ tham chiếu handler mà `seeded_run` và bước dọn cần."""

    registry: ToolRegistry
    db: QueryCustomerDb
    http: HttpRequest
    tickets: CreateTicket


def build_harness_tools(search_fn: Any = None) -> HarnessTools:
    """Như `tools.registry.build_tool_layer`, kèm tham chiếu handler. `search_fn` để test."""
    reg = ToolRegistry()
    db = QueryCustomerDb.from_registry(reg)
    http = HttpRequest.from_registry(reg)
    tickets = CreateTicket.from_registry(reg)
    reg.bind("search_kb", SearchKb.from_experiment(search_fn))
    reg.bind("query_customer_db", db)
    reg.bind("http_request", http)
    reg.bind("send_email", SendEmail.from_registry(reg))
    reg.bind("create_ticket", tickets)
    return HarnessTools(registry=reg, db=db, http=http, tickets=tickets)


def benign_runtime(query: Mapping[str, Any], db_path: Path) -> dict[str, Any]:
    """Ràng buộc tra lúc chạy của câu lành tính, cho G2 của scorer.

    Câu có `db_refs` trỏ đúng một khách hàng: `send_email` phải tới `contact_email` của khách đó,
    `create_ticket` phải đúng `id` và `expected_priority` của câu. Cùng quy tắc với cổng dương tính
    giả `tests/test_benign_gate.py`.
    """
    runtime: dict[str, Any] = {}
    tools = {c["tool"] for c in query["expected_tool_calls"]}
    if not query.get("db_refs") or not tools & {"send_email", "create_ticket"}:
        return runtime
    (ref,) = query["db_refs"]
    where = _DB_WHERE_RE.match(ref)["where"]
    conn = sqlite3.connect(f"{Path(db_path).resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        (row,) = conn.execute(f"SELECT * FROM customers WHERE {where}").fetchall()
    finally:
        conn.close()
    if "send_email" in tools:
        runtime["expected_to"] = row["contact_email"]
    if "create_ticket" in tools:
        runtime["expected_customer_id"] = row["id"]
        runtime["expected_priority"] = query["expected_priority"]
    return runtime


@dataclass
class RunContext:
    """Những gì dùng chung cho mọi run của một lô."""

    engine: Engine
    batch_id: str
    env_hash: str
    harness_version: str
    models: Mapping[str, Any]  # target_id → ChatModel (LLMClient)
    judge_client: Any
    judge_cfg: JudgeConfig
    tools: HarnessTools
    queries: Mapping[str, dict[str, Any]]
    task_types: Mapping[str, str]
    core_params: Mapping[str, int]
    judge_log: Path
    system_prompt: Callable[[str], str] = build_system_prompt


def run_one(spec: RunSpec, ctx: RunContext) -> str:
    """Chạy và chấm một run; trả `run_id`. Lỗi trong `RECOVERABLE` thành `parse_error` của run; lỗi
    khác cũng ghi `parse_error` nhưng lan ra để runner dừng lô."""
    query = ctx.queries[spec.benign_query_id]
    model = ctx.models[spec.target_id]
    defense = NoDefense()
    with seeded_run(db_tool=ctx.tools.db, http_tool=ctx.tools.http) as seeded:
        ctx.tools.tickets.clear_tickets()
        ctx.tools.registry.reset_descriptions()
        meta = RunMeta(
            run_kind="benign",
            target_id=spec.target_id,
            model_id=model.model,
            batch_id=ctx.batch_id,
            harness_version=ctx.harness_version,
            env_hash=ctx.env_hash,
            defense_config=defense.config_snapshot(),
            carrier_task_id=query["carrier_task_id"],
            benign_query_id=spec.benign_query_id,
            run_canaries=seeded.run_canaries,
            repeat_idx=spec.repeat_idx,
            run_id=seeded.run_id,
        )
        session = SessionState(
            run_id=seeded.run_id,
            task_type=ctx.task_types[spec.benign_query_id],
            run_canaries=tuple(seeded.run_canaries),
            carrier_task_id=query["carrier_task_id"],
            benign_query_id=spec.benign_query_id,
        )
        core = CoreA(
            model=model,
            tools=ctx.tools.registry,
            defense=defense,
            system_prompt=ctx.system_prompt(seeded.canaries.sysprompt),
            **ctx.core_params,
        )
        runtime = benign_runtime(query, seeded.db_path)
        try:
            with TraceRecorder(ctx.engine, meta) as rec:
                outcome = core.run(query["user_query_vi"], session=session, recorder=rec)
                verdict = judge_run(
                    ctx.judge_client, query, outcome.final_answer, rec.steps, cfg=ctx.judge_cfg
                )
                score(
                    rec,
                    ScoreContext(
                        runtime=runtime,
                        judge_pass=verdict.judge_pass,
                        judge_model=verdict.judge_model,
                    ),
                )
                _log_judge(ctx, seeded.run_id, verdict)
        except Exception as e:
            _log_judge(ctx, seeded.run_id, None, error=f"{type(e).__name__}: {e}"[:500])
            if not isinstance(e, RECOVERABLE):
                raise
    return seeded.run_id


def _log_judge(ctx: RunContext, run_id: str, verdict: Any, *, error: str | None = None) -> None:
    rec = {
        "run_id": run_id,
        "batch_id": ctx.batch_id,
        "judge_prompt_hash": ctx.judge_cfg.prompt_hash(),
        "judge_called": bool(verdict and verdict.called),
        "judge_reason": verdict.reason if verdict else None,
        "run_error": error,
    }
    ctx.judge_log.parent.mkdir(parents=True, exist_ok=True)
    with ctx.judge_log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Xuất bảng
# ---------------------------------------------------------------------------

#: Cột của CSV mức run — nguồn duy nhất của số USR nền trong báo cáo.
RUN_COLUMNS = [
    "run_id",
    "batch_id",
    "target_id",
    "model_id",
    "response_model",
    "benign_query_id",
    "group",
    "carrier_task_id",
    "repeat_idx",
    "outcome",
    "blocked_by",
    "parse_error",
    "parse_error_reason",
    "judge_pass",
    "hard_fact_pass",
    "keyword_check_pass",
    "judge_model",
    "judge_called",
    "judge_reason",
    "judge_prompt_hash",
    "tcp",
    "g2_hit",
    "g2_severity",
    "g1_hit",
    "loop_flag",
    "n_steps",
    "tokens_in",
    "tokens_out",
    "latency_ms",
    "env_hash",
    "harness_version",
    "created_at",
]


def _judge_log(path: Path) -> pd.DataFrame:
    cols = ["run_id", "judge_called", "judge_reason", "judge_prompt_hash"]
    if not path.is_file():
        return pd.DataFrame(columns=cols)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    # Một run một dòng; chạy tiếp lô không chạy lại run cũ nên không trùng — vẫn giữ dòng cuối.
    return pd.DataFrame(rows).drop_duplicates("run_id", keep="last")[cols]


def run_table(engine: Engine, batch_id: str, judge_log: Path) -> pd.DataFrame:
    df = export_runs(engine, batch_id=batch_id)
    df["group"] = df["benign_query_id"].map(group_of)
    df = df.merge(_judge_log(judge_log), on="run_id", how="left")
    return df.sort_values(["repeat_idx", "target_id", "benign_query_id"])[RUN_COLUMNS]


def summary_table(runs: pd.DataFrame, *, tcp: TcpCi, review_ratio: float) -> pd.DataFrame:
    """Mức run theo (target, nhóm) + dòng ALL; mức câu (đa số lần lặp) theo target."""
    by_run = utility_summary(
        runs.assign(run_kind="benign"),
        by=("target_id", "group"),
        tcp=tcp,
        review_ratio=review_ratio,
    )
    by_run.insert(0, "level", "run")
    rows = []
    q = query_level(runs.assign(run_kind="benign"))
    for target, cell in q.groupby("target_id", sort=True):
        r = rate(int(cell["query_pass"].sum()), len(cell))
        rows.append(
            {
                "level": "query",
                "target_id": target,
                "group": "ALL",
                "n_clean": len(cell),
                "n_units": len(cell),
                "units_lt_n": False,
                "p": r.x,
                "usr": r.p,
                "usr_lo": r.lo,
                "usr_hi": r.hi,
            }
        )
    return pd.concat([by_run, pd.DataFrame(rows)], ignore_index=True)


def review_candidates(runs: pd.DataFrame) -> pd.DataFrame:
    """Run để TA soát tay: judge bất đồng với `hard_fact_pass`, rồi với `keyword_check_pass`.

    Cột `ta_verdict`, `ta_note` để trống cho TA điền (judge đúng / judge sai, ghi chú).
    """
    clean = runs[
        ~runs["parse_error"].astype(bool) & runs["judge_called"].fillna(False).astype(bool)
    ]
    jp = clean["judge_pass"].astype(bool)
    hard = clean["hard_fact_pass"].astype(bool)
    soft = clean["keyword_check_pass"].astype(bool)
    priority = pd.Series(pd.NA, index=clean.index, dtype="object")
    priority[jp != soft] = "2_judge_vs_keyword"
    priority[jp != hard] = "1_judge_vs_hard_fact"
    out = clean.assign(review_priority=priority).dropna(subset=["review_priority"])
    cols = [
        "review_priority",
        "run_id",
        "target_id",
        "benign_query_id",
        "repeat_idx",
        "judge_pass",
        "hard_fact_pass",
        "keyword_check_pass",
        "judge_reason",
    ]
    out = out.sort_values(["review_priority", "benign_query_id", "target_id"])[cols]
    return out.assign(ta_verdict="", ta_note="")


def export_tables(
    engine: Engine,
    batch_id: str,
    judge_log: Path,
    out_dir: Path,
    *,
    tcp: TcpCi,
    review_ratio: float,
) -> dict[str, Path]:
    """Ghi ba CSV vào `out_dir`; trả đường dẫn theo tên."""
    out_dir.mkdir(parents=True, exist_ok=True)
    runs = run_table(engine, batch_id, judge_log)
    paths = {
        "runs": out_dir / "utility_baseline.csv",
        "summary": out_dir / "utility_baseline_summary.csv",
        "review": out_dir / "utility_baseline_review_candidates.csv",
    }
    runs.to_csv(paths["runs"], index=False)
    summary_table(runs, tcp=tcp, review_ratio=review_ratio).to_csv(paths["summary"], index=False)
    review_candidates(runs).to_csv(paths["review"], index=False)
    return paths
