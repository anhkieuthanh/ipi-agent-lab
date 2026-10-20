"""Tool `create_ticket` (TL5) — kho phiếu CSKH mô phỏng, bồn chứa G1 mức trung bình (STT-30).

Ba phần, cùng mẫu với `send_email`:

- **Handler** — `CreateTicket.__call__(args)` kiểm `customer_id` có trong `customers.db`, ghi phiếu
  vào kho SQLite append-only, trả mã phiếu. Gắn bằng `reg.bind("create_ticket", t)`.
- **`list_tickets()`** — đọc lại mọi phiếu theo thứ tự tạo. Bộ chấm dùng nó để biết phiếu nào THỰC SỰ
  rời ngữ cảnh phiên, độc lập với trace.
- **`clear_tickets()`** — xóa kho phiếu. Runner gọi trước MỖI run; mã phiếu đánh lại từ 1 nên tất
  định giữa các run.

    t = CreateTicket.from_registry(reg)
    reg.bind("create_ticket", t)
    t.clear_tickets()                    # đầu run
    ...
    tickets = t.list_tickets()           # cuối run, cho scorer

Kho phiếu tách khỏi `customers.db`: phiếu là kho người khác đọc được (Y_TUONG_DU_AN.md mục 2.2),
không phải ghi vào dữ liệu khách hàng. Tool chỉ thêm, không sửa, không xóa — `clear_tickets()` là
thao tác của harness, không phơi cho model.

Handler không lọc nội dung phiếu: baseline dễ tổn thương có chủ đích. Dò canary trong `title`/`body`
và kiểm `customer_id`, `priority`, số phiếu là việc của `eval.allowed_actions` và scorer.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from interfaces import ToolResult

if TYPE_CHECKING:
    from tools.registry import ToolRegistry

__all__ = ["CreateTicket", "Ticket", "TicketConfig"]

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL_NAME = "create_ticket"

_PARAM_KEYS = frozenset({"store_path", "customers_db_path", "ticket_id_format"})
_SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id   TEXT NOT NULL UNIQUE,
    customer_id INTEGER NOT NULL,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    priority    TEXT NOT NULL,
    created_at  TEXT NOT NULL
)
"""


@dataclass(frozen=True)
class TicketConfig:
    store_path: Path
    customers_db_path: Path
    ticket_id_format: str

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> TicketConfig:
        missing = _PARAM_KEYS - set(params)
        if missing:
            raise ValueError(f"create_ticket.params thiếu {sorted(missing)}")
        unknown = set(params) - _PARAM_KEYS
        if unknown:
            raise ValueError(f"create_ticket.params có khóa lạ {sorted(unknown)}")
        return cls(
            store_path=_abs(params["store_path"]),
            customers_db_path=_abs(params["customers_db_path"]),
            ticket_id_format=str(params["ticket_id_format"]),
        )


@dataclass(frozen=True)
class Ticket:
    ticket_id: str
    customer_id: int
    title: str
    body: str
    priority: str
    created_at: str


class CreateTicket:
    """Handler `create_ticket` + đọc/xóa kho phiếu."""

    def __init__(self, config: TicketConfig) -> None:
        if not config.customers_db_path.is_file():
            raise FileNotFoundError(
                f"không có {config.customers_db_path} — chạy scripts/seed_db.py"
            )
        self.config = config
        config.store_path.parent.mkdir(parents=True, exist_ok=True)
        with self._store() as conn:
            conn.execute(_SCHEMA)

    @classmethod
    def from_registry(cls, registry: ToolRegistry) -> CreateTicket:
        return cls(TicketConfig.from_params(registry.params(TOOL_NAME)))

    # -- handler --------------------------------------------------------------

    def __call__(self, args: dict[str, Any]) -> ToolResult:
        customer_id = args["customer_id"]
        name = self._customer_name(customer_id)
        if name is None:
            return _error(
                f"Không tìm thấy khách hàng có id={customer_id}.", reason="customer_not_found"
            )
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._store() as conn:
            cur = conn.execute(
                "INSERT INTO tickets (ticket_id, customer_id, title, body, priority, created_at) "
                "VALUES ('', ?, ?, ?, ?, ?)",
                (customer_id, args["title"], args["body"], args["priority"], created_at),
            )
            ticket_id = self.config.ticket_id_format % cur.lastrowid
            conn.execute(
                "UPDATE tickets SET ticket_id = ? WHERE seq = ?", (ticket_id, cur.lastrowid)
            )
        return ToolResult(
            call_id="",
            name=TOOL_NAME,
            content=(
                f"Đã tạo phiếu {ticket_id} cho khách hàng {name} (id={customer_id}), "
                f"mức ưu tiên {args['priority']}."
            ),
            meta={"ticket_id": ticket_id, "customer_id": customer_id},
        )

    def _customer_name(self, customer_id: int) -> str | None:
        uri = f"{self.config.customers_db_path.resolve().as_uri()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        try:
            row = conn.execute("SELECT name FROM customers WHERE id = ?", (customer_id,)).fetchone()
        finally:
            conn.close()
        return row[0] if row else None

    # -- kho phiếu cho harness ------------------------------------------------

    def list_tickets(self) -> list[Ticket]:
        """Mọi phiếu trong kho, cũ trước mới sau."""
        with self._store() as conn:
            rows = conn.execute(
                "SELECT ticket_id, customer_id, title, body, priority, created_at "
                "FROM tickets ORDER BY seq"
            ).fetchall()
        return [Ticket(*r) for r in rows]

    def clear_tickets(self) -> None:
        """Xóa mọi phiếu và đặt lại bộ đếm mã phiếu. Gọi trước mỗi run."""
        with self._store() as conn:
            conn.execute("DELETE FROM tickets")
            conn.execute("DELETE FROM sqlite_sequence WHERE name = 'tickets'")

    def _store(self) -> _Store:
        return _Store(self.config.store_path)


class _Store:
    """Kết nối kho phiếu: commit khi thoát bình thường, rollback khi lỗi, luôn đóng."""

    def __init__(self, path: Path) -> None:
        self.conn = sqlite3.connect(path)

    def __enter__(self) -> sqlite3.Connection:
        return self.conn

    def __exit__(self, exc_type: object, *_: object) -> None:
        try:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            self.conn.close()


def _abs(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else REPO_ROOT / p


def _error(message: str, *, reason: str) -> ToolResult:
    return ToolResult(
        call_id="", name=TOOL_NAME, content=message, is_error=True, meta={"error": reason}
    )
