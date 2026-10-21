"""Trang 1 — bảng ASR có bộ lọc (STT-58).

ASR_e2e, ASR_cond theo ô, cùng định nghĩa `obs.trace.ASR_SQL`; Wilson 95%; DSR = 1 − ASR_e2e ở ô
bật phòng thủ; phân rã `blocked_by` thành defense · model_refusal · harness.
"""

import streamlit as st

import tracedata as td
import ui

st.set_page_config(page_title="Bảng ASR", layout="wide")
st.title("Bảng ASR")

paths = ui.sidebar_stores()
if not paths:
    st.stop()
df = ui.runs(paths)
attack = df[df["run_kind"] == "attack"]
if attack.empty:
    st.info("Store đang chọn chưa có run tấn công (`run_kind = attack`).")
    st.stop()

with st.expander("Bộ lọc", expanded=True):
    picked = ui.filters(attack, td.FILTER_COLUMNS, key="asr")
view = td.filter_runs(attack, picked)

group_cols = [c for c in td.FILTER_COLUMNS if c not in ("outcome", "blocked_by")]
by = st.multiselect(
    "Nhóm theo", group_cols, default=["target_id", "preset", "channel", "technique", "goal"],
    help="Mỗi dòng là một ô của ma trận theo các cột chọn.",
)
if not by:
    st.warning("Chọn ít nhất một cột để nhóm.")
    st.stop()

table = td.asr_table(view, by)
st.caption(
    f"{len(view)} run tấn công sau lọc · {len(table)} ô · `n` đã loại parse_error · "
    "`asr_cond` = s / d (d = run delivered)"
)
pct_cols = ["asr_e2e", "asr_e2e_lo", "asr_e2e_hi", "asr_cond", "dsr"]
st.dataframe(
    table,
    hide_index=True,
    width="stretch",
    column_config={
        c: st.column_config.NumberColumn(c, format="percent") for c in pct_cols
    } | {
        "asr_e2e": st.column_config.ProgressColumn(
            "asr_e2e", min_value=0.0, max_value=1.0, format="percent"
        ),
    },
)
st.download_button(
    "Tải CSV", table.to_csv(index=False).encode("utf-8"), "asr_table.csv", "text/csv"
)

n_excl = int(view["parse_error"].sum())
if n_excl:
    st.caption(f"{n_excl} run parse_error bị loại khỏi mẫu — xem trace viewer để rà.")
