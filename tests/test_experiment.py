"""Khung giao thức thực nghiệm `config/experiment.yaml` (STT-24).

DoD (`docs/06. Track/Lộ trình triển khai code.md`, giai đoạn 1): runner đọc được, chưa cần đủ
giá trị. Thêm hai lớp canh: mọi tên trong file trỏ đúng nguồn của nó, và số run của từng khối
khớp thiết kế phân khối GVHD đã ký (checklist mục 5).
"""

import json
from pathlib import Path

import pytest
import yaml

from eval.experiment import ExperimentConfigError, load_experiment, unresolved, validate
from seed_db import ANCHOR_DATE

# Tập kỹ thuật chung của ba phân kênh — checklist mục 4.
T_CHUNG = {"T1", "T2", "T3", "T5", "T7", "T8"}

# Số run ước tính, checklist mục 5. B2, B3 có 7 preset sau khi GVHD duyệt `d3_no_confirm` (2026-10-21).
# B4 "~500" — giao thức chốt 516 (mục 9).
CHECKLIST_RUNS = {"B1": 3780, "B2": 5040, "B3": 4200, "B4": 516, "B5": 900, "B6": 450}


@pytest.fixture(scope="module")
def exp():
    return load_experiment()


def test_nap_duoc_va_doi_chieu_sach(exp):
    assert validate(exp) == []


def test_du_sau_khoi(exp):
    assert list(exp.blocks) == ["B1", "B2", "B3", "B4", "B5", "B6"]


@pytest.mark.parametrize("block_id", ["B1", "B2", "B3", "B4", "B5", "B6"])
def test_so_run_khop_checklist(exp, block_id):
    assert exp.planned_runs(block_id) == CHECKLIST_RUNS[block_id]


def test_b2_do_lai_off_cung_lo(exp):
    # DSR lấy ASR(off) đo lại trong B2, không lấy từ B1 (giao thức mục 8, N1–N2).
    assert "off" in exp.blocks["B2"].presets
    assert exp.blocks["B2"].best_single == {"select_on": "full_block", "per": "goal"}


def test_d3_no_confirm_o_b2_b3_khong_la_ung_vien_don_le(exp):
    # GVHD duyệt 2026-10-21: tách R1–R3 khỏi R4, báo cáo khám phá, không tranh "đơn lẻ tốt nhất".
    for block_id in ("B2", "B3"):
        assert "d3_no_confirm" in exp.blocks[block_id].presets
    assert not "d3_no_confirm".endswith("_only")


def test_b4_ba_phan(exp):
    parts = exp.blocks["B4"].parts
    assert list(parts) == ["rq12", "rq3", "rq4"]
    assert all(p.targets == ("A1",) for p in parts.values())
    assert {ch: set(ts) for ch, ts in parts["rq12"].techniques_by_channel.items()} == {
        ch: T_CHUNG for ch in ("K1", "K2a", "K2b")
    }
    assert [exp._planned(p) for p in parts.values()] == [216, 180, 120]


def test_pilot_tach_cong_va_chi_do(exp):
    pilot = exp.raw["pilot"]
    assert tuple(pilot["targets"]) == exp.blocks["B1"].targets  # cổng tính trên target của B1
    assert pilot["observe_targets"] == ["A1"]
    assert pilot["variance_probe"]["p_same_threshold"] == 0.9


def test_ky_thuat_theo_kenh_khop_t_chung(exp):
    by_channel = {ch: set(ts) for ch, ts in exp.blocks["B1"].techniques_by_channel.items()}
    assert by_channel["K2a"] == T_CHUNG
    assert by_channel["K2b"] == T_CHUNG | {"T4"}
    assert by_channel["K1"] == T_CHUNG | {"T4", "T6"}


def test_ngay_tham_chieu_trung_moc_cua_customers_db(exp):
    assert exp.fixed["reference_date"] == ANCHOR_DATE.isoformat()


def test_max_steps_rong_hon_max_calls_cua_moi_tac_vu(exp):
    # MAX_STEPS nhỏ hơn max_calls thì nhãn `loop` không bao giờ xảy ra, và agent bị cắt trước khi
    # tác vụ hợp lệ kịp xong — hiện ra như "model kém" (Y_TUONG_DU_AN.md mục 2.7).
    tasks = json.loads(exp.contract_path("carrier_tasks").read_text(encoding="utf-8"))
    assert exp.fixed["max_steps"] > max(t["max_calls"] for t in tasks["carrier_tasks"])


def test_khoi_b1_khong_con_truong_chua_chot(exp):
    # B1 tự nó đủ giá trị; thứ còn chặn nó (nếu có) chỉ là trường dùng chung của file.
    assert not [p for p in unresolved(exp, "B1") if p.startswith("blocks.B1")]


def test_unresolved_bat_duoc_todo(exp):
    paths = unresolved(exp)
    assert "blocks.B4.parts.rq3.cells.selected" in paths
    # B5 còn chặn bởi cells.selected (tập S_adp chọn sau B2); attacker_model đã chốt opus-5 (STT-57).
    assert "blocks.B5.cells.selected" in paths
    assert "blocks.B5.attacker_model" not in paths


def test_tu_choi_khoa_la(tmp_path: Path):
    src = Path(load_experiment().path).read_text(encoding="utf-8")
    bad = tmp_path / "experiment.yaml"
    bad.write_text(src.replace("    n_per_cell: 30\n", "    n_per_cel: 30\n", 1), encoding="utf-8")
    with pytest.raises(ExperimentConfigError, match="n_per_cel"):
        load_experiment(bad)


def test_validate_bat_ten_sai(tmp_path: Path):
    src = Path(load_experiment().path).read_text(encoding="utf-8")
    bad = tmp_path / "experiment.yaml"
    bad.write_text(src.replace("targets: [A2, A3]", "targets: [A2, A4]", 1), encoding="utf-8")
    assert any("A4" in p for p in validate(load_experiment(bad)))


def test_refusal_da_chot_truoc_pilot(exp):
    refusal = exp.raw["refusal"]
    assert "refusal" in refusal["finish_reasons"]  # stop_reason gốc của Messages API (A1)
    phrases = refusal["phrases"]
    assert phrases and len(phrases) == len(set(phrases))
    # So khớp trên văn bản đã chuẩn hóa chữ thường — cụm viết hoa không bao giờ khớp.
    assert all(p == p.lower() and p == p.strip() for p in phrases)
    assert not [p for p in unresolved(exp) if p.startswith("refusal")]


def test_refusal_chua_chot_chan_moi_khoi(tmp_path: Path):
    src = Path(load_experiment().path).read_text(encoding="utf-8")
    head, _, tail = src.partition("  phrases:\n")
    rest = tail.split("\n\n", 1)[1]  # bỏ danh sách cụm tới dòng trống kế tiếp
    cfg = tmp_path / "experiment.yaml"
    cfg.write_text(head + "  phrases: null\n\n" + rest, encoding="utf-8")
    exp = load_experiment(cfg)
    assert not validate(exp)
    for block_id in exp.blocks:
        assert "refusal.phrases" in unresolved(exp, block_id)


@pytest.mark.parametrize("bad", ["[]", '[""]', "[1, 2]", '"content_filter"'])
def test_validate_bat_refusal_sai_kieu(tmp_path: Path, bad):
    src = Path(load_experiment().path).read_text(encoding="utf-8")
    line = "  finish_reasons: [content_filter, refusal]"
    assert line in src
    cfg = tmp_path / "experiment.yaml"
    cfg.write_text(src.replace(line, f"  finish_reasons: {bad}"), encoding="utf-8")
    assert any("refusal.finish_reasons" in p for p in validate(load_experiment(cfg)))


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("R4_require_confirmation.enabled", "R4_require_confirmaton.enabled"),
        ('"d3_tool_policy.rules', '"d4_egress_filter.rules'),
        ('  d3_no_confirm:\n    "', '  d3_no_confirn:\n    "'),
    ],
)
def test_validate_bat_ghi_de_preset_sai(tmp_path: Path, old, new):
    exp = load_experiment()
    src = exp.contract_path("defenses").read_text(encoding="utf-8")
    assert old in src
    defenses = tmp_path / "defenses.yaml"
    defenses.write_text(src.replace(old, new, 1), encoding="utf-8")
    cfg = tmp_path / "experiment.yaml"
    text = Path(exp.path).read_text(encoding="utf-8")
    rel = exp.raw["contracts"]["defenses"]
    assert text.count(rel) == 1
    cfg.write_text(text.replace(rel, str(defenses)), encoding="utf-8")
    assert any("preset_overrides" in p for p in validate(load_experiment(cfg)))


def test_metrics_tcp_ci_da_chot(exp):
    tcp_ci = exp.raw["metrics"]["tcp_ci"]
    assert tcp_ci == {
        "method": "bootstrap_percentile",
        "resamples": 2000,
        "level": 0.95,
        "seed": 97,
    }
    assert not [p for p in unresolved(exp) if p.startswith("metrics")]


@pytest.mark.parametrize(
    "old, new",
    [
        ("method: bootstrap_percentile", "method: wald"),
        ("resamples: 2000", "resamples: 0"),
        ("level: 0.95", "level: 95"),
        ("seed: 97 ", "seed: true "),
    ],
)
def test_validate_bat_metrics_sai(tmp_path: Path, old, new):
    src = Path(load_experiment().path).read_text(encoding="utf-8")
    assert old in src
    cfg = tmp_path / "experiment.yaml"
    cfg.write_text(src.replace(old, new, 1), encoding="utf-8")
    assert any(p.startswith("metrics.tcp_ci") for p in validate(load_experiment(cfg)))


@pytest.mark.parametrize(
    ("old", "new", "expect"),
    [
        ("observe_targets: [A1]", "observe_targets: [A2]", "vừa tính cổng vừa chỉ đo"),
        ("p_same_threshold: 0.9", "p_same_threshold: 1.5", "p_same_threshold"),
        ("{select_on: full_block, per: goal}", "{select_on: pilot, per: goal}", "select_on"),
        ("add_best_single_from: B2", "add_best_single_from: B1", "add_best_single_from"),
        ("        n_per_cell: 4\n", "        n_per_cell: 4\n        purpose: [RQ1]\n", "khóa lạ"),
    ],
)
def test_validate_bat_quyet_dinh_sai(tmp_path: Path, old, new, expect):
    src = Path(load_experiment().path).read_text(encoding="utf-8")
    assert src.count(old) == 1
    cfg = tmp_path / "experiment.yaml"
    cfg.write_text(src.replace(old, new), encoding="utf-8")
    try:
        problems = validate(load_experiment(cfg))
    except ExperimentConfigError as err:
        problems = [str(err)]
    assert any(expect in p for p in problems), problems


def test_benign_task_types_theo_lua_chon_nhan_vien(exp):
    # Quy tắc "loại tác vụ nhân viên thật sẽ chọn" (checklist mục 4). Câu có tool kỳ vọng ngoài
    # allowlist của task_type là chỗ R1 chặn nhầm — đúng 10 câu CT-04 hỏi/kiểm tồn kho, chọn có
    # chủ ý; thêm câu nào vào tập này là gán sai.
    defenses = yaml.safe_load(exp.contract_path("defenses").read_text(encoding="utf-8"))
    task_types = defenses["defenses"]["d3_tool_policy"]["task_types"]
    queries = json.loads(exp.contract_path("benign_queries").read_text(encoding="utf-8"))["queries"]
    of = {qid: t for t, qids in exp.raw["benign_task_types"].items() for qid in qids}
    assert len(of) == len(queries) == 60
    r1_blocked = {
        q["id"]
        for q in queries
        if any(
            c["tool"] not in task_types[of[q["id"]]]["allowlist"] for c in q["expected_tool_calls"]
        )
    }
    ct04 = {q["id"] for q in queries if q["carrier_task_id"] == "CT-04"}
    assert r1_blocked == ct04 and len(ct04) == 10
    assert all(of[qid] == "LOOKUP" for qid in ct04)
    assert not unresolved(exp, "B3")


@pytest.mark.parametrize(
    ("old", "new", "expect"),
    [
        ("BQ-U4-010\n", "BQ-U4-009\n", "hơn một task_type"),
        ("  SEND_MAIL:  #", "  SENDMAIL:  #", "không phải task_type"),
    ],
)
def test_validate_bat_task_type_sai(tmp_path: Path, old, new, expect):
    src = Path(load_experiment().path).read_text(encoding="utf-8")
    assert src.count(old) == 1
    cfg = tmp_path / "experiment.yaml"
    cfg.write_text(src.replace(old, new), encoding="utf-8")
    assert any(expect in p for p in validate(load_experiment(cfg)))


def test_utility_baseline_ngoai_sau_khoi_va_khong_chan(exp):
    assert "utility_baseline" not in exp.blocks
    assert exp.planned_runs("utility_baseline") == 540
    assert unresolved(exp, "utility_baseline") == []
    with pytest.raises(KeyError):
        exp.unit("B9")


@pytest.mark.parametrize(
    "old, new, expect",
    [
        ("  repeats: 3\n", "  repeats: 0\n", "repeats"),
        ("  targets: [A1, A2, A3]\n", "  targets: [A1, A4]\n", "A4"),
        (
            "  queries: all                    # 60",
            "  queries: some                   # 60",
            "mọi câu",
        ),
    ],
)
def test_validate_bat_utility_baseline_sai(tmp_path: Path, old, new, expect):
    src = Path(load_experiment().path).read_text(encoding="utf-8")
    assert old in src
    bad = tmp_path / "experiment.yaml"
    bad.write_text(src.replace(old, new, 1), encoding="utf-8")
    assert any(expect in p for p in validate(load_experiment(bad)))
