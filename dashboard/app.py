"""Dashboard Streamlit — trang chủ (STT-58).

Khung tối thiểu để service `dashboard` trong docker-compose khởi động được. Bốn trang
(bảng ASR · Pareto · trace viewer · công tắc D1–D4) thêm vào `dashboard/pages/` ở STT-58,
đọc trực tiếp traces.db.
"""

import os
from pathlib import Path

import streamlit as st

TRACES_DB = Path(os.environ.get("TRACES_DB", "data/traces.db"))

st.set_page_config(page_title="ipi-agent-lab", layout="wide")
st.title("ipi-agent-lab")
st.caption("Đánh giá và phòng chống tấn công tiêm nhiễm gián tiếp trên agent RAG + MCP")

if TRACES_DB.exists():
    st.success(f"Đã thấy trace store: `{TRACES_DB}`")
else:
    st.info(f"Chưa có trace store tại `{TRACES_DB}` — chạy thực nghiệm trước.")
