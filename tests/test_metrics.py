"""Chỉ số hữu dụng — ví dụ tính tay của `docs/04. Design/07. Chỉ số đo.md` mục 3.2, 5.2, 6.2."""

from __future__ import annotations

import pandas as pd
import pytest

from eval.experiment import load_experiment
from eval.metrics import (
    TcpCi,
    group_of,
    query_level,
    rate,
    utility_cell,
    utility_summary,
    wilson,
)


@pytest.mark.parametrize(
    "x, n, lo, hi",
    [
        (0, 30, 0.00, 11.35),
        (2, 30, 1.85, 21.32),
        (3, 30, 3.46, 25.62),
        (9, 12, 46.77, 91.11),
        (9, 30, 16.66, 47.88),
        (6, 47, 5.98, 25.17),
        (18, 30, 42.32, 75.41),
        (27, 30, 74.38, 96.54),
        (30, 30, 88.65, 100.00),
    ],
)
def test_wilson_khop_bang_3_2(x, n, lo, hi):
    got_lo, got_hi = wilson(x, n)
    assert round(got_lo * 100, 2) == lo
    assert round(got_hi * 100, 2) == hi


def test_wilson_tu_choi_n_0_va_x_ngoai_mien():
    with pytest.raises(ValueError):
        wilson(0, 0)
    with pytest.raises(ValueError):
        wilson(5, 4)
    assert rate(0, 0) is None


def _run(qid: str, outcome: str | None, *, blocked_by=None, parse_error=False, tcp=1.0, **kw):
    return {
        "run_kind": "benign",
        "target_id": kw.get("target_id", "A2"),
        "benign_query_id": qid,
        "outcome": outcome,
        "blocked_by": blocked_by,
        "parse_error": parse_error,
        "tcp": tcp,
        "judge_pass": kw.get("judge_pass", outcome == "pass"),
        "hard_fact_pass": kw.get("hard_fact_pass", outcome == "pass"),
        "keyword_check_pass": kw.get("keyword_check_pass"),
        "g2_hit": kw.get("g2_hit", False),
    }


def _example_5_2() -> pd.DataFrame:
    rows = [_run(f"BQ-U1-{i:03d}", "pass") for i in range(51)]
    rows += [_run(f"BQ-U4-{i:03d}", "blocked", blocked_by="defense") for i in range(6)]
    rows += [_run(f"BQ-U2-{i:03d}", "fail") for i in range(2)]
    rows += [_run("BQ-U3-001", "blocked", blocked_by="model_refusal")]
    return pd.DataFrame(rows)


def test_vi_du_5_2_usr_frr_model_fail():
    cell = utility_cell(_example_5_2())
    assert (cell["n_clean"], cell["p"], cell["b_def"]) == (60, 51, 6)
    for name, p, lo, hi in [
        ("usr", 85.0, 73.89, 91.90),
        ("frr", 10.0, 4.66, 20.15),
        ("model_fail_rate", 5.0, 1.71, 13.70),
    ]:
        assert round(cell[name] * 100, 2) == p
        assert round(cell[f"{name}_lo"] * 100, 2) == lo
        assert round(cell[f"{name}_hi"] * 100, 2) == hi
    assert abs(cell["usr"] + cell["frr"] + cell["model_fail_rate"] - 1) <= 1e-9


def test_parse_error_roi_mau_va_bat_co_ra_soat():
    df = pd.DataFrame(
        [
            _run("BQ-U1-001", "pass"),
            _run("BQ-U1-002", "fail"),
            _run("BQ-U1-003", None, parse_error=True),
        ]
    )
    cell = utility_cell(df, review_ratio=0.05)
    assert (cell["n_raw"], cell["n_excl"], cell["n_clean"]) == (3, 1, 2)
    assert cell["usr"] == 0.5 and cell["review_flag"] is True
    assert utility_cell(df.iloc[:2], review_ratio=0.05)["review_flag"] is False


def test_tcp_vi_du_6_2_va_bo_run_khong_co_required():
    df = pd.DataFrame(
        [
            _run("BQ-U4-001", "fail", tcp=2 / 3),
            _run("BQ-U4-001", "pass", tcp=1.0),
            _run("BQ-U4-001", "blocked", blocked_by="model_refusal", tcp=0.0),
            _run("BQ-U1-001", "pass", tcp=None),
        ]
    )
    exp = load_experiment()
    cell = utility_cell(df, tcp=TcpCi.from_experiment(exp))
    assert round(cell["tcp"], 3) == 0.556
    assert cell["tcp_n_dropped"] == 1
    assert 0.0 <= cell["tcp_lo"] <= cell["tcp"] <= cell["tcp_hi"] <= 1.0
    again = utility_cell(df, tcp=TcpCi.from_experiment(exp))
    assert (again["tcp_lo"], again["tcp_hi"]) == (cell["tcp_lo"], cell["tcp_hi"])


def test_lap_nhieu_lan_bat_co_units_lt_n():
    df = pd.DataFrame([_run("BQ-U1-001", "pass") for _ in range(3)])
    assert utility_cell(df)["units_lt_n"] is True
    assert utility_cell(df.iloc[:1])["units_lt_n"] is False


def test_tach_ba_cot_cua_muc_12_3():
    df = pd.DataFrame(
        [
            _run(
                "BQ-U1-001", "fail", judge_pass=True, hard_fact_pass=False, keyword_check_pass=True
            ),
            _run("BQ-U1-002", "pass", keyword_check_pass=False),
        ]
    )
    cell = utility_cell(df)
    assert cell["judge_pass_rate"] == 1.0
    assert cell["hard_fact_pass_rate"] == 0.5
    assert cell["keyword_check_pass_rate"] == 0.5


def test_tu_choi_run_tan_cong():
    df = pd.DataFrame([_run("BQ-U1-001", "pass") | {"run_kind": "attack"}])
    with pytest.raises(ValueError, match="lành tính"):
        utility_cell(df)


def test_utility_summary_theo_target_nhom_va_dong_tong():
    df = _example_5_2()
    df.loc[:9, "target_id"] = "A3"
    table = utility_summary(df, by=("target_id", "group"))
    total_a2 = table[(table["target_id"] == "A2") & (table["group"] == "ALL")].iloc[0]
    assert total_a2["n_clean"] == 50
    a3 = table[table["target_id"] == "A3"]
    assert set(a3["group"]) == {"U1", "ALL"}
    assert table[table["group"] != "ALL"]["n_clean"].sum() == 60


def test_query_level_da_so_va_hoa_la_khong_dat():
    df = pd.DataFrame(
        [
            _run("BQ-U1-001", "pass"),
            _run("BQ-U1-001", "pass"),
            _run("BQ-U1-001", "fail"),
            _run("BQ-U1-002", "pass"),
            _run("BQ-U1-002", "fail"),
            _run("BQ-U1-002", None, parse_error=True),
            _run("BQ-U1-003", None, parse_error=True),
        ]
    )
    out = query_level(df).set_index("benign_query_id")
    assert out.loc["BQ-U1-001", "query_pass"]
    assert not out.loc["BQ-U1-002", "query_pass"]
    assert out.loc["BQ-U1-002", "n_repeats_clean"] == 2
    assert "BQ-U1-003" not in out.index


def test_group_of():
    assert group_of("BQ-U3-012") == "U3"
    with pytest.raises(ValueError):
        group_of("CT-01")
