"""Quy tắc chọn ô S_def (`eval.cell_select`) — cận dưới Wilson, xếp ASR gộp, ASR sàn, hòa ranh giới."""

from __future__ import annotations

import sqlite3

import pytest

from eval.cell_select import CellSelectError, CellStat, cell_stats, select_s_def


def _stat(cell, a2, a3):
    return CellStat(cell, {"A2": a2, "A3": a3})


def test_chon_o_dat_nguong_xep_theo_asr_gop():
    stats = [
        _stat(("K1", "T1", "G1"), (10, 10), (0, 10)),  # gộp 0,50, đạt nhờ A2
        _stat(("K1", "T2", "G1"), (8, 10), (9, 10)),  # gộp 0,85
        _stat(("K1", "T3", "G1"), (1, 10), (1, 10)),  # không đạt: cận dưới < 0,10
        _stat(("K1", "T4", "G1"), (6, 10), (6, 10)),  # gộp 0,60
    ]
    chosen, floor = select_s_def(stats, min_ci_low=0.10, max_cells=2)
    assert [c.cell for c in chosen] == [("K1", "T2", "G1"), ("K1", "T4", "G1")]
    assert not floor


def test_it_o_dat_nguong_thi_lay_asr_san():
    stats = [
        _stat(("K1", "T1", "G1"), (3, 10), (3, 10)),
        _stat(("K1", "T2", "G1"), (1, 10), (0, 10)),
        _stat(("K1", "T3", "G1"), (0, 10), (0, 10)),
    ]
    chosen, floor = select_s_def(stats, min_ci_low=0.10, max_cells=2)
    assert floor
    assert [c.cell for c in chosen] == [("K1", "T1", "G1"), ("K1", "T2", "G1")]


def test_hoa_o_ranh_gioi_bao_loi():
    stats = [
        _stat(("K1", "T1", "G1"), (9, 10), (9, 10)),
        _stat(("K1", "T2", "G1"), (8, 10), (8, 10)),
        _stat(("K1", "T3", "G1"), (10, 10), (6, 10)),
    ]
    with pytest.raises(CellSelectError, match="hòa"):
        select_s_def(stats, min_ci_low=0.10, max_cells=2)


def test_cell_stats_loai_parse_error(tmp_path):
    store = tmp_path / "trace.sqlite"
    with sqlite3.connect(store) as con:
        con.execute("CREATE TABLE runs (run_kind, channel, technique, goal, target_id, outcome,"
                    " parse_error)")
        con.executemany("INSERT INTO runs VALUES ('attack','K1','T1','G1',?,?,?)", [
            ("A2", "success", 0), ("A2", "failed", 0), ("A2", None, 1), ("A1", "success", 0),
        ])
    [stat] = cell_stats(store, ["A2", "A3"])
    assert stat.by_target == {"A2": (1, 2)}
