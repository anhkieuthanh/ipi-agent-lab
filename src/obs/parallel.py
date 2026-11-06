"""Chạy một lô trên N tiến trình con (`run_matrix.py --workers N`).

Cùng cơ chế với `scripts/coupling_probe.py --workers`, thêm chạy tiếp (resume): mẹ gộp shard vào
`trace.sqlite` ĐANG CÓ chứ không thay nó, nên lô bị ngắt chạy lại cùng `--batch-id` không mất run cũ.

- Con i chạy với `IPI_WORKER_ID=<batch_id>-<i>` (`obs.worker`): kho phiếu và collection Qdrant riêng;
  mẹ chép điểm nền của `kb` sang trước khi chạy, xóa sau khi xong. Con ghi `trace-s<i>.sqlite` +
  `shard-<i>.log`.
- MailHog dùng chung: chỉ an toàn với kẻ tấn công blind (chấm từ tham số tool-call trong trace).
- Dừng phối hợp qua file `STOP` trong thư mục lô: con kiểm file và ngân sách TRƯỚC mỗi run, mẹ kiểm
  ngân sách mỗi `MONITOR_S` giây. Mẹ nhận SIGINT/SIGTERM (hoặc lỗi) thì đặt `STOP`, ngắt các con, chờ
  `GRACE_S` giây rồi kill, sau đó vẫn dọn tài nguyên và gộp trace dở.
- Gộp: chép `trace.sqlite` sang file tạm (SQLite backup API), gộp shard vào bản tạm, đổi tên. Hỏng giữa
  chừng thì `trace.sqlite` cũ nguyên vẹn và shard giữ trên đĩa; lần chạy sau gộp shard sót trước khi
  tính phần còn lại (`merge_leftover_shards`).

Mẹ phải giữ `obs.worker.batch_lock` suốt lô: đầu lô dọn tài nguyên worker còn sót.
"""

from __future__ import annotations

import os
import signal
import sqlite3
import subprocess
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

from obs.cost import spend_from_log
from obs.trace import open_store
from obs.worker import WORKER_ENV, worker_collection, worker_path

MONITOR_S = 5  # chu kỳ mẹ kiểm ngân sách và trạng thái con
GRACE_S = 30  # thời gian chờ con thoát sau SIGINT trước khi kill
EXIT_BUDGET, EXIT_STOPPED = 3, 4  # mã thoát của con: tự dừng vì ngân sách / dừng theo file STOP


def shard_path(batch_dir: Path, i: int) -> Path:
    return batch_dir / f"trace-s{i}.sqlite"


def stop_file(batch_dir: Path) -> Path:
    return batch_dir / "STOP"


def _merge_shards(dest: Path, shards: list[Path]) -> None:
    """Gộp `runs`/`steps` của các trace shard vào `dest` (id bước đánh lại, khóa run_id giữ nguyên)."""
    engine = open_store(dest)
    engine.dispose()
    con = sqlite3.connect(dest)
    try:
        for i, src in enumerate(shards):
            if not src.exists():
                continue
            con.execute(f"ATTACH DATABASE ? AS s{i}", (str(src),))
            for table in ("runs", "steps"):
                cols = [r[1] for r in con.execute(f'PRAGMA s{i}.table_info("{table}")') if r[1] != "id"]
                lst = ", ".join(f'"{c}"' for c in cols)
                con.execute(f'INSERT INTO main."{table}" ({lst}) SELECT {lst} FROM s{i}."{table}"')
            con.commit()
            con.execute(f"DETACH DATABASE s{i}")
    finally:
        con.close()


def merge_into(store: Path, shards: list[Path]) -> None:
    """Gộp shard vào `store` đang có, nguyên tử: bản tạm → gộp → đổi tên → xóa shard."""
    merging = store.with_name(f"{store.stem}.merging{store.suffix}")
    merging.unlink(missing_ok=True)
    if store.exists():
        src, dst = sqlite3.connect(store), sqlite3.connect(merging)
        try:
            src.backup(dst)
        finally:
            src.close()
            dst.close()
    _merge_shards(merging, shards)
    os.replace(merging, store)
    for sh in shards:
        sh.unlink(missing_ok=True)


def merge_leftover_shards(store: Path) -> list[Path]:
    """Shard còn sót của lần chạy trước (gộp hỏng / mẹ bị kill) — gộp vào store trước khi lập phần còn
    lại, để không chạy lại run đã xong. Trả danh sách shard đã gộp."""
    shards = sorted(store.parent.glob("trace-s*.sqlite"))
    if shards:
        merge_into(store, shards)
    return shards


@dataclass
class ShardResult:
    status: str = "ok"
    exit_codes: list[int | None] = field(default_factory=list)
    kb_copies: dict[str, int] = field(default_factory=dict)
    kb_leftover: dict[str, int] = field(default_factory=dict)
    cleanup_errors: list[str] = field(default_factory=list)
    save_errors: list[str] = field(default_factory=list)


def run_sharded(
    *,
    batch_id: str,
    batch_dir: Path,
    store: Path,
    n: int,
    child_argv: list[str],
    cwd: Path,
    log_path: Path,
    prices: dict,
    guard,
    sweep=None,
    since_ts: str | None = None,
) -> ShardResult:
    """Chạy `child_argv + ["--shard", "i/n"]` trên n con, giám sát ngân sách, dọn, gộp vào `store`.

    `since_ts`: chỉ tính chi phí từ mốc này (chạy tiếp một lô — không cộng chi phí phiên trước)."""
    from rag.ingest import RagConfig, clone_base_collection, connect, count_points, purge_injected
    from tools.create_ticket import TicketConfig
    from tools.registry import ToolRegistry

    res = ShardResult()
    wids = [f"{batch_id}-{i}" for i in range(n)]
    stop = stop_file(batch_dir)
    stop.unlink(missing_ok=True)
    ticket_base = TicketConfig.from_params(ToolRegistry().params("create_ticket")).store_path
    kb_cfg = RagConfig.load()
    client = connect(kb_cfg)

    # Dưới khóa lô: không lô nào khác đang chạy, nên mọi thư mục run / tài nguyên worker còn lại là rác.
    swept = sweep() if sweep else []
    if swept:
        print(f"Đã dọn {len(swept)} thư mục run cũ còn sót.")
    for f in ticket_base.parent.glob(f"{ticket_base.stem}.w*{ticket_base.suffix}"):
        f.unlink()
    for c in client.get_collections().collections:
        if c.name.startswith(f"{kb_cfg.collection}_w"):
            client.delete_collection(c.name)

    procs: list[tuple[subprocess.Popen, object]] = []
    try:
        for wid in wids:
            name = worker_collection(kb_cfg.collection, wid)
            res.kb_copies[name] = clone_base_collection(kb_cfg.collection, name, cfg=kb_cfg, client=client)
        print(f"Collection KB riêng: {res.kb_copies}", flush=True)
        for i, wid in enumerate(wids):
            log = (batch_dir / f"shard-{i}.log").open("w", encoding="utf-8")
            env = {**os.environ, WORKER_ENV: wid}
            # Phiên riêng: Ctrl-C ở terminal chỉ tới mẹ, mẹ chuyển một lần (không ngắt con hai lần).
            procs.append((subprocess.Popen([*child_argv, "--shard", f"{i}/{n}"], stdout=log,
                                           stderr=subprocess.STDOUT, cwd=cwd, env=env,
                                           start_new_session=True), log))
        print(f"{n} tiến trình con; log: {batch_dir / 'shard-<i>.log'}", flush=True)
        while any(p.poll() is None for p, _ in procs):
            time.sleep(MONITOR_S)
            spent = sum(spend_from_log(log_path, prices, run_ids=[batch_id], since_ts=since_ts).values())
            over = guard.status(spent) == "stop"
            if (over or any(p.poll() == EXIT_BUDGET for p, _ in procs)) and not stop.exists():
                res.status = "stop"
                stop.write_text(f"ngân sách: {spent:.2f} USD\n", encoding="utf-8")
                print(f"DỪNG: chi phí lô {spent:.2f} USD vượt ngưỡng — đặt STOP, chờ con xong run.",
                      flush=True)
    except BaseException as e:  # SIGINT/SIGTERM (KeyboardInterrupt) hoặc lỗi khi dựng/khởi động con
        res.status = "interrupted" if isinstance(e, KeyboardInterrupt) else f"error: {e!r}"
        print(f"NGẮT LÔ ({res.status}) — dừng các con, lưu kết quả dở.", flush=True)
        stop.write_text(f"{res.status}\n", encoding="utf-8")
        for p, _ in procs:
            if p.poll() is None:
                p.send_signal(signal.SIGINT)
    finally:
        deadline = time.monotonic() + GRACE_S
        for p, _ in procs:
            try:
                p.wait(timeout=max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        for _, log in procs:
            log.close()
        res.exit_codes = [p.returncode for p, _ in procs]
        if res.status == "ok" and any(c not in (0, EXIT_STOPPED) for c in res.exit_codes):
            res.status = "stop" if EXIT_BUDGET in res.exit_codes else "error"
        # Lỗi dọn từng tài nguyên ghi lại, KHÔNG chặn bước gộp phía sau. Lô sau dọn lại dưới khóa.
        for name in res.kb_copies:
            try:
                wcfg = replace(kb_cfg, collection=name)
                res.kb_leftover[name] = count_points(cfg=wcfg, client=client, source=kb_cfg.inject_marker)
                purge_injected(cfg=wcfg, client=client)
                client.delete_collection(name)
            except Exception as e:  # noqa: BLE001
                res.cleanup_errors.append(f"collection {name}: {e!r}")
        for wid in wids:
            try:
                worker_path(ticket_base, wid).unlink(missing_ok=True)
            except OSError as e:
                res.cleanup_errors.append(f"tickets {wid}: {e!r}")
        try:
            merge_into(store, [shard_path(batch_dir, i) for i in range(n)])
        except Exception as e:  # noqa: BLE001 — store cũ nguyên vẹn, shard còn trên đĩa
            res.save_errors.append(f"gộp trace: {e!r}")
    return res
