"""Gộp shard và điều phối tiến trình con của `run_matrix --workers` (`obs.parallel`)."""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

import obs.parallel as par
import rag.ingest as ingest
from obs.trace import open_store


def _store_with_steps(path, run_id, n):
    open_store(path).dispose()
    con = sqlite3.connect(path)
    con.executemany(
        "INSERT INTO steps (run_id, step_idx, created_at, kind, defense_hits) VALUES (?, ?, ?, 'llm', '[]')",
        [(run_id, i, "2026-11-03 00:00:00") for i in range(n)],
    )
    con.commit()
    con.close()


def _steps(path):
    con = sqlite3.connect(path)
    rows = con.execute("SELECT run_id, COUNT(*) FROM steps GROUP BY run_id ORDER BY run_id").fetchall()
    con.close()
    return rows


def test_gop_giu_run_cu_cua_store(tmp_path):
    store = tmp_path / "trace.sqlite"
    _store_with_steps(store, "cu", 2)
    shards = [par.shard_path(tmp_path, i) for i in range(2)]
    _store_with_steps(shards[0], "s0", 1)
    _store_with_steps(shards[1], "s1", 3)
    par.merge_into(store, shards)
    assert _steps(store) == [("cu", 2), ("s0", 1), ("s1", 3)]
    assert not any(s.exists() for s in shards)
    assert not (tmp_path / "trace.merging.sqlite").exists()


def test_gop_hong_giu_store_cu_va_shard(tmp_path, monkeypatch):
    store = tmp_path / "trace.sqlite"
    _store_with_steps(store, "cu", 2)
    shard = par.shard_path(tmp_path, 0)
    _store_with_steps(shard, "s0", 1)

    def _boom(dest, shards):
        raise RuntimeError("đĩa đầy")

    monkeypatch.setattr(par, "_merge_shards", _boom)
    with pytest.raises(RuntimeError):
        par.merge_into(store, [shard])
    assert _steps(store) == [("cu", 2)]
    assert shard.exists()


def test_gop_shard_sot_truoc_khi_chay_tiep(tmp_path):
    store = tmp_path / "trace.sqlite"
    _store_with_steps(store, "cu", 1)
    _store_with_steps(par.shard_path(tmp_path, 1), "sot", 2)
    assert len(par.merge_leftover_shards(store)) == 1
    assert _steps(store) == [("cu", 1), ("sot", 2)]
    assert par.merge_leftover_shards(store) == []


class _Proc:
    """Con giả: ghi shard của mình rồi thoát mã 0."""

    returncode = 0

    def __init__(self, argv, **kw):
        i = int(argv[argv.index("--shard") + 1].split("/")[0])
        _store_with_steps(par.shard_path(kw["cwd"], i), f"s{i}", 1)

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0


class _DownClient:
    def get_collections(self):
        return SimpleNamespace(collections=[])

    def delete_collection(self, name):
        raise ConnectionError("qdrant mất kết nối")


def _down(*a, **kw):
    raise ConnectionError("qdrant mất kết nối")


def test_loi_don_qdrant_khong_chan_gop(tmp_path, monkeypatch):
    import tools.create_ticket as ct

    real = ct.TicketConfig.from_params
    monkeypatch.setattr(ct.TicketConfig, "from_params", classmethod(
        lambda cls, params: real({**params, "store_path": str(tmp_path / "tickets.db")})))
    monkeypatch.setattr(par, "MONITOR_S", 0)
    monkeypatch.setattr(par.subprocess, "Popen", _Proc)
    monkeypatch.setattr(ingest, "connect", lambda cfg: _DownClient())
    monkeypatch.setattr(ingest, "clone_base_collection", lambda *a, **kw: 41)
    monkeypatch.setattr(ingest, "count_points", _down)
    monkeypatch.setattr(ingest, "purge_injected", _down)
    store = tmp_path / "trace.sqlite"
    _store_with_steps(store, "cu", 1)
    res = par.run_sharded(
        batch_id="b", batch_dir=tmp_path, store=store, n=2, child_argv=["x"], cwd=tmp_path,
        log_path=tmp_path / "llm.jsonl", prices={}, guard=SimpleNamespace(status=lambda s: "ok"),
    )
    assert res.status == "ok"
    assert res.exit_codes == [0, 0]
    assert len(res.cleanup_errors) == 2
    assert res.save_errors == []
    assert _steps(store) == [("cu", 1), ("s0", 1), ("s1", 1)]
