"""Cách ly tài nguyên có ghi giữa các tiến trình chạy song song (`coupling_probe --workers`).

Mỗi run đã có bản sao `customers.db` riêng (`eval.canary.seeded_run`). Hai tài nguyên còn lại dùng
chung giữa các tiến trình và bị XÓA SẠCH hoặc GHI ĐÈ theo run:

- collection Qdrant của K1: tài liệu chèn nằm chung collection với nền và `search()` không lọc theo
  `run_id`, nên run song song truy hồi trúng payload của nhau;
- `tickets.db`: `clear_tickets()` đầu mỗi run xóa phiếu của tiến trình khác.

Tiến trình con nhận `IPI_WORKER_ID` (`<batch_id>-<i>`: tên gắn lô, hai lô không trùng tài nguyên);
`RagConfig.load()` và `TicketConfig.from_params()` gắn hậu tố worker vào tên collection / đường dẫn
kho. Không đặt biến thì giữ nguyên tên trong `config/` — chạy tuần tự không đổi gì. Mỗi lúc chỉ một lô
chạy (`batch_lock`), vì đầu lô dọn tài nguyên còn sót của lô trước.

MailHog KHÔNG cách ly: `clear_mailbox()` xóa thư của mọi tiến trình. Chế độ blind chấm từ tham số
tool-call trong trace nên không bị ảnh hưởng; chế độ adaptive đọc lại hộp thư sau run nên KHÔNG được
chạy song song.
"""

from __future__ import annotations

import fcntl
import os
from contextlib import contextmanager
from pathlib import Path

WORKER_ENV = "IPI_WORKER_ID"


def worker_id() -> str | None:
    """Id worker của tiến trình hiện tại, None khi chạy tuần tự."""
    value = os.environ.get(WORKER_ENV, "").strip()
    return value or None


def worker_collection(base: str, wid: str | None = None) -> str:
    """Tên collection Qdrant của worker: `kb` → `kb_w<wid>`."""
    wid = wid if wid is not None else worker_id()
    return f"{base}_w{wid}" if wid else base


def worker_path(base: Path, wid: str | None = None) -> Path:
    """Đường dẫn kho riêng của worker: `data/tickets.db` → `data/tickets.w<wid>.db`."""
    wid = wid if wid is not None else worker_id()
    return base.with_name(f"{base.stem}.w{wid}{base.suffix}") if wid else base


@contextmanager
def batch_lock(path: Path):
    """Khóa độc quyền một lô tại một thời điểm (`fcntl.flock`, nhả khi tiến trình chết).

    Lô dọn thư mục run tạm của mọi lô (`sweep_stale_run_dirs`) và tài nguyên worker còn sót, nên hai
    lô chạy chồng nhau sẽ phá nhau. Lô thứ hai gặp khóa thì báo lỗi ngay, không chờ.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fh.seek(0)
            raise BatchLockedError(f"đang có lô khác giữ khóa {path}: {fh.read().strip()}") from None
        fh.seek(0)
        fh.truncate()
        fh.write(f"pid={os.getpid()}\n")
        fh.flush()
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


class BatchLockedError(RuntimeError):
    """Lô khác đang chạy (giữ `batch_lock`)."""
