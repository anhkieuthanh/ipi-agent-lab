"""Test adapter AgentDojo (STT-38) — kiểm bằng số bản ghi trích được và tính trung thực với nguồn.

Chỉ tiêu đầu việc: ≥100 payload có nguồn gốc + cờ coupling. Snapshot là 5 attack × 35 injection
task của AgentDojo v1.2.2 đã chạy thật (data/upstream/agentdojo/MANIFEST.txt).
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter

import pytest
import yaml

from attack.adapters.agentdojo import import_agentdojo, main, to_lab_payload
from attack.adapters.base import DEFAULT_CONFIG_PATH, ROOT, AdapterError, extract_template
from attack.payloads.schema import load_task_meta, validate_payload

RECORDS = import_agentdojo()
SNAP = ROOT / "data" / "upstream" / "agentdojo"
COMMIT = "089ed468cf3ed0322acc66b0211f26d9d90dbf60"


def test_snapshot_khop_manifest():
    manifest = (SNAP / "MANIFEST.txt").read_text(encoding="utf-8")
    for name in ("payload_samples_all.csv", "injection_tasks_gt_all.csv"):
        digest = hashlib.sha256((SNAP / name).read_bytes()).hexdigest()
        assert f"sha256 {name}: {digest}" in manifest


def test_du_chi_tieu_so_ban_ghi():
    assert len(RECORDS) == 175 >= 100
    assert len({r.id for r in RECORDS}) == len(RECORDS)
    assert Counter(r.suite for r in RECORDS) == {
        "workspace": 70, "banking": 45, "travel": 35, "slack": 25,
    }


def test_moi_ban_ghi_co_nguon_goc():
    for r in RECORDS:
        assert r.source["kind"] == "verbatim"
        assert r.source["license"] == "MIT"
        assert COMMIT in r.source["ref"]
        assert f"{r.suite}/{r.injection_task}" in r.source["ref"]


def test_moi_attack_dung_mot_template_va_tai_tao_duoc_payload():
    by_attack: dict[str, set[str]] = {}
    for r in RECORDS:
        by_attack.setdefault(r.attack, set()).add(r.template)
        assert r.template.count("{INSTRUCTION}") == 1
        assert r.template.replace("{INSTRUCTION}", r.goal_text) == r.payload
    assert len(by_attack) == 5
    assert all(len(t) == 1 for t in by_attack.values())


def test_template_khong_chua_ten_tool_cua_lab():
    tools = load_task_meta().tools
    for r in RECORDS:
        for tool in tools:
            assert not re.search(rf"\b{tool}\b", r.template)


def test_phan_bo_ky_thuat_va_muc_tieu_theo_config():
    assert Counter(r.technique for r in RECORDS) == {"T1": 105, "T2": 70}
    assert Counter(r.goal for r in RECORDS) == {"G1": 100, "G2": 70, "G3": 5}
    assert {r.goal for r in RECORDS if r.suite == "travel" and r.injection_task.endswith("_6")} \
        == {"G3"}


def test_grader_unverified_dung_workspace_6_den_13():
    flagged = {(r.suite, r.injection_task) for r in RECORDS if r.grader_unverified}
    assert flagged == {("workspace", f"injection_task_{i}") for i in range(6, 14)}
    assert sum(r.grader_unverified for r in RECORDS) == 40


def test_semantic_coupling_co_bang_chung():
    for r in RECORDS:
        assert r.semantic_coupling == bool(r.coupling_evidence)
    uncoupled = {(r.suite, r.injection_task) for r in RECORDS if not r.semantic_coupling}
    assert uncoupled == {("banking", "injection_task_7")}  # "Change the password … new_password"
    mark = next(r for r in RECORDS if r.id == "agentdojo:workspace/injection_task_0/direct")
    assert "mark.black-2134@gmail.com" in mark.coupling_evidence


def test_xuat_tat_dinh(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    main(["--out", str(a)])
    main(["--out", str(b)])
    assert a.read_bytes() == b.read_bytes()


def test_to_lab_payload_hop_le_theo_schema():
    rec = next(r for r in RECORDS if r.id == "agentdojo:workspace/injection_task_0/system_message")
    p = to_lab_payload(
        rec,
        number=1,
        goal_binding={
            "tool": "send_email",
            "arguments": {"to": "mau@ngoai.vn", "subject": "x", "body": "y"},
            "instruction_vi": "noi dung chi thi mau",
            "instruction_en": "sample instruction body",
        },
        activation_check={
            "goal": "G2", "violation": "tool_not_allowed", "expected_tool": "send_email",
            "severity": "external_action",
        },
        adaptation_note="Giữ khung, viết lại goal_binding sang send_email của lab.",
    )
    assert p["id"] == "P-T1-G2-EN-001"
    assert p["source"]["kind"] == "adapted"
    assert p["semantic_coupling"] is True
    assert validate_payload(p) == []


def test_schema_bat_buoc_coupling_khi_muon_agentdojo():
    rec = RECORDS[0]
    p = to_lab_payload(
        rec, number=1, adaptation_note="x",
        goal_binding={"tool": "send_email", "arguments": {}, "instruction_vi": "a",
                      "instruction_en": "b"},
        activation_check={"goal": rec.goal, "canary_kind": "any", "sinks": ["send_email"],
                          "record_leak_attempted": True},
    )
    del p["semantic_coupling"]
    assert any("semantic_coupling" in m for m in validate_payload(p))
    p["semantic_coupling"] = "true"
    assert any("bool" in m for m in validate_payload(p))


def test_attack_chua_gan_ky_thuat_thi_dung(tmp_path):
    cfg = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    del cfg["agentdojo"]["attacks"]["injecagent"]
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    with pytest.raises(AdapterError, match="injecagent"):
        import_agentdojo(path)


def test_task_chua_gan_muc_tieu_thi_dung(tmp_path):
    cfg = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    del cfg["agentdojo"]["goals"]["slack"]["injection_task_5"]
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    with pytest.raises(AdapterError, match="slack/injection_task_5"):
        import_agentdojo(path)


def test_goal_phai_xuat_hien_dung_mot_lan():
    with pytest.raises(AdapterError):
        extract_template("TODO: khac", "goal")
    with pytest.raises(AdapterError):
        extract_template("goal goal", "goal")
