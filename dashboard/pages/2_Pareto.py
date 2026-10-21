"""Trang 2 — biểu đồ đánh đổi Pareto an toàn/hữu dụng (STT-58).

Ảnh tĩnh do notebook phân tích xuất ra `results/figures/pareto*` — dashboard không vẽ lại, để số
trên hình luôn là số của notebook đã đưa vào báo cáo.
"""

from datetime import datetime

import streamlit as st

import tracedata as td

st.set_page_config(page_title="Pareto", layout="wide")
st.title("Đánh đổi an toàn / hữu dụng (Pareto)")

figures = td.list_figures()
if not figures:
    st.info(
        f"Chưa có ảnh `pareto*` ({', '.join(td.FIGURE_SUFFIXES)}) trong "
        f"`{td.store_label(td.FIGURES_DIR)}`. Notebook phân tích xuất ảnh vào thư mục này."
    )
    st.stop()

for fig in figures:
    mtime = datetime.fromtimestamp(fig.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    st.subheader(fig.stem)
    if fig.suffix.lower() == ".svg":
        st.image(fig.read_text(encoding="utf-8"), width="stretch")
    else:
        st.image(str(fig), width="stretch")
    st.caption(f"`{td.store_label(fig)}` · cập nhật {mtime}")
