"""CỔNG KIỂM CHỨNG BỘ CHẤM — 8/8 ca thử (STT-36, quy tắc cứng #5).

Tám ca và đáp án ở `tests/fixtures/scorer_gate/cases.yaml`, chép nguyên từ `docs/04. Design/07. Chỉ
số đo.md` mục 10.3. Sai một ca là chưa đạt: không chạy ma trận. Chưa đạt thì sửa scorer, không sửa
đáp án. Bằng chứng gắn commit: `scripts/run_scorer_gate.py` → `results/scorer_gate/`.
"""

import pytest

from eval.scorer_gate import CASES_PATH, N_CASES, REPEATS, load_cases, run_gate


@pytest.fixture(scope="module")
def report():
    return run_gate()


@pytest.mark.parametrize("case_id", range(1, N_CASES + 1))
def test_ca_dung_moi_truong_dap_an(report, case_id):
    case = report.cases[case_id - 1]
    assert case.id == case_id
    assert case.mismatches == {}, f"ca {case_id} ({case.checks}): {{trường: (đáp án, scorer)}}"


@pytest.mark.parametrize("case_id", range(1, N_CASES + 1))
def test_ca_tat_dinh_qua_100_lan(report, case_id):
    assert report.repeats == REPEATS == 100
    assert report.cases[case_id - 1].deterministic


def test_cong_dat_8_tren_8(report):
    assert report.n_passed == N_CASES and report.passed


def test_cong_bat_duoc_dap_an_sai(tmp_path):
    # Cổng không được đạt rỗng: đổi một trường đáp án thì đúng ca đó trượt, cổng chưa đạt.
    raw = CASES_PATH.read_text(encoding="utf-8")
    bad = tmp_path / "cases.yaml"
    bad.write_text(raw.replace("blocked_by: model_refusal", "blocked_by: defense"), encoding="utf-8")
    broken = run_gate(cases_path=bad, repeats=2)
    assert not broken.passed and [c.id for c in broken.cases if not c.passed] == [8]
    assert broken.cases[7].mismatches == {"blocked_by": ("defense", "model_refusal")}


def test_dap_an_du_truong_bat_buoc():
    # Mọi ca kiểm outcome, blocked_by, ba cờ G và parse_error — đúng cờ chính mà sai outcome là trượt.
    for case in load_cases()["cases"]:
        missing = {"g1_hit", "g2_hit", "g3_hit", "outcome", "blocked_by", "parse_error"}
        missing -= set(case["expected"])
        assert not missing, f"ca {case['id']} thiếu {sorted(missing)}"
