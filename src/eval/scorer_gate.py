"""Cổng kiểm chứng bộ chấm — tám ca thử dựng tay (STT-36, quy tắc cứng #5).

Đặc tả: `docs/04. Design/07. Chỉ số đo.md` mục 10. Ca thử nằm ở
`tests/fixtures/scorer_gate/cases.yaml`; module này dựng trace từ đó, cho `eval.scorer` chấm và so
với đáp án. Dùng chung cho `tests/test_scorer.py` và `scripts/run_scorer_gate.py` (ghi bằng chứng).

Đạt cổng khi đồng thời: (1) 8/8 ca đạt, mỗi ca đúng MỌI trường trong `expected`; (2) chấm mỗi ca
`repeats` lần liên tiếp trong cùng tiến trình cho cùng kết quả mọi trường.
"""

from __future__ import annotations

import base64
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from eval.scorer import ScoreContext, ScorerConfig, ScoreResult, score_trace
from obs.trace import Run, RunMeta, Step, TraceRecorder, open_store

__all__ = ["CASES_PATH", "CaseResult", "GateReport", "customer_refs", "load_cases", "run_gate"]

REPO_ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = REPO_ROOT / "tests" / "fixtures" / "scorer_gate" / "cases.yaml"
CUSTOMERS_DB = REPO_ROOT / "data" / "customers.db"
N_CASES = 8
REPEATS = 100

_INT_REFS = {"{NAM_PHAT_ID}"}


def load_cases(path: Path = CASES_PATH) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    ids = [c["id"] for c in data["cases"]]
    if ids != list(range(1, N_CASES + 1)):
        raise ValueError(f"{Path(path).name} phải có đúng ca 1..{N_CASES} theo thứ tự, có {ids}")
    return data


def customer_refs(db_path: Path = CUSTOMERS_DB) -> dict[str, Any]:
    """Bản ghi cố định của `customers.db` cho ràng buộc runtime của CT-05, CT-06 (mục 10.2)."""

    def one(sql: str, name: str) -> Any:
        rows = conn.execute(sql, (f"%{name}%",)).fetchall()
        if len(rows) != 1:
            raise ValueError(f"customers.db: cần đúng 1 khách '{name}', có {len(rows)}")
        return rows[0][0]

    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
        return {
            "{VIET_TIEN_EMAIL}": one(
                "SELECT contact_email FROM customers WHERE name LIKE ?", "Việt Tiến"
            ),
            "{NAM_PHAT_ID}": one("SELECT id FROM customers WHERE name LIKE ?", "Nam Phát"),
        }


def _substitute(value: Any, refs: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {k: _substitute(v, refs) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute(v, refs) for v in value]
    if not isinstance(value, str):
        return value
    if value in _INT_REFS:
        return int(refs[value])
    for key, ref in refs.items():
        value = value.replace(key, str(ref))
    return value


def _build(data: dict[str, Any], case: dict[str, Any], refs: dict[str, Any]) -> tuple[Run, list[Step]]:
    common = data["common"]
    run_fields = {**common["run"], **case["run"]}
    delivered = run_fields.pop("delivered", None)
    sys_canary, db_canary = common["run_canaries"]
    refs = {
        **refs,
        "{SYS}": sys_canary,
        "{DB}": db_canary,
        "{DB_B64}": base64.b64encode(db_canary.encode()).decode(),
        "{RUN_ID}": run_fields["run_id"],
    }
    rec = TraceRecorder(open_store(), RunMeta(run_canaries=list(common["run_canaries"]), **run_fields))
    rec.run.delivered = delivered

    steps = _substitute(case["steps"], refs)
    for i, s in enumerate(steps):
        if s["kind"] == "llm":
            calls = None
            if s.get("calls"):
                following = [t for t in steps[i + 1 :] if t["kind"] == "tool"]
                calls = [
                    {"id": f"call_{i}_{j}", "name": name,
                     "arguments": json.dumps(following[j]["tool_args"], ensure_ascii=False)}
                    for j, name in enumerate(s["calls"])
                ]
            rec.step(kind="llm", llm_text=s.get("llm_text"), finish_reason="stop", tool_args=calls)
        else:
            rec.step(kind=s["kind"], tool_name=s["tool_name"], tool_args=s.get("tool_args"),
                     tool_result=s.get("tool_result"), defense_hits=s.get("defense_hits"))
    return rec.run, rec.steps


@dataclass(frozen=True)
class CaseResult:
    id: int
    checks: str
    passed: bool
    deterministic: bool
    expected: dict[str, Any]
    got: dict[str, Any]
    mismatches: dict[str, tuple[Any, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class GateReport:
    cases: tuple[CaseResult, ...]
    repeats: int

    @property
    def n_passed(self) -> int:
        return sum(c.passed for c in self.cases)

    @property
    def passed(self) -> bool:
        return len(self.cases) == N_CASES and all(c.passed and c.deterministic for c in self.cases)


def _score_case(
    data: dict[str, Any], case: dict[str, Any], refs: dict[str, Any], cfg: ScorerConfig
) -> ScoreResult:
    run, steps = _build(data, case, refs)
    ctx = ScoreContext(
        runtime=_substitute(case.get("runtime") or {}, refs),
        activation_check=case.get("activation_check"),
    )
    return score_trace(run, steps, ctx, cfg)


def run_gate(
    cases_path: Path = CASES_PATH,
    db_path: Path = CUSTOMERS_DB,
    cfg: ScorerConfig | None = None,
    repeats: int = REPEATS,
) -> GateReport:
    data = load_cases(cases_path)
    refs = customer_refs(db_path)
    cfg = cfg or ScorerConfig.load()
    results = []
    for case in data["cases"]:
        first = _score_case(data, case, refs, cfg)
        got = first.fields()
        expected = case["expected"]
        mismatches = {
            k: (v, got.get(k, "<không có trường>")) for k, v in expected.items() if got.get(k) != v
        }
        # Dựng lại trace mỗi lần: kiểm cả phần dựng lẫn phần chấm, không chỉ cache của một object.
        deterministic = all(_score_case(data, case, refs, cfg) == first for _ in range(repeats - 1))
        results.append(
            CaseResult(
                id=case["id"],
                checks=case["checks"],
                passed=not mismatches,
                deterministic=deterministic,
                expected=expected,
                got={k: got.get(k) for k in expected},
                mismatches=mismatches,
            )
        )
    return GateReport(cases=tuple(results), repeats=repeats)
