"""Nhãn upstream phục vụ từng run và tỉ lệ run theo upstream mỗi ô (VT-2, phần A3).

Gateway phân tải A3 (`glm-5.3-flash`) qua nhiều nhà cung cấp: cùng request, trường `model` của response
có bốn dạng (`glm-5.3-flash`, `z-ai/glm-5.3-flash`, `glm-5-3-flash`, rỗng —
`results/smoke/probe_gateway_identity_20261013T024118Z.json`). Không ghim được upstream, nên đề tài
chấp nhận nguồn phương sai này và khai thành hạn chế; bù lại, mọi ô thí nghiệm báo cáo tỉ lệ run theo
upstream để người đọc thấy ô nào trộn nhiều upstream.

Nhãn lấy thẳng từ `runs.response_model` (cột recorder đã ghi), chỉ chuẩn hóa khoảng trắng và chữ
hoa. Không gộp các dạng lại với nhau: mỗi dạng là dấu vết của một đường phục vụ khác nhau, gộp là
xóa mất chính thứ cần báo cáo.

    df = export_runs(engine, target_id="A3")
    share = upstream_share(df)        # một dòng cho mỗi (ô, nhãn upstream)
"""

from __future__ import annotations

import pandas as pd

__all__ = ["CELL_KEYS", "EMPTY_LABEL", "upstream_label", "upstream_share"]

#: Khóa của một ô thí nghiệm — trùng `GROUP BY` của `obs.trace.ASR_SQL`.
CELL_KEYS = ("batch_id", "target_id", "defense_config", "channel", "technique", "goal")
#: Nhãn cho response không mang trường `model` (một trong bốn dạng đã quan sát).
EMPTY_LABEL = "<rỗng>"


def upstream_label(response_model: str | None) -> str:
    """Nhãn upstream của một run: `response_model` đã bỏ khoảng trắng hai đầu, chữ thường."""
    if response_model is None or pd.isna(response_model):
        return EMPTY_LABEL
    label = str(response_model).strip().lower()
    return label or EMPTY_LABEL


def upstream_share(runs: pd.DataFrame, by: tuple[str, ...] = CELL_KEYS) -> pd.DataFrame:
    """Số run và tỉ lệ theo nhãn upstream trong mỗi nhóm `by`.

    Cột ra: các cột `by`, `upstream`, `matches_model_id` (nhãn trùng `model_id` đã yêu cầu), `n`,
    `n_cell`, `share`. Chỉ đếm run hợp lệ (`parse_error = 0`), khớp mẫu số `N` của ASR.
    """
    missing = [c for c in (*by, "model_id", "response_model", "parse_error") if c not in runs]
    if missing:
        raise KeyError(f"thiếu cột {missing}")
    valid = runs[~runs["parse_error"].astype(bool)].copy()
    cols = [*by, "upstream", "matches_model_id", "n", "n_cell", "share"]
    if valid.empty:
        return pd.DataFrame(columns=cols)
    valid["upstream"] = valid["response_model"].map(upstream_label)
    valid["matches_model_id"] = valid["upstream"] == valid["model_id"].str.strip().str.lower()
    keys = list(by)
    out = (
        valid.groupby([*keys, "upstream", "matches_model_id"], dropna=False)
        .size()
        .reset_index(name="n")
    )
    out["n_cell"] = out.groupby(keys, dropna=False)["n"].transform("sum")
    out["share"] = out["n"] / out["n_cell"]
    return out.sort_values([*keys, "n"], ascending=[True] * len(keys) + [False]).reset_index(
        drop=True
    )[cols]
