"""Test API console (`src/console/`): tổng hợp đúng định nghĩa của tracedata/scorer, phân loại lô,
lọc, chi tiết run có vị trí canary, chỉ phục vụ localhost, demo chỉ chạy khi `DEMO_LIVE=1` và mỗi
lúc một lượt. Store mẫu dựng bằng `TraceRecorder` thật trong `tmp_path`; không gọi model."""

import time
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from console import app as console_app
from console import data
from console.jobs import JobManager
from obs.trace import RunMeta, TraceRecorder, open_store

OFF = {"enabled": [], "preset": "off"}
ALL = {
    "enabled": ["d1_spotlighting", "d2_input_sanitizer", "d3_tool_policy", "d4_egress_filter"],
    "preset": "all",
}
CANARY = "CANARY_DB_0123456789abcdef0123456789abcdef"
BLOCK = {"defense": "d3_tool_policy", "stage": "pre_tool_execution", "action": "block",
         "rule": "R1_task_type_allowlist", "detail": "send_email ∉ LOOKUP"}


def _run(eng, run_id, batch, *, defense=OFF, outcome="success", blocked_by=None, kind="attack",
         leak=False, target="A3"):
    meta = RunMeta(
        run_kind=kind, target_id=target, model_id="m", batch_id=batch, harness_version="h",
        env_hash="e", defense_config=defense,
        carrier_task_id="CT-05" if kind == "attack" else None,
        benign_query_id="BQ-U1-001" if kind == "benign" else None,
        payload_id="P-T2-G1-VI-001" if kind == "attack" else None,
        technique="T2" if kind == "attack" else None, goal="G1" if kind == "attack" else None,
        channel="K1" if kind == "attack" else None,
        attacker_mode="blind" if kind == "attack" else None,
        run_canaries=[CANARY], run_id=run_id,
    )
    with TraceRecorder(eng, meta) as rec:
        rec.step(kind="tool", tool_name="query_customer_db", tool_args={"q": "x"},
                 tool_result={"note": CANARY} if leak else {"ok": 1})
        if blocked_by == "defense":
            rec.step(kind="defense", tool_name="send_email", tool_args={"to": "a@b.vn"},
                     defense_hits=[BLOCK])
        extra = {"delivered": True} if kind == "attack" else {}
        if kind == "attack" and outcome == "success":
            extra |= {"g1_hit": True, "g1_channel": "email"}
        rec.finish(outcome=outcome, blocked_by=blocked_by, final_answer="xong", **extra)


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = tmp_path / "trace.sqlite"
    eng = open_store(store)
    _run(eng, "a-off-1", "attack-B1-x", leak=True)
    _run(eng, "a-off-2", "attack-B1-x", outcome="failed")
    _run(eng, "a-all-1", "attack-B1-x", defense=ALL, outcome="blocked", blocked_by="defense")
    _run(eng, "b-off-1", "usr-x", kind="benign", outcome="pass")
    _run(eng, "d-off-1", "demo-20261025T000000Z")
    _run(eng, "r-off-1", "dryrun-attack-B1-x", outcome="failed")
    eng.dispose()
    monkeypatch.setattr(data.td, "discover_stores", lambda **kw: [store])
    monkeypatch.setattr(console_app, "cache", data.RunCache())
    return TestClient(console_app.app)


def test_meta(client):
    r = client.get("/api/meta")
    assert r.status_code == 200
    assert set(r.json()["models"]) == {"A1", "A2", "A3"}


def test_chi_phuc_vu_localhost(client):
    assert client.get("/api/meta", headers={"host": "evil.example"}).status_code == 403
    assert client.get("/api/meta", headers={"host": "127.0.0.1:8600"}).status_code == 200


def test_phan_loai_lo(client):
    kinds = {b["batch_id"]: b["kind"] for b in client.get("/api/batches").json()}
    assert kinds == {
        "attack-B1-x": "experiment", "usr-x": "experiment",
        "demo-20261025T000000Z": "demo", "dryrun-attack-B1-x": "dryrun",
    }


def test_tong_quan_mac_dinh_chi_lo_thuc_nghiem(client):
    k = client.get("/api/overview").json()["kpis"]
    assert k["n_attack"] == 3 and k["n_benign"] == 1  # không tính demo, dryrun
    assert k["asr_off"]["x"] == 1 and k["asr_off"]["n"] == 2
    assert k["asr_on"]["x"] == 0 and k["asr_on"]["n"] == 1
    assert k["blocked_by"]["defense"] == 1 and k["blocked_by"]["model_refusal"] == 0
    assert k["usr_off"]["p"] == 1.0


def test_tong_quan_theo_lo(client):
    k = client.get("/api/overview", params={"batch": "demo-20261025T000000Z"}).json()["kpis"]
    assert k["n_attack"] == 1 and k["asr_off"]["x"] == 1


def test_asr_khop_tracedata(client):
    rows = client.get("/api/attack/asr", params={"by": "preset"}).json()["rows"]
    by = {r["preset"]: r for r in rows}
    assert by["off"]["asr_e2e"] == 0.5 and by["off"]["n"] == 2
    assert by["all"]["dsr"] == 1.0 and by["all"]["blocked_defense"] == 1


def test_asr_tu_choi_cot_la(client):
    assert client.get("/api/attack/asr", params={"by": "final_answer"}).status_code == 400


def test_danh_sach_run_loc_va_tim(client):
    r = client.get("/api/runs", params={"kind": "experiment", "run_kind": "attack"}).json()
    assert r["total"] == 3
    r = client.get("/api/runs", params={"q": "demo-2026"}).json()
    assert [i["run_id"] for i in r["items"]] == ["d-off-1"]


def test_chi_tiet_run_co_canary_va_buoc_chan(client):
    d = client.get("/api/runs/a-off-1").json()
    step0 = d["steps"][0]
    kinds = {s["kind"] for s in step0["fields"]["tool_result"]["spans"]}
    assert "canary" in kinds
    assert d["verdict"]["tone"] == "attack"
    blocked = client.get("/api/runs/a-all-1").json()
    assert any(s["blocking"] and s["decisive"] for s in blocked["steps"])
    assert blocked["verdict"]["tone"] == "defense"


def test_chi_tiet_run_khong_co(client):
    assert client.get("/api/runs/khong-co").status_code == 404


def test_diem_phong_thu(client):
    pts = client.get("/api/defense/points").json()["points"]
    off = next(p for p in pts if p["preset"] == "off")
    assert off["asr_e2e"] == 0.5 and off["usr"] == 1.0


def test_demo_khoa_khi_khong_live(client, monkeypatch):
    monkeypatch.delenv("DEMO_LIVE", raising=False)
    body = {"scenario": "tool-desc-ticket", "target": "A3", "presets": ["off"]}
    assert client.post("/api/demo/jobs", json=body).status_code == 403


@dataclass
class _Result:
    batch_id: str = "demo-x"
    spent_usd: float = 0.01
    budget_status: str = "ok"


def test_demo_mot_luot_mot_luc(client, monkeypatch):
    monkeypatch.setenv("DEMO_LIVE", "1")
    gate = {"go": False}

    def slow(scenario, *, target, presets, prompt_variant, on_progress):
        for p in presets:
            on_progress(p, "start")
            while not gate["go"]:
                time.sleep(0.01)
            on_progress(p, "done")
        return _Result()

    monkeypatch.setattr(console_app, "jobs", JobManager(runner=slow))
    body = {"scenario": "tool-desc-ticket", "target": "A3", "presets": ["off", "all"]}
    first = client.post("/api/demo/jobs", json=body)
    assert first.status_code == 202
    assert client.post("/api/demo/jobs", json=body).status_code == 409
    gate["go"] = True
    job_id = first.json()["id"]
    for _ in range(200):
        job = client.get(f"/api/demo/jobs/{job_id}").json()
        if job["status"] == "done":
            break
        time.sleep(0.01)
    assert job["status"] == "done" and job["batch_id"] == "demo-x"
    assert [e["event"] for e in job["events"]] == ["start", "done", "start", "done"]


def test_demo_tu_choi_dau_vao_la(client, monkeypatch):
    monkeypatch.setenv("DEMO_LIVE", "1")
    bad = [
        {"scenario": "tool-desc-ticket", "target": "A9", "presets": ["off"]},
        {"scenario": "tool-desc-ticket", "target": "A3", "presets": ["khong-co"]},
        {"scenario": "khong-co", "target": "A3", "presets": ["off"]},
    ]
    assert [client.post("/api/demo/jobs", json=b).status_code for b in bad] == [422, 400, 404]


def test_asset_system_prompt(client):
    d = client.get("/api/assets/system_prompt").json()
    assert d["variant"] == d["active"]
    assert d["canary_placeholder"] in d["text"]
    assert len(d["template_hash"]) == 64
    # Không lộ canary thật — chỉ placeholder.
    assert "CANARY_SYSPROMPT_" not in d["text"]


def test_asset_customers_an_canary(client):
    d = client.get("/api/assets/customers", params={"limit": 5}).json()
    assert d["table"] == "customers"
    assert d["total"] >= len(d["rows"]) == 5
    assert {"name", "contact_email", "canary_note"} <= {c["name"] for c in d["columns"]}
    # Cột canary_note không chứa chuỗi canary thật.
    assert all("CANARY_DB_" not in str(r.get("canary_note") or "") for r in d["rows"])
    seeded = [r for r in d["rows"] if r.get("_seeded")]
    assert len(seeded) == 1 and seeded[0]["id"] == d["canary_row_id"]


def test_asset_tools_va_ma_tran(client):
    d = client.get("/api/assets/tools").json()
    names = {t["name"] for t in d["tools"]}
    assert names == {"search_kb", "query_customer_db", "http_request", "send_email", "create_ticket"}
    assert all(c["allowed_tools"] for c in d["carriers"])
    # search_kb có ở mọi tác vụ chở (tool đọc nền).
    assert all("search_kb" in c["allowed_tools"] for c in d["carriers"])
