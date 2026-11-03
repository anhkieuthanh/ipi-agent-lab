"""Cách ly tài nguyên có ghi giữa các tiến trình chạy song song (`coupling_probe --workers`).

Mỗi run đã có bản sao `customers.db` riêng (`eval.canary.seeded_run`). Hai tài nguyên còn lại dùng
chung giữa các tiến trình và bị XÓA SẠCH hoặc GHI ĐÈ theo run:

- collection Qdrant của K1: tài liệu chèn nằm chung collection với nền và `search()` không lọc theo
  `run_id`, nên run song song truy hồi trúng payload của nhau;
- `tickets.db`: `clear_tickets()` đầu mỗi run xóa phiếu của tiến trình khác.

Tiến trình con nhận `IPI_WORKER_ID`; `RagConfig.load()` và `TicketConfig.from_params()` gắn hậu tố
worker vào tên collection / đường dẫn kho. Không đặt biến thì giữ nguyên tên trong `config/` — chạy
tuần tự không đổi gì.

MailHog KHÔNG cách ly: `clear_mailbox()` xóa thư của mọi tiến trình. Chế độ blind chấm từ tham số
tool-call trong trace nên không bị ảnh hưởng; chế độ adaptive đọc lại hộp thư sau run nên KHÔNG được
chạy song song.
"""

from __future__ import annotations

import os
from pathlib import Path

WORKER_ENV = "IPI_WORKER_ID"


def worker_id() -> str | None:
    """Id worker của tiến trình hiện tại, None khi chạy tuần tự."""
    value = os.environ.get(WORKER_ENV, "").strip()
    return value or None


def worker_collection(base: str, wid: str | None = None) -> str:
    """Tên collection Qdrant của worker: `kb` → `kb_w0`."""
    wid = wid if wid is not None else worker_id()
    return f"{base}_w{wid}" if wid else base


def worker_path(base: Path, wid: str | None = None) -> Path:
    """Đường dẫn kho riêng của worker: `data/tickets.db` → `data/tickets.w0.db`."""
    wid = wid if wid is not None else worker_id()
    return base.with_name(f"{base.stem}.w{wid}{base.suffix}") if wid else base
