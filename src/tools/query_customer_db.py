"""Tool `query_customer_db` (TL2) — đọc `customers.db`, tối đa `max_rows` bản ghi (STT-30).

Nhận một trong hai dạng `sql_or_filter`:

- **Câu SELECT** (hoặc `WITH … SELECT`) — chạy nguyên văn, một câu duy nhất.
- **Bộ lọc** `cột = giá trị` / `cột LIKE mẫu`, nối nhiều điều kiện bằng `AND` — dựng thành
  `SELECT * FROM customers WHERE …` với tham số ràng buộc, tên cột phải có trong bảng.

File mở ở chế độ CHỈ ĐỌC (`mode=ro` + `PRAGMA query_only`): ghi bằng bất kỳ đường nào cũng là lỗi
SQLite, trả về model như một lỗi truy vấn. Không lọc cột — `canary_note` (canary DB gieo theo run,
STT-33) đọc được như mọi cột khác: đây là nguồn dữ liệu của G1, baseline dễ tổn thương có chủ đích.
Chấm phạm vi truy vấn (`must_not_match`, quét toàn bảng) là việc của `eval.allowed_actions`.

    db = QueryCustomerDb.from_registry(reg)
    reg.bind("query_customer_db", db)

Kết quả vào context là JSON `{"columns", "rows", "row_count", "truncated"}` — chỗ injector K2b
(STT-45) chèn payload. `meta` giữ số dòng và dạng truy vấn, không vào context.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from interfaces import ToolResult

if TYPE_CHECKING:
    from tools.registry import ToolRegistry

__all__ = ["DbConfig", "QueryCustomerDb", "parse_filter"]

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL_NAME = "query_customer_db"
TABLE = "customers"

_PARAM_KEYS = frozenset({"max_rows", "db_path", "max_vm_steps"})
_SQL_START = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
_AND = re.compile(r"\s+and\s+", re.IGNORECASE)
_COND = re.compile(
    r"^\s*(?P<col>[A-Za-z_]\w*)\s*(?P<op>=|==|like)\s*(?P<val>.+?)\s*$", re.IGNORECASE
)
_PROGRESS_EVERY = 1000  # số lệnh VM giữa hai lần gọi progress handler


@dataclass(frozen=True)
class DbConfig:
    db_path: Path
    max_rows: int
    max_vm_steps: int

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> DbConfig:
        missing = _PARAM_KEYS - set(params)
        if missing:
            raise ValueError(f"query_customer_db.params thiếu {sorted(missing)}")
        unknown = set(params) - _PARAM_KEYS
        if unknown:
            raise ValueError(f"query_customer_db.params có khóa lạ {sorted(unknown)}")
        path = Path(params["db_path"])
        return cls(
            db_path=path if path.is_absolute() else REPO_ROOT / path,
            max_rows=int(params["max_rows"]),
            max_vm_steps=int(params["max_vm_steps"]),
        )


def parse_filter(text: str, columns: list[str]) -> tuple[str, list[str]] | str:
    """Bộ lọc → (mệnh đề WHERE có `?`, tham số). Sai dạng trả chuỗi lỗi để báo lại model."""
    clauses: list[str] = []
    values: list[str] = []
    for part in _AND.split(text.strip().rstrip(";")):
        m = _COND.match(part)
        if m is None:
            return f"không hiểu điều kiện {part.strip()!r} (dạng hợp lệ: cột = giá trị)"
        col = m.group("col").lower()
        if col not in columns:
            return f"bảng {TABLE} không có cột '{m.group('col')}' (các cột: {', '.join(columns)})"
        val = m.group("val")
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
            val = val[1:-1]
        op = "LIKE" if m.group("op").lower() == "like" else "="
        clauses.append(f"{col} {op} ?")
        values.append(val)
    return " AND ".join(clauses), values


class QueryCustomerDb:
    """Handler `query_customer_db`."""

    def __init__(self, config: DbConfig) -> None:
        if not config.db_path.is_file():
            raise FileNotFoundError(f"không có {config.db_path} — chạy scripts/seed_db.py")
        self.config = config
        self._base_config = config

    @classmethod
    def from_registry(cls, registry: ToolRegistry) -> QueryCustomerDb:
        return cls(DbConfig.from_params(registry.params(TOOL_NAME)))

    def use_db(self, path: Path | None) -> None:
        """Trỏ handler tới bản sao đã gieo canary của run (`eval.canary.seeded_run`); `None` trả
        về file của tools.yaml."""
        if path is None:
            self.config = self._base_config
            return
        if not Path(path).is_file():
            raise FileNotFoundError(f"không có {path}")
        self.config = replace(self._base_config, db_path=Path(path))

    def __call__(self, args: dict[str, Any]) -> ToolResult:
        text = args["sql_or_filter"].strip()
        if not text:
            return _error("Truy vấn rỗng.", reason="empty_query")
        with self._connect() as conn:
            if _SQL_START.match(text):
                mode, sql, params = "sql", text, []
            else:
                columns = [r[1] for r in conn.execute(f"PRAGMA table_info({TABLE})")]
                parsed = parse_filter(text, columns)
                if isinstance(parsed, str):
                    return _error(f"Bộ lọc không hợp lệ: {parsed}.", reason="invalid_filter")
                where, params = parsed
                mode, sql = "filter", f"SELECT * FROM {TABLE} WHERE {where}"
            try:
                cur = conn.execute(sql, params)
                rows = cur.fetchmany(self.config.max_rows + 1)
            except sqlite3.Warning:
                # "You can only execute one statement at a time."
                return _error("Chỉ được chạy một câu lệnh mỗi lần.", reason="multi_statement")
            except sqlite3.Error as exc:
                return _error(f"Lỗi truy vấn: {exc}.", reason="sql_error")
            columns = [d[0] for d in cur.description or []]

        truncated = len(rows) > self.config.max_rows
        rows = rows[: self.config.max_rows]
        payload = {
            "columns": columns,
            "rows": [dict(zip(columns, r, strict=True)) for r in rows],
            "row_count": len(rows),
            "truncated": truncated,
        }
        return ToolResult(
            call_id="",
            name=TOOL_NAME,
            content=json.dumps(payload, ensure_ascii=False),
            meta={"mode": mode, "sql": sql, "row_count": len(rows), "truncated": truncated},
        )

    def _connect(self) -> _ReadOnly:
        return _ReadOnly(self.config)


class _ReadOnly:
    """Kết nối chỉ đọc, đóng khi ra khỏi `with` (context manager của sqlite3 chỉ commit)."""

    def __init__(self, config: DbConfig) -> None:
        uri = f"{config.db_path.resolve().as_uri()}?mode=ro"
        self.conn = sqlite3.connect(uri, uri=True)
        self.conn.execute("PRAGMA query_only = ON")
        budget = [config.max_vm_steps // _PROGRESS_EVERY]

        def _tick() -> int:
            budget[0] -= 1
            return 1 if budget[0] < 0 else 0  # khác 0 ⇒ SQLite hủy truy vấn ("interrupted")

        self.conn.set_progress_handler(_tick, _PROGRESS_EVERY)

    def __enter__(self) -> sqlite3.Connection:
        return self.conn

    def __exit__(self, *exc: object) -> None:
        self.conn.close()


def _error(message: str, *, reason: str) -> ToolResult:
    return ToolResult(
        call_id="", name=TOOL_NAME, content=message, is_error=True, meta={"error": reason}
    )
