"""Dashboard Streamlit — trang chủ (STT-58).

Bốn trang trong `dashboard/pages/`: bảng ASR có bộ lọc · Pareto (ảnh tĩnh từ notebook) · trace
viewer · công tắc D1–D4. Mọi trang đọc trực tiếp trace store SQLite của `obs.trace` (chế độ chỉ
đọc): biến `TRACES_DB` và mọi store dưới `results/`. Lớp dữ liệu ở `tracedata.py`.

Chạy: `uv run streamlit run dashboard/app.py` hoặc `make dashboard`.
"""

import streamlit as st

import tracedata as td
import ui

st.set_page_config(page_title="ipi-agent-lab", layout="wide")
st.title("ipi-agent-lab")
st.caption("Đánh giá và phòng chống tấn công tiêm nhiễm gián tiếp trên agent RAG + MCP")

paths = ui.sidebar_stores()
if not paths:
    st.info("Chưa có trace store — chạy thực nghiệm trước, hoặc đặt biến `TRACES_DB`.")
    st.stop()

df = ui.runs(paths)
attack = df[df["run_kind"] == "attack"]
benign = df[df["run_kind"] == "benign"]

c = st.columns(5)
c[0].metric("Run", len(df))
c[1].metric("Run tấn công", len(attack))
c[2].metric("Run lành tính", len(benign))
c[3].metric("parse_error (loại khỏi N)", int(df["parse_error"].sum()))
c[4].metric("Lô (batch)", df["batch_id"].nunique())

st.subheader("Theo lô")
summary = (
    df.groupby(["store", "batch_id", "run_kind", "target_id", "preset"], dropna=False)
    .size()
    .rename("runs")
    .reset_index()
)
st.dataframe(summary, hide_index=True, width="stretch")

st.subheader("Nguyên nhân chặn")
st.caption(
    "`blocked_by` tách ba tác nhân — model tự từ chối không tính là phòng thủ chặn "
    "(quy tắc cứng #8)."
)
blocked = df[df["outcome"] == "blocked"]
st.dataframe(
    blocked.groupby(["run_kind", "target_id", "preset", "blocked_by"]).size().rename("runs")
    .reset_index(),
    hide_index=True,
    width="stretch",
)

st.markdown(
    "**Trang:** 1 · Bảng ASR có bộ lọc — 2 · Pareto an toàn/hữu dụng — "
    "3 · Trace viewer — 4 · Công tắc D1–D4"
)
st.caption(f"Cấu hình phòng thủ: `{td.store_label(td.DEFENSES_PATH)}`")
