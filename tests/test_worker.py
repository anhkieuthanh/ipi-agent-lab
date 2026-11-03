"""Cách ly tài nguyên theo worker khi chạy song song (`obs.worker`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from obs.worker import WORKER_ENV, worker_collection, worker_id, worker_path
from rag.ingest import RagConfig, clone_base_collection
from tools.create_ticket import TicketConfig
from tools.registry import ToolRegistry


def test_khong_dat_bien_giu_nguyen_ten(monkeypatch):
    monkeypatch.delenv(WORKER_ENV, raising=False)
    assert worker_id() is None
    assert worker_collection("kb") == "kb"
    assert worker_path(Path("data/tickets.db")) == Path("data/tickets.db")


def test_dat_bien_gan_hau_to(monkeypatch):
    monkeypatch.setenv(WORKER_ENV, "2")
    assert worker_collection("kb") == "kb_w2"
    assert worker_path(Path("data/tickets.db")) == Path("data/tickets.w2.db")


def test_rag_config_va_kho_phieu_theo_worker(monkeypatch):
    monkeypatch.delenv(WORKER_ENV, raising=False)
    base_kb = RagConfig.load().collection
    base_store = TicketConfig.from_params(ToolRegistry().params("create_ticket")).store_path
    monkeypatch.setenv(WORKER_ENV, "0")
    assert RagConfig.load().collection == f"{base_kb}_w0"
    store = TicketConfig.from_params(ToolRegistry().params("create_ticket")).store_path
    assert store == base_store.with_name(f"{base_store.stem}.w0{base_store.suffix}")


def test_clone_tu_choi_ghi_de_collection_nen():
    with pytest.raises(ValueError, match="từ chối"):
        clone_base_collection("kb", "kb", cfg=RagConfig.load(), client=object())
