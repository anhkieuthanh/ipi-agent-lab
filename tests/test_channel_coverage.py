"""Test cho scripts/channel_coverage.py — bảng phủ kênh và chỉ tiêu ≥80% (STT-41, taxonomy 2.3)."""

from __future__ import annotations

import copy

from channel_coverage import coverage, main, write_csv

from attack.payloads.render import load_render_config

CFG = load_render_config()


def _p(pid: str, code: str, channels: list[str]) -> dict:
    """Payload tối giản chỉ đủ cho hàm phủ (render + đếm kỹ thuật), không qua validator."""
    return {
        "id": pid,
        "technique": {"code": code, "template": "X: {INSTRUCTION}"},
        "goal": "G2",
        "goal_binding": {"tool": "create_ticket", "instruction_vi": "chi thi", "instruction_en": "do"},
        "channels": channels,
        "lang": "vi",
    }


def test_denominator_drops_architecturally_excluded_cells():
    # T4 chỉ khai K1+K2b; corpus hai kỹ thuật T4, T5.
    items = [_p("a", "T4", ["K1", "K2b"]), _p("b", "T5", ["K1", "K2a", "K2b"])]
    out = coverage(items, cfg=CFG)
    k2a = next(s for s in out["summaries"] if s["subchannel"] == "K2a")
    assert k2a["denom_matrix"] == 1 and k2a["denom_raw"] == 2   # T4 loại khỏi mẫu số ma trận
    assert k2a["covered"] == 1 and k2a["passed"] == 1


def test_technique_covered_needs_build_on_both_k1_and_sub():
    # T1 chỉ khai K1 (không K2a) → không phủ K2a dù có mặt corpus.
    items = [_p("a", "T1", ["K1"]), _p("b", "T2", ["K1", "K2a"])]
    out = coverage(items, cfg=CFG)
    k2a = next(s for s in out["summaries"] if s["subchannel"] == "K2a")
    assert "T1" not in k2a["covered_techniques"] and "T2" in k2a["covered_techniques"]
    assert k2a["ratio_matrix"] == 0.5 and k2a["passed"] == 0     # 1/2 < 0.8


def test_over_limit_payload_not_counted_buildable():
    small = copy.deepcopy(CFG)
    small["channels"]["K2a"]["max_payload_chars"] = 3   # mọi payload vượt
    items = [_p("a", "T1", ["K1", "K2a"])]
    out = coverage(items, cfg=small)
    row = next(r for r in out["rows"] if r["subchannel"] == "K2a" and r["technique"] == "T1")
    assert row["n_sub"] == 0 and row["covered"] == 0


def test_main_on_real_corpus_passes_and_writes_csv(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "K2a" in out and "K2b" in out and "ĐẠT" in out
    csv_path = __import__("pathlib").Path(CFG["coverage"]["output"])
    from channel_coverage import ROOT
    assert (ROOT / csv_path).exists()


def test_csv_has_summary_and_per_technique_blocks(tmp_path):
    items = [_p("a", "T1", ["K1", "K2a", "K2b"])]
    dest = tmp_path / "cov.csv"
    write_csv(coverage(items, cfg=CFG), dest)
    text = dest.read_text(encoding="utf-8")
    assert "# summary" in text and "# per_technique" in text and "ratio_matrix" in text


def test_coverage_requires_valid_schema_via_main(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("- id: x\n", encoding="utf-8")
    assert main(["--payloads", str(bad)]) == 1
    assert "sai schema" in capsys.readouterr().out
