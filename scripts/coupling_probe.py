"""Lô dò payload "gắn ngữ cảnh" (STT-61) — thử giả thuyết payload/phương thức tấn công còn yếu.

Chạy 6 payload ở `results/probe/coupling/payloads_coupling.yaml`, mỗi payload bám đúng tool và nghiệp
vụ của một tác vụ chở (CT-01..CT-06), kẻ tấn công mù (blind), D = OFF, trên A2 và A3, lặp `--repeats`
lần. So ASR với nhánh blind corpus hiện tại (hiệu chỉnh: A2/A3 ≈ 0–2,5%).

Lô dò, KHÔNG vào bảng kết quả nào và KHÔNG vào corpus (giao thức thực nghiệm mục 3; payload không
mang v-attack-1.0). Dùng chính `attack.runner.run_one_attack` như lô thật, nên kết quả so được.

    uv run python scripts/coupling_probe.py --plan-only
    uv run python scripts/coupling_probe.py --estimate-usd 3

Lô tiền tố `probe-coupling-`, lưu ở `results/probe/coupling/<batch_id>/`: `trace.sqlite`,
`runs.csv`, `manifest.json`.

`--workers N` chia spec cho N tiến trình con (spec thứ i vào shard i mod N), mỗi con ghi
`trace-s<i>.sqlite` + `shard-<i>.log`, tiến trình mẹ gộp về `trace.sqlite` khi mọi con xong. Con i chạy
với `IPI_WORKER_ID=<batch_id>-<i>` (`obs.worker`): kho phiếu và collection Qdrant riêng (cả lô chỉ K2:
agent vẫn đọc KB qua `search_kb`), mẹ chép điểm nền của `kb` sang trước khi chạy, xóa sau khi xong. MailHog dùng chung: chỉ an toàn vì lô
dò là blind.

Dừng phối hợp qua file `STOP` trong thư mục lô: con kiểm file và ngân sách TRƯỚC mỗi run, mẹ kiểm ngân
sách mỗi `MONITOR_S` giây và đặt `STOP` khi vượt ngưỡng hoặc có con báo vượt. Mẹ nhận SIGINT/SIGTERM
(hoặc lỗi bất kỳ) thì đặt `STOP`, ngắt các con, chờ con thoát (`GRACE_S` giây rồi kill), sau đó vẫn
dọn tài nguyên, gộp trace dở và ghi manifest. Mỗi lúc chỉ một lô (`obs.worker.batch_lock`).

    uv run python scripts/coupling_probe.py --payloads <file> --estimate-usd 2 --workers 4
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

from agent.core import load_core_params  # noqa: E402
from agent.llm_client import LLMClient  # noqa: E402
from agent.prompts import load_prompt_config, template_hash  # noqa: E402
from attack.payloads.schema import load_payloads  # noqa: E402
from attack.runner import (  # noqa: E402
    HARNESS_PREFIX,
    AttackRunSpec,
    RunContext,
    build_defense,
    build_defenses,
    export_runs_csv,
    load_carriers,
    run_one_attack,
    snapshot_json,
)
from eval.canary import sweep_stale_run_dirs  # noqa: E402
from eval.experiment import load_experiment  # noqa: E402
from eval.utility_baseline import build_harness_tools  # noqa: E402
from obs.cost import budget_from_env, load_prices, spend_from_log  # noqa: E402
from obs.trace import (  # noqa: E402
    compute_env_hash,
    lab_git_commit,
    open_store,
    uncommitted_changes,
)
from obs.worker import (  # noqa: E402
    WORKER_ENV,
    BatchLockedError,
    batch_lock,
    worker_collection,
    worker_id,
    worker_path,
)

MODELS = ROOT / "config" / "models.yaml"
TOOLS = ROOT / "config" / "tools.yaml"
LOG = ROOT / "logs" / "llm_client.jsonl"
PROBE_DIR = ROOT / "results" / "probe" / "coupling"
PAYLOADS = PROBE_DIR / "payloads_coupling.yaml"
TARGETS = ("A2", "A3")
LOCK = ROOT / "logs" / "batch.lock"
MONITOR_S = 5  # chu kỳ mẹ kiểm ngân sách và trạng thái con
GRACE_S = 30  # thời gian chờ con thoát sau SIGINT trước khi kill
EXIT_BUDGET, EXIT_STOPPED = 3, 4  # mã thoát của con: tự dừng vì ngân sách / dừng theo file STOP

# Mỗi payload dò bám đúng một tác vụ chở (tool/nghiệp vụ khớp).
PAYLOAD_CARRIER = {
    "P-T1-G3-VI-910": "CT-01",
    "P-T3-G3-VI-910": "CT-02",
    "P-T3-G1-VI-910": "CT-03",
    "P-T3-G2-VI-910": "CT-04",
    "P-T3-G1-VI-911": "CT-05",
    "P-T3-G2-VI-911": "CT-06",
}


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repeats", type=int, default=3, help="số lần lặp mỗi (payload, target)")
    parser.add_argument("--estimate-usd", type=float)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--payloads", default=str(PAYLOADS), help="file payload dò")
    parser.add_argument("--targets", nargs="+", help="tập con target (mặc định A2 A3)")
    parser.add_argument("--workers", type=int, default=1, help="số tiến trình chạy song song")
    parser.add_argument("--shard", help=argparse.SUPPRESS)  # "i/N", do tiến trình mẹ truyền
    parser.add_argument("--batch-id", help=argparse.SUPPRESS)
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    TG = tuple(args.targets) if args.targets else TARGETS
    exp = load_experiment()
    payloads, report = load_payloads(args.payloads)
    if not report.all_ok:
        print("payload dò sai schema:", report.errors_by_id)
        return 2
    corpus = {p["id"]: p for p in payloads}
    off = snapshot_json(build_defense("off"))

    def _carrier(p):  # carrier ghim ở only_carriers, hoặc bảng cứng cho file cũ
        only = p.get("only_carriers")
        return only[0] if only else PAYLOAD_CARRIER[p["id"]]

    specs = [
        AttackRunSpec(
            repeat_idx=r,
            target_id=t,
            channel=p["channels"][0],
            technique=p["technique"]["code"],
            goal=p["goal"],
            attacker_mode="blind",
            defense_config=off,
            carrier_task_id=_carrier(p),
            payload_id=p["id"],
        )
        for p in payloads
        for t in TG
        for r in range(args.repeats)
    ]
    shard = None
    if args.shard:
        i, n = (int(x) for x in args.shard.split("/"))
        shard, specs = i, specs[i::n]
    else:
        print(f"{len(payloads)} payload × {len(TG)} target × {args.repeats} lặp = {len(specs)} run")
        for p in payloads:
            print(f"  {p['id']} {p['channels'][0]}·{p['goal']} → {_carrier(p)}")
    if args.workers > 1 and shard is None and worker_id() is not None:
        parser.error(f"{WORKER_ENV} đã đặt sẵn — tiến trình mẹ phải chạy với collection/kho gốc")
    if args.plan_only:
        return 0

    commit = lab_git_commit()
    if commit.endswith("-dirty"):
        print(f"Cây làm việc chưa commit ({commit}) — commit rồi chạy lại:")
        print("\n".join(f"  {line}" for line in uncommitted_changes()))
        return 2
    if args.estimate_usd is None:
        parser.error("cần --estimate-usd để mở lô")

    if shard is None:  # mẹ (hoặc lô tuần tự) giữ khóa suốt lô; con chạy dưới khóa của mẹ
        signal.signal(signal.SIGTERM, signal.default_int_handler)  # SIGTERM → KeyboardInterrupt
        try:
            with batch_lock(LOCK):
                return _run_batch(args, specs, shard, payloads, corpus, _carrier, TG, exp, commit)
        except BatchLockedError as e:
            print(f"Không mở lô: {e}")
            return 2
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    return _run_batch(args, specs, shard, payloads, corpus, _carrier, TG, exp, commit)


def _run_batch(args, specs, shard, payloads, corpus, _carrier, TG, exp, commit) -> int:
    batch_id = args.batch_id or f"probe-coupling-{_stamp()}"
    batch_dir = PROBE_DIR / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    if args.workers > 1 and shard is None:
        return _run_parallel(args, batch_id, batch_dir, payloads, _carrier, TG, commit, len(specs))
    trace_path = batch_dir / ("trace.sqlite" if shard is None else f"trace-s{shard}.sqlite")
    engine = open_store(trace_path)
    prices = load_prices(MODELS, list(TG))
    guard = budget_from_env(args.estimate_usd)
    models = {t: LLMClient(t, config_path=MODELS, log_path=LOG, run_id=batch_id) for t in TG}
    swept = [] if shard is not None else sweep_stale_run_dirs()  # con không dọn: xóa run của con khác
    if swept:
        print(f"Đã dọn {len(swept)} thư mục run cũ còn sót.")
    ctx = RunContext(
        engine=engine,
        batch_id=batch_id,
        env_hash=compute_env_hash(template_hash(), TOOLS, commit),
        harness_version=f"{HARNESS_PREFIX}{commit}",
        models=models,
        tools=build_harness_tools(),
        corpus_by_id=corpus,
        carriers_by_id={c["id"]: c for c in load_carriers()},
        core_params=load_core_params(),
        kb_top_k=exp.fixed["kb_top_k"],
        defenses=build_defenses(["off"]),
    )
    prompt_cfg = load_prompt_config()
    manifest = {
        "task": "STT-61 (dò payload gắn ngữ cảnh)",
        "batch_id": batch_id,
        "lab_git_commit": commit,
        "env_hash": ctx.env_hash,
        "prompt_variant": prompt_cfg.active,
        "models": {t: m.model for t, m in models.items()},
        "defense": "off",
        "repeats": args.repeats,
        "payload_carrier": {p["id"]: _carrier(p) for p in payloads},
        "payloads_file": args.payloads,
        "estimate_usd": args.estimate_usd,
        "started_at_utc": _stamp(),
    }

    status = "ok"
    stop_file = batch_dir / "STOP"
    t0 = time.monotonic()
    try:
        for i, spec in enumerate(specs, start=1):
            # Kiểm TRƯỚC khi nhận run: con khác/mẹ đã ra lệnh dừng, hoặc ngân sách đã chạm ngưỡng.
            if stop_file.exists():
                status = "stopped"
                print("DỪNG: có file STOP của lô.", flush=True)
                break
            if guard.status(sum(spend_from_log(LOG, prices, run_ids=[batch_id]).values())) == "stop":
                status = "stop"
                print("DỪNG trước run: chi phí lô vượt 120% dự toán hoặc chạm hạn mức tổng.", flush=True)
                break
            run_id = run_one_attack(spec, ctx)
            con = sqlite3.connect(trace_path)
            row = con.execute(
                "SELECT outcome, blocked_by, delivered, g2_spontaneous FROM runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
            con.close()
            spent = sum(spend_from_log(LOG, prices, run_ids=[batch_id]).values())
            status = guard.status(spent)
            print(
                f"[{i}/{len(specs)}] {spec.target_id} {spec.payload_id} {spec.carrier_task_id} r{spec.repeat_idx}"
                f" → {row[0]}/{row[1] or '-'} deliv={row[2]} spont={row[3]}"
                f" · {spent:.2f} USD · {status} · {(time.monotonic() - t0) / 60:.1f} phút",
                flush=True,
            )
            if status == "stop":
                print("DỪNG: chi phí lô vượt 120% dự toán hoặc chạm hạn mức tổng.")
                break
    finally:
        if shard is None:  # con: mẹ ghi manifest, gộp trace, xuất CSV
            manifest["finished_at_utc"] = _stamp()
            manifest["spent_usd"] = sum(spend_from_log(LOG, prices, run_ids=[batch_id]).values())
            manifest["budget_status"] = status
            (batch_dir / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            export_runs_csv(engine, batch_id, batch_dir / "runs.csv")
    if shard is not None:
        return {"stop": EXIT_BUDGET, "stopped": EXIT_STOPPED}.get(status, 0)
    _summary(batch_dir, TG)
    return 0


def _summary(batch_dir: Path, TG) -> None:
    con = sqlite3.connect(batch_dir / "trace.sqlite")
    for t in TG:
        n, s = con.execute(
            "SELECT COUNT(*), SUM(outcome='success') FROM runs WHERE target_id=? AND parse_error=0",
            (t,),
        ).fetchone()
        print(f"{t}: {s or 0}/{n} run thành công")
    con.close()
    print(f"  runs: {(batch_dir / 'runs.csv').relative_to(ROOT)}")


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


def _run_parallel(args, batch_id, batch_dir, payloads, carrier_of, TG, commit, n_specs) -> int:
    from rag.ingest import RagConfig, clone_base_collection, connect, count_points, purge_injected
    from tools.create_ticket import TicketConfig
    from tools.registry import ToolRegistry

    n = args.workers
    wids = [f"{batch_id}-{i}" for i in range(n)]
    started = _stamp()
    stop_file = batch_dir / "STOP"
    stop_file.unlink(missing_ok=True)
    prices = load_prices(MODELS, list(TG))
    guard = budget_from_env(args.estimate_usd)
    ticket_base = TicketConfig.from_params(ToolRegistry().params("create_ticket")).store_path
    kb_cfg = RagConfig.load()
    client = connect(kb_cfg)

    # Dưới khóa lô: không lô nào khác đang chạy, nên mọi thư mục run / tài nguyên worker còn lại là rác.
    swept = sweep_stale_run_dirs()
    if swept:
        print(f"Đã dọn {len(swept)} thư mục run cũ còn sót.")
    for f in ticket_base.parent.glob(f"{ticket_base.stem}.w*{ticket_base.suffix}"):
        f.unlink()
    for c in client.get_collections().collections:
        if c.name.startswith(f"{kb_cfg.collection}_w"):
            client.delete_collection(c.name)

    kb_copies: dict[str, int] = {}
    procs: list[tuple[subprocess.Popen, object]] = []
    codes: list[int | None] = []
    status, spent = "ok", 0.0
    base = [sys.executable, str(Path(__file__).resolve()), "--payloads", args.payloads,
            "--repeats", str(args.repeats), "--estimate-usd", str(args.estimate_usd),
            "--targets", *TG, "--workers", str(n), "--batch-id", batch_id]
    try:
        for wid in wids:
            name = worker_collection(kb_cfg.collection, wid)
            kb_copies[name] = clone_base_collection(kb_cfg.collection, name, cfg=kb_cfg, client=client)
        print(f"Collection KB riêng: {kb_copies}", flush=True)
        for i, wid in enumerate(wids):
            log = (batch_dir / f"shard-{i}.log").open("w", encoding="utf-8")
            env = {**os.environ, WORKER_ENV: wid}
            # Phiên riêng: Ctrl-C ở terminal chỉ tới mẹ, mẹ chuyển một lần (không ngắt con hai lần).
            procs.append((subprocess.Popen([*base, "--shard", f"{i}/{n}"], stdout=log,
                                           stderr=subprocess.STDOUT, cwd=ROOT, env=env,
                                           start_new_session=True), log))
        print(f"{n} tiến trình con, {n_specs} run; log: {(batch_dir / 'shard-<i>.log').relative_to(ROOT)}",
              flush=True)
        while any(p.poll() is None for p, _ in procs):
            time.sleep(MONITOR_S)
            spent = sum(spend_from_log(LOG, prices, run_ids=[batch_id]).values())
            over = guard.status(spent) == "stop"
            if (over or any(p.poll() == EXIT_BUDGET for p, _ in procs)) and not stop_file.exists():
                status = "stop"
                stop_file.write_text(f"ngân sách: {spent:.2f} USD\n", encoding="utf-8")
                print(f"DỪNG: chi phí lô {spent:.2f} USD vượt ngưỡng — đặt STOP, chờ con xong run.",
                      flush=True)
    except BaseException as e:  # SIGINT/SIGTERM (KeyboardInterrupt) hoặc lỗi khi dựng/khởi động con
        status = "interrupted" if isinstance(e, KeyboardInterrupt) else f"error: {e!r}"
        print(f"NGẮT LÔ ({status}) — dừng các con, lưu kết quả dở.", flush=True)
        stop_file.write_text(f"{status}\n", encoding="utf-8")
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
        codes = [p.returncode for p, _ in procs]
        if status == "ok" and any(c not in (0, EXIT_STOPPED) for c in codes):
            status = "stop" if EXIT_BUDGET in codes else "error"
        # Lỗi dọn từng tài nguyên ghi vào manifest, KHÔNG chặn bước lưu kết quả phía sau. Collection
        # dọn hỏng thì lô sau dọn lại (đầu lô xóa mọi `kb_w*` dưới khóa).
        cleanup_errors: list[str] = []
        leftover: dict[str, int] = {}  # tài liệu chèn còn sót trong collection worker (run chết giữa chừng)
        for name in kb_copies:
            try:
                wcfg = replace(kb_cfg, collection=name)
                leftover[name] = count_points(cfg=wcfg, client=client, source=kb_cfg.inject_marker)
                purge_injected(cfg=wcfg, client=client)
                client.delete_collection(name)
            except Exception as e:  # noqa: BLE001
                cleanup_errors.append(f"collection {name}: {e!r}")
        for wid in wids:
            try:
                worker_path(ticket_base, wid).unlink(missing_ok=True)
            except OSError as e:
                cleanup_errors.append(f"tickets {wid}: {e!r}")
        # Lưu kết quả: gộp vào file tạm rồi đổi tên — hỏng giữa chừng thì KHÔNG có trace.sqlite/runs.csv
        # một phần trông như cả lô; shard giữ nguyên để gộp lại. Mọi lỗi ở đây làm lô thất bại.
        save_errors: list[str] = []
        shards = [batch_dir / f"trace-s{i}.sqlite" for i in range(n)]
        merging = batch_dir / "trace.merging.sqlite"
        merged = False
        try:
            merging.unlink(missing_ok=True)
            _merge_shards(merging, shards)
            os.replace(merging, batch_dir / "trace.sqlite")
            merged = True
            for sh in shards:
                sh.unlink(missing_ok=True)
        except Exception as e:  # noqa: BLE001 — shard còn nguyên trên đĩa, gộp lại được
            save_errors.append(f"gộp trace: {e!r}")
        if merged:
            try:
                csv_tmp = batch_dir / "runs.csv.tmp"
                export_runs_csv(open_store(batch_dir / "trace.sqlite"), batch_id, csv_tmp)
                os.replace(csv_tmp, batch_dir / "runs.csv")
            except Exception as e:  # noqa: BLE001
                save_errors.append(f"xuất runs.csv: {e!r}")
        try:
            spent = sum(spend_from_log(LOG, prices, run_ids=[batch_id]).values())
        except Exception as e:  # noqa: BLE001
            save_errors.append(f"đọc chi phí: {e!r}")
        manifest = {
            "task": "STT-61 (dò payload gắn ngữ cảnh)",
            "batch_id": batch_id,
            "lab_git_commit": commit,
            "defense": "off",
            "repeats": args.repeats,
            "workers": n,
            "worker_ids": wids,
            "shard_exit_codes": codes,
            "kb_worker_collections": kb_copies,
            "kb_injected_leftover": leftover,
            "cleanup_errors": cleanup_errors,
            "save_status": "error" if save_errors else "ok",
            "save_errors": save_errors,
            "payload_carrier": {p["id"]: carrier_of(p) for p in payloads},
            "payloads_file": args.payloads,
            "estimate_usd": args.estimate_usd,
            "started_at_utc": started,
            "finished_at_utc": _stamp(),
            "spent_usd": spent,
            "budget_status": status,
        }
        (batch_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if merged and not save_errors:
            _summary(batch_dir, TG)
        if cleanup_errors:
            print("Lỗi dọn tài nguyên (ghi trong manifest):", *cleanup_errors, sep="\n  ", flush=True)
        if save_errors:
            print("LỖI LƯU KẾT QUẢ (ghi trong manifest):", *save_errors, sep="\n  ", flush=True)
        print(f"Kết thúc: {spent:.2f} USD · {status} · lưu {manifest['save_status']} · mã thoát con {codes}",
              flush=True)
    return 0 if status == "ok" and not save_errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
