"""Kế hoạch B5 (`attack.adaptive_block`) và phép điền S_adp vào config (`scripts/select_cells.py`)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from attack.adaptive_block import plan_adaptive
from attack.runner import AttackRunnerError, load_carriers, load_corpus
from eval.cell_select import CellSelectError, DsrStat, select_s_adp
from eval.experiment import load_experiment, unresolved, validate

ROOT = Path(__file__).resolve().parent.parent
CELLS = [["K2a", "T3", "G2"], ["K2a", "T3", "G3"], ["K2b", "T4", "G3"]]


def _config_b5_cells_null() -> str:
    """Bản config với `blocks.B5.cells.source_batch/selected` = null — trạng thái trước khi chọn ô.

    Config hiện hành đã điền S_adp (STT-75), nhưng các test ở đây kiểm chính PHÉP điền/từ chối nên cần
    bản chưa điền. Thu gọn khối đã điền về dạng null bằng regex trên văn bản (giữ đúng format mà
    `select_cells.write_config` khớp dòng)."""
    import re

    lines = (ROOT / "config/experiment.yaml").read_text(encoding="utf-8").splitlines(keepends=True)
    start = next(i for i, ln in enumerate(lines) if ln.rstrip() == "  B5:")
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].startswith("  ") and not lines[i].startswith("   ")
                and lines[i].strip()), len(lines))
    block = "".join(lines[start:end])
    block = re.sub(r"(?m)^      source_batch: .*$", "      source_batch: null", block)
    block = re.sub(r"(?m)^      selected:\n(?:        - .*\n)+", "      selected: null\n", block)
    return "".join(lines[:start]) + block + "".join(lines[end:])


def _select_cells_module():
    spec = importlib.util.spec_from_file_location("select_cells", ROOT / "scripts/select_cells.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def exp_b5(tmp_path, monkeypatch):
    cfg = tmp_path / "experiment.yaml"
    cfg.write_text(_config_b5_cells_null(), encoding="utf-8")
    mod = _select_cells_module()
    monkeypatch.setattr(mod, "CONFIG", cfg)
    mod.write_config("B5", "attack-B2-20261119T000000Z", CELLS)
    return load_experiment(cfg)


def test_write_config_dien_b5_giu_khoi_khac(exp_b5):
    assert exp_b5.blocks["B5"].cells["selected"] == CELLS
    assert exp_b5.blocks["B5"].cells["source_batch"] == "attack-B2-20261119T000000Z"
    assert exp_b5.blocks["B2"].cells == load_experiment().blocks["B2"].cells
    assert not validate(exp_b5)
    assert not [p for p in unresolved(exp_b5, "B5") if p.startswith("blocks.B5")]


def test_write_config_tu_choi_khi_da_dien(exp_b5, monkeypatch, tmp_path):
    mod = _select_cells_module()
    monkeypatch.setattr(mod, "CONFIG", tmp_path / "experiment.yaml")
    with pytest.raises(SystemExit, match="không còn"):
        mod.write_config("B5", "attack-B2-x", CELLS)


def test_plan_adaptive_so_chuoi_va_chain_id_tat_dinh(exp_b5):
    corpus, carriers = load_corpus(), load_carriers()
    plans = plan_adaptive(exp_b5, "B5", corpus=corpus, carriers=carriers, seed=1)
    b5 = exp_b5.blocks["B5"]
    assert len(plans) == len(CELLS) * len(b5.presets) * b5.chains_per_cell * len(b5.targets) == 75
    assert len({p.chain_id for p in plans}) == 75
    again = plan_adaptive(exp_b5, "B5", corpus=corpus, carriers=carriers, seed=1)
    assert [p.chain_id for p in plans] == [p.chain_id for p in again]
    assert {(p.channel, p.technique, p.goal) for p in plans} == {tuple(c) for c in CELLS}


def test_plan_adaptive_tu_choi_khi_chua_chon_o(tmp_path):
    cfg = tmp_path / "experiment.yaml"
    cfg.write_text(_config_b5_cells_null(), encoding="utf-8")
    with pytest.raises(AttackRunnerError, match="chưa điền"):
        plan_adaptive(load_experiment(cfg), "B5", corpus=load_corpus(), carriers=load_carriers(),
                      seed=1)


def _d(cell, best_s, off_s):
    return DsrStat(cell, {"d1_only": (best_s, 10), "d2_only": (10, 10)}, (off_s, 10))


def test_s_adp_hoa_dsr_phan_dinh_bang_asr_off():
    stats = [_d(("K1", "T1", "G1"), 0, 9), _d(("K1", "T2", "G1"), 0, 5), _d(("K1", "T3", "G1"), 5, 9)]
    chosen, short = select_s_adp(stats, min_dsr_blind=0.3, max_cells=2)
    assert [c.cell for c in chosen] == [("K1", "T1", "G1"), ("K1", "T2", "G1")]
    assert not short


def test_s_adp_hoa_ca_hai_khoa_bao_loi():
    stats = [_d(("K1", "T1", "G1"), 0, 9), _d(("K1", "T2", "G1"), 0, 9), _d(("K1", "T3", "G1"), 0, 9)]
    with pytest.raises(CellSelectError, match="hòa"):
        select_s_adp(stats, min_dsr_blind=0.3, max_cells=2)
