"""Tiêu chí RQ1/RQ2 của phân tích B1 (`eval.b1_analysis`)."""

from __future__ import annotations

import pytest

from eval.b1_analysis import Count, kendall_tau_b, overlap, tally, top_group


def test_tally_loai_parse_error_va_dem_delivered_refusal():
    runs = [
        {"parse_error": 0, "outcome": "success", "delivered": 1, "blocked_by": None},
        {"parse_error": 0, "outcome": "blocked", "delivered": 1, "blocked_by": "model_refusal"},
        {"parse_error": 0, "outcome": "failed", "delivered": 0, "blocked_by": None},
        {"parse_error": 1, "outcome": None, "delivered": None, "blocked_by": None},
    ]
    c = tally(runs)
    assert (c.n, c.s, c.d, c.refusal) == (3, 1, 2, 1)
    assert c.asr == pytest.approx(1 / 3) and c.asr_cond == pytest.approx(0.5)


def test_overlap_wilson():
    assert overlap((0.0, 0.02), (0.06, 0.12)) is False
    assert overlap((0.0, 0.1), (0.06, 0.12)) is True
    assert overlap(None, (0.1, 0.2)) is None


def test_top_group_theo_can_tren_ge_can_duoi_dau_bang():
    assert top_group({"T3": (0.87, (0.70, 0.95)), "T5": (0.33, (0.19, 0.51)),
                      "T8": (0.37, (0.22, 0.54))}) == ["T3"]
    # Sàn: mọi kỹ thuật 0 thì cả nhóm đều "mạnh nhất" — không phân định được.
    assert top_group({"T1": (0.0, (0.0, 0.11)), "T2": (0.0, (0.0, 0.11))}) == ["T1", "T2"]


def test_kendall_tau_b():
    assert kendall_tau_b([1, 2, 3, 4], [1, 2, 3, 4]) == pytest.approx(1.0)
    assert kendall_tau_b([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    # Có hòa, tính tay: 6 cặp, 4 thuận, 0 nghịch, 1 hòa ở x, 1 hòa ở y ⇒ 4 / √(5 · 5) = 0,8.
    assert kendall_tau_b([1, 2, 2, 3], [1, 3, 2, 3]) == pytest.approx(0.8)
    assert kendall_tau_b([0, 0, 0], [1, 2, 3]) is None


def test_count_khong_run_hop_le():
    c = Count(0, 0, 0, 0)
    assert c.asr is None and c.ci is None and c.asr_cond is None
