"""Nhãn upstream và tỉ lệ run theo upstream mỗi ô (VT-2, phần A3)."""

import pandas as pd
import pytest

from obs.trace import RunMeta, TraceRecorder, export_runs, open_store
from obs.upstream import EMPTY_LABEL, upstream_label, upstream_share


@pytest.mark.parametrize(
    ("raw", "label"),
    [
        ("glm-5.3-flash", "glm-5.3-flash"),
        ("  Z-AI/glm-5.3-flash ", "z-ai/glm-5.3-flash"),
        ("glm-5-3-flash", "glm-5-3-flash"),
        ("", EMPTY_LABEL),
        ("   ", EMPTY_LABEL),
        (None, EMPTY_LABEL),
    ],
)
def test_nhan_upstream_khong_gop_cac_dang(raw, label):
    assert upstream_label(raw) == label


def _store(models):
    engine = open_store()
    for i, (model, parse_error) in enumerate(models):
        meta = RunMeta(run_kind="attack", target_id="A3", model_id="glm-5.3-flash", batch_id="B1",
                       harness_version="t", env_hash="e", carrier_task_id="CT-01", technique="T1",
                       goal="G1", channel="K1", attacker_mode="blind", run_id=f"r{i}")
        with TraceRecorder(engine, meta) as rec:
            rec.step(kind="llm", llm_text="x", finish_reason="stop", response_model=model)
            if parse_error:
                rec.finish(parse_error=True, parse_error_reason="test")
            else:
                rec.finish(outcome="failed")
    return export_runs(engine)


def test_ti_le_theo_upstream_trong_o_bo_run_parse_error():
    df = _store([
        ("glm-5.3-flash", False),
        ("glm-5.3-flash", False),
        ("z-ai/glm-5.3-flash", False),
        ("", False),
        ("glm-5-3-flash", True),  # parse_error — không vào mẫu số N
    ])
    share = upstream_share(df)
    rows = {r.upstream: (r.n, r.n_cell, r.share, r.matches_model_id) for r in share.itertuples()}
    assert rows == {
        "glm-5.3-flash": (2, 4, 0.5, True),
        "z-ai/glm-5.3-flash": (1, 4, 0.25, False),
        EMPTY_LABEL: (1, 4, 0.25, False),
    }
    assert share["upstream"].iloc[0] == "glm-5.3-flash"  # nhãn nhiều run nhất đứng đầu ô


def test_moi_o_tinh_rieng():
    df = _store([("glm-5.3-flash", False), ("z-ai/glm-5.3-flash", False)])
    df.loc[1, "technique"] = "T2"
    share = upstream_share(df)
    assert list(share["share"]) == [1.0, 1.0] and list(share["n_cell"]) == [1, 1]


def test_thieu_cot_bao_loi():
    with pytest.raises(KeyError, match="response_model"):
        upstream_share(pd.DataFrame({"batch_id": []}), by=("batch_id",))


def test_khong_co_run_hop_le_tra_bang_rong():
    out = upstream_share(_store([("glm-5.3-flash", True)]))
    assert out.empty and "share" in out.columns
