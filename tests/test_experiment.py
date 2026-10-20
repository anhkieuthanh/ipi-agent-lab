"""Khung giao thức thực nghiệm `config/experiment.yaml` (STT-24).

DoD (`docs/06. Track/Lộ trình triển khai code.md`, giai đoạn 1): runner đọc được, chưa cần đủ
giá trị. Thêm hai lớp canh: mọi tên trong file trỏ đúng nguồn của nó, và số run của từng khối
khớp thiết kế phân khối GVHD đã ký (checklist mục 5).
"""

import json
from pathlib import Path

import pytest

from eval.experiment import ExperimentConfigError, load_experiment, unresolved, validate
from seed_db import ANCHOR_DATE

# Tập kỹ thuật chung của ba phân kênh — checklist mục 4.
T_CHUNG = {"T1", "T2", "T3", "T5", "T7", "T8"}

# Số run ước tính, checklist mục 5 (đã ký). B4 "~500" chưa có công thức.
CHECKLIST_RUNS = {"B1": 3780, "B2": 4320, "B3": 4200, "B5": 900, "B6": 450}

# Checklist đếm 7 preset (`off`, `d1_only`…`d4_only`, `all`, `reduced_3`) nhưng `reduced_3` là
# nhóm {off, d3_only, all}, không phải một cấu hình phòng thủ — defenses.yaml chỉ có 6 preset chạy
# được, nên B2 (5 preset bật) và B3 (6 preset) ra 3.600 thay vì 4.320 và 4.200. B5 cùng checklist
# dùng 5 preset bật, khớp. Chờ TA quyết; xfail strict để báo ngay khi hai bên khớp lại.
PRESET_COUNT_MISMATCH = pytest.mark.xfail(
    strict=True, reason="checklist mục 5 đếm reduced_3 như một preset — chờ TA chốt"
)


@pytest.fixture(scope="module")
def exp():
    return load_experiment()


def test_nap_duoc_va_doi_chieu_sach(exp):
    assert validate(exp) == []


def test_du_sau_khoi(exp):
    assert list(exp.blocks) == ["B1", "B2", "B3", "B4", "B5", "B6"]


@pytest.mark.parametrize(
    "block_id",
    [
        "B1",
        pytest.param("B2", marks=PRESET_COUNT_MISMATCH),
        pytest.param("B3", marks=PRESET_COUNT_MISMATCH),
        "B5",
        "B6",
    ],
)
def test_so_run_khop_checklist(exp, block_id):
    assert exp.planned_runs(block_id) == CHECKLIST_RUNS[block_id]


def test_b4_chua_co_cong_thuc(exp):
    assert exp.planned_runs("B4") is None


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
    assert "blocks.B4.subset" in paths
    assert "blocks.B5.attacker_model" in paths
    assert "benign_task_types" in unresolved(exp, "B3")
    assert "benign_task_types" not in unresolved(exp, "B1")


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
        ("  d3_no_confirm:\n    \"", "  d3_no_confirn:\n    \""),
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
