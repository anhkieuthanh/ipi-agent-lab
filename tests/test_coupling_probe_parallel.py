"""Tiến trình mẹ của `coupling_probe --workers`: lỗi dọn Qdrant không được chặn bước lưu kết quả."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import rag.ingest as ingest

ROOT = Path(__file__).resolve().parent.parent


def _load_script():
    spec = importlib.util.spec_from_file_location("coupling_probe", ROOT / "scripts" / "coupling_probe.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Proc:
    """Con giả: đã thoát mã 0 ngay khi tạo."""

    returncode = 0

    def __init__(self, *a, **kw):
        pass

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0

    def send_signal(self, sig):  # pragma: no cover
        pass


class _DownClient:
    """Qdrant còn liệt kê được lúc đầu lô, mất kết nối lúc dọn cuối lô."""

    def get_collections(self):
        return SimpleNamespace(collections=[])

    def delete_collection(self, name):
        raise ConnectionError("qdrant mất kết nối")


def _down(*a, **kw):
    raise ConnectionError("qdrant mất kết nối")


def test_loi_don_qdrant_van_ghi_manifest_va_csv(tmp_path, monkeypatch):
    cp = _load_script()
    monkeypatch.setattr(cp, "sweep_stale_run_dirs", lambda: [])
    monkeypatch.setattr(cp, "load_prices", lambda *a, **kw: {})
    monkeypatch.setattr(cp, "spend_from_log", lambda *a, **kw: {"A2": 0.0})
    monkeypatch.setattr(cp, "budget_from_env", lambda est: SimpleNamespace(status=lambda s: "ok"))
    monkeypatch.setattr(cp, "MONITOR_S", 0)
    monkeypatch.setattr(cp.subprocess, "Popen", _Proc)
    monkeypatch.setattr(ingest, "connect", lambda cfg: _DownClient())
    monkeypatch.setattr(ingest, "clone_base_collection", lambda *a, **kw: 41)
    monkeypatch.setattr(ingest, "count_points", _down)
    monkeypatch.setattr(ingest, "purge_injected", _down)
    monkeypatch.setattr(cp, "ROOT", tmp_path)
    # Kho phiếu trỏ vào tmp: đầu lô mẹ xóa mọi `tickets.w*.db` cạnh kho gốc — không được đụng data/
    # của lô thật đang chạy.
    import tools.create_ticket as ct

    real = ct.TicketConfig.from_params
    monkeypatch.setattr(ct.TicketConfig, "from_params", classmethod(
        lambda cls, params: real({**params, "store_path": str(tmp_path / "tickets.db")})))

    batch_dir = tmp_path / "probe-coupling-test"
    batch_dir.mkdir()
    args = SimpleNamespace(workers=2, payloads="p.yaml", repeats=1, estimate_usd=1.0)
    rc = cp._run_parallel(args, "probe-coupling-test", batch_dir, [], lambda p: None, ("A2",),
                          "abc", 0)

    manifest = json.loads((batch_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["shard_exit_codes"] == [0, 0]
    assert len(manifest["cleanup_errors"]) == 2  # một lỗi mỗi collection worker
    assert all("mất kết nối" in e for e in manifest["cleanup_errors"])
    assert (batch_dir / "runs.csv").exists()
    assert rc == 0


def test_test_khong_dung_kho_phieu_that(tmp_path, monkeypatch):
    """Chốt chặn cho chính bộ test: kho phiếu worker thật trong data/ không bị test xóa."""
    real_dir = ROOT / "data"
    sentinel = real_dir / "tickets.wsentinel-test.db"
    sentinel.write_bytes(b"")
    try:
        test_loi_don_qdrant_van_ghi_manifest_va_csv(tmp_path, monkeypatch)
        assert sentinel.exists()
    finally:
        sentinel.unlink(missing_ok=True)
