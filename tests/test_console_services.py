"""Test trạng thái dịch vụ hạ tầng của console (`src/console/services.py`, `config/services.yaml`).

Không gọi mạng: `fetch` giả trả mã HTTP hoặc ném lỗi theo URL, ghi lại mọi URL đã gọi."""

import json
import urllib.error

import pytest
from fastapi.testclient import TestClient

from console import app as console_app
from console import services

SECRET = "s3cr3t-token"


class FakeFetch:
    def __init__(self, routes):
        self.routes = routes  # tiền tố URL → int | Exception | (int, bytes); khai sau thắng
        self.calls: list[str] = []

    def __call__(self, url, timeout):
        self.calls.append(url)
        for prefix, result in reversed(list(self.routes.items())):
            if url.startswith(prefix):
                if isinstance(result, BaseException):
                    raise result
                if isinstance(result, tuple):
                    return result
                return result, b""
        raise urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))


@pytest.fixture
def sources(tmp_path):
    rag = tmp_path / "rag.yaml"
    rag.write_text("qdrant:\n  url: http://qdrant.internal:6333\n")
    tools = tmp_path / "tools.yaml"
    tools.write_text(
        "tools:\n"
        "  send_email:\n    params:\n      mailhog_api_url: http://mail.internal:8025\n"
        "  http_request:\n    params:\n      external_sink_url: http://canary.internal:8099\n"
    )
    return {"rag": rag, "tools": tools}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(sources, routes, env=None, clock=None):
    fetch = FakeFetch(routes)
    mon = services.Monitor(fetch=fetch, env=env or {}, sources=sources, clock=clock or Clock())
    return mon, fetch


ALL_UP = {
    "http://qdrant.internal:6333/readyz": 200,
    "http://mail.internal:8025/api/v2/messages?limit=1": 200,
    "http://canary.internal:8099/healthz": 200,
}


def by_id(result):
    return {s["id"]: s for s in result["services"]}


def test_config_contract_loads():
    settings, svcs = services.load_config()
    assert settings.timeout_s <= 1.0
    assert {s.id for s in svcs} >= {"qdrant", "mailhog", "canary", "gateway"}
    # Địa chỉ probe lấy từ đúng nguồn harness dùng, không khai lại trong services.yaml.
    assert all(s.base_from for s in svcs if s.kind == "probe")


def test_all_up_with_latency_and_ports(sources):
    mon, _ = make(sources, ALL_UP)
    st = by_id(mon.status())
    for sid, port in (("qdrant", 6333), ("mailhog", 8025), ("canary", 8099)):
        assert st[sid]["status"] == "up"
        assert st[sid]["latency_ms"] is not None
        assert st[sid]["port"] == port
    assert st["qdrant"]["public_url"] == "http://localhost:6333/dashboard"
    # Listener không có giao diện web.
    assert st["canary"]["public_url"] is None


def test_timeout_marks_down_without_breaking_others(sources):
    routes = {**ALL_UP, "http://qdrant.internal:6333/": TimeoutError("timed out")}
    mon, _ = make(sources, routes)
    st = by_id(mon.status())
    assert st["qdrant"]["status"] == "down"
    assert "hết thời gian chờ" in st["qdrant"]["error"]
    assert st["mailhog"]["status"] == "up"


def test_unexpected_exception_and_http_error_are_isolated(sources):
    routes = {
        **ALL_UP,
        "http://mail.internal:8025/": RuntimeError("boom"),
        "http://canary.internal:8099/": 503,
    }
    mon, _ = make(sources, routes)
    st = by_id(mon.status())
    assert st["mailhog"]["status"] == "down" and st["mailhog"]["error"] == "RuntimeError"
    assert st["canary"]["status"] == "down" and st["canary"]["error"] == "HTTP 503"
    assert st["qdrant"]["status"] == "up"


def test_missing_config_is_not_configured(tmp_path, sources):
    sources["rag"].write_text("qdrant: {}\n")
    mon, fetch = make(sources, ALL_UP)
    st = by_id(mon.status())
    assert st["qdrant"]["status"] == "not_configured"
    assert not any("qdrant" in u for u in fetch.calls)
    assert st["gateway"]["status"] == "not_configured"


def test_env_override_used_for_probe(sources):
    env = {"MAILHOG_API_URL": "http://mailhog:8025/"}
    mon, fetch = make(sources, {**ALL_UP, "http://mailhog:8025/": 200}, env=env)
    assert by_id(mon.status())["mailhog"]["status"] == "up"
    assert "http://mailhog:8025/api/v2/messages?limit=1" in fetch.calls


def test_gateway_never_requested_and_value_not_leaked(sources):
    env = {"GATEWAY_BASE_URL": f"https://user:{SECRET}@gateway.example/v1"}
    mon, fetch = make(sources, ALL_UP, env=env)
    result = mon.status()
    assert by_id(result)["gateway"]["status"] == "configured"
    assert not any("gateway" in u for u in fetch.calls)
    assert SECRET not in json.dumps(result)
    assert "gateway.example" not in json.dumps(result)


def test_no_secret_in_public_url_or_errors(sources):
    env = {
        "MAILHOG_API_URL": f"http://admin:{SECRET}@mail.internal:8025",
        "MAILHOG_PUBLIC_URL": f"http://admin:{SECRET}@localhost:8025/?token={SECRET}",
        "QDRANT_PUBLIC_URL": "javascript:alert(1)",
    }
    routes = {f"http://admin:{SECRET}@mail.internal:8025/": urllib.error.URLError(
        f"bad host http://admin:{SECRET}@mail.internal")}
    mon, _ = make(sources, {**ALL_UP, **routes}, env=env)
    result = mon.status()
    dumped = json.dumps(result)
    assert SECRET not in dumped
    assert "mail.internal" not in dumped and "qdrant.internal" not in dumped
    st = by_id(result)
    assert st["mailhog"]["public_url"] == "http://localhost:8025/"
    assert st["qdrant"]["public_url"] is None


def test_cache_shared_until_ttl_and_refresh_rate_limited(sources):
    clock = Clock()
    mon, fetch = make(sources, ALL_UP, clock=clock)
    mon.status()
    n = len(fetch.calls)
    clock.t += 5
    mon.status()
    assert len(fetch.calls) == n  # trong TTL: không probe lại
    mon.status(force=True)
    assert len(fetch.calls) == 2 * n  # làm mới: probe lại
    clock.t += 0.5
    mon.status(force=True)
    assert len(fetch.calls) == 2 * n  # bấm dồn dưới min_interval_s: dùng kết quả vừa có
    clock.t += mon.settings.cache_ttl_s
    mon.status()
    assert len(fetch.calls) == 3 * n


def test_demo_check_required_vs_optional(sources):
    routes = {**ALL_UP, "http://canary.internal:8099/": 503}
    mon, _ = make(sources, routes)
    k1_g1 = services.demo_check(mon, {"channel": "K1", "goal": "G1"})
    needs = {d["id"]: d["need"] for d in k1_g1["deps"]}
    assert needs == {"qdrant": "required", "mailhog": "required", "canary": "optional"}
    assert k1_g1["ok"]  # canary tùy chọn lỗi vẫn cho chạy
    k2_g2 = services.demo_check(mon, {"channel": "K2a", "goal": "G2"})
    needs = {d["id"]: d["need"] for d in k2_g2["deps"]}
    assert needs == {"qdrant": "optional", "mailhog": "required"}  # G2 không dùng canary


def test_demo_check_blocks_on_required_down_and_reprobes_when_stale(sources):
    clock = Clock()
    routes = dict(ALL_UP)
    mon, fetch = make(sources, routes, clock=clock)
    mon.status()
    routes.pop("http://mail.internal:8025/api/v2/messages?limit=1")
    fetch.routes = routes
    clock.t += mon.settings.stale_before_demo_s + 0.1  # còn trong TTL nhưng đã cũ với demo
    out = services.demo_check(mon, {"channel": "K2b", "goal": "G1"})
    assert not out["ok"] and out["blocking"] == ["mailhog"]


def test_canary_hits_filters_fields_and_validates_run_id(sources):
    hit = {"id": 1, "run_token": "run-1", "received_at": "2026-11-04T01:00:00+00:00",
           "method": "POST", "original_url": "http://evil.test/x", "headers": {"x-secret": SECRET},
           "body": "a" * 3000, "body_encoding": "utf-8", "body_truncated": False}
    routes = {**ALL_UP, "http://canary.internal:8099/hits": (200, json.dumps([hit]).encode())}
    mon, fetch = make(sources, routes)
    out = services.canary_hits(mon, ["run-1"])
    assert out["status"] == "up"
    (item,) = out["items"]
    assert item["run_id"] == "run-1" and item["truncated"]
    assert len(item["body_preview"]) == services.HIT_BODY_PREVIEW
    assert "headers" not in item and SECRET not in json.dumps(out)
    assert fetch.calls[-1] == "http://canary.internal:8099/hits?run=run-1"
    with pytest.raises(ValueError):
        services.canary_hits(mon, ["../hits?x"])


def test_match_run_by_time_window():
    windows = [{"run_id": "r1", "created_at": "2026-11-04 01:00:00",
                "finished_at": "2026-11-04 01:01:00"}]
    at = services._parse_time("2026-11-04T08:00:30.123456789+07:00")
    assert services._match_run(at, windows) == "r1"
    assert services._match_run(services._parse_time("2026-11-04T01:02:00Z"), windows) is None


@pytest.fixture
def client(sources, monkeypatch):
    mon, _ = make(sources, {**ALL_UP, "http://canary.internal:8099/": RuntimeError("x")})
    monkeypatch.setattr(console_app, "monitor", mon)
    return TestClient(console_app.app)


def test_endpoint_partial_failure_still_200(client):
    r = client.get("/api/services")
    assert r.status_code == 200
    st = by_id(r.json())
    assert st["canary"]["status"] == "down" and st["qdrant"]["status"] == "up"


def test_endpoint_demo_check_and_validation(client):
    assert client.get("/api/services/demo-check", params={"scenario": "nope"}).status_code == 404
    r = client.get("/api/services/demo-check", params={"scenario": "exfil-email"})
    assert r.status_code == 200 and r.json()["ok"]
    assert client.get("/api/services/canary-hits", params={"run": "a b"}).status_code == 400
    assert client.get("/api/services/canary-hits").status_code == 422
