"""Trang 3 — trace viewer (STT-58).

Một run: nhãn thí nghiệm, kết quả chấm, rồi từng bước tô màu — đỏ: bước bị chặn (defense /
harness), tím: model từ chối, cam viền: phòng thủ biến đổi nội dung (transform/flag, không phải
chặn). Viền đỏ đậm: sự kiện chặn sớm nhất — nguồn của `blocked_by` (Trace schema mục 4.3), tính
bằng đúng hàm của scorer. Đoạn tô cam nhạt: vị trí payload; xanh: canary của run.

Mọi văn bản trong trace là dữ liệu không tin cậy — được escape HTML trước khi hiển thị.
"""

from pathlib import Path

import streamlit as st

import tracedata as td
import ui

st.set_page_config(page_title="Trace viewer", layout="wide")
st.title("Trace viewer")
st.markdown(ui.CSS, unsafe_allow_html=True)

paths = ui.sidebar_stores()
if not paths:
    st.stop()
df = ui.runs(paths)

with st.expander("Bộ lọc run", expanded=True):
    kind = st.radio("Loại run", ["attack", "benign"], horizontal=True)
    pool = df[df["run_kind"] == kind]
    picked = ui.filters(pool, td.FILTER_COLUMNS, key="trace")
    pool = td.filter_runs(pool, picked)
if pool.empty:
    st.info("Không có run nào khớp bộ lọc.")
    st.stop()


def _label(r) -> str:
    task = r["carrier_task_id"] or r["benign_query_id"] or ""
    parts = [r["target_id"], r["preset"], task, r["technique"], r["channel"], r["goal"]]
    tag = " · ".join(str(p) for p in parts if p)
    return f"{r['run_id'][:10]} · {tag} → {r['outcome'] or 'parse_error'}"


labels = {_label(r): i for i, r in pool.iterrows()}
choice = st.selectbox(f"Run ({len(pool)})", list(labels))
run = pool.loc[labels[choice]]
store_path = next(p for p in paths if td.store_label(Path(p)) == run["store"])

# --- Đầu run ---------------------------------------------------------------
c = st.columns(3)
c[0].metric("outcome", run["outcome"] or "∅")
c[1].metric("blocked_by", run["blocked_by"] or "∅")
c[2].metric("delivered", "∅" if run["delivered"] is None else str(bool(run["delivered"])))
c = st.columns(3)
c[0].metric("Bước", int(run["n_steps"]))
c[1].metric("Token vào/ra", f"{run['tokens_in']}/{run['tokens_out']}")
c[2].metric("Độ trễ", f"{run['latency_ms']} ms")
hits = [g for g in ("g1", "g2", "g3") if run[f"{g}_hit"]]
st.caption(
    f"Store `{run['store']}` · batch `{run['batch_id']}` · model `{run['model_id']}` "
    f"(phục vụ: `{run['response_model']}`) · harness `{run['harness']}` "
    f"{run['harness_version']} · phòng thủ `{run['preset']}` ({run['enabled']}) · "
    f"goal đạt: {', '.join(hits).upper() or 'không'}"
    + (f" · g1_channel `{run['g1_channel']}`" if run["g1_channel"] else "")
    + (f" · g2_severity `{run['g2_severity']}`" if run["g2_severity"] else "")
)
if run["parse_error"]:
    st.error(f"parse_error: {run['parse_error_reason']}")

ui.render_trace(store_path, run)
