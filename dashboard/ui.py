"""Phần streamlit dùng chung của bốn trang (STT-58): chọn store, nạp có cache, bộ lọc, CSS."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

import tracedata as td

SELECTED_KEY = "selected_stores"

CSS = """
<style>
.step {border-left: 6px solid #9aa0a6; padding: .4rem .8rem; margin: .5rem 0;
       border-radius: 4px; background: rgba(127,127,127,.06);}
.step.block {border-left-color: #d93025; background: rgba(217,48,37,.10);}
.step.refusal {border-left-color: #8e44ad; background: rgba(142,68,173,.10);}
.step.transform {border-left-color: #f29900;}
.step.decisive {outline: 2px solid #d93025;}
.step pre {white-space: pre-wrap; word-break: break-word; margin: .3rem 0 0;
           font-size: .82rem;}
.badge {display: inline-block; padding: 0 .45rem; margin-right: .3rem; border-radius: 3px;
        font-size: .75rem; font-weight: 600; color: #fff; background: #5f6368;}
.badge.block {background: #d93025;} .badge.refusal {background: #8e44ad;}
.badge.transform {background: #f29900;} .badge.payload {background: #e8710a;}
.badge.canary {background: #1a73e8;} .badge.decisive {background: #a50e0e;}
mark.hl-canary {background: #aecbfa; color: inherit;}
mark.hl-payload {background: #fdc69c; color: inherit;}
</style>
"""


@st.cache_data(show_spinner=False)
def _stores_cached(_token: int) -> list[str]:
    return [str(p) for p in td.discover_stores()]


def stores() -> list[str]:
    # Nút "Quét lại" tăng token để bỏ cache khi có lô chạy mới.
    return _stores_cached(st.session_state.get("_scan", 0))


@st.cache_data(show_spinner="Đang đọc trace…")
def _runs_cached(paths: tuple[str, ...], mtimes: tuple[float, ...]) -> pd.DataFrame:
    presets = td.runnable_presets(td.load_defenses())
    return td.load_runs(paths, presets)


def runs(paths: list[str]) -> pd.DataFrame:
    mtimes = tuple(Path(p).stat().st_mtime for p in paths)
    return _runs_cached(tuple(paths), mtimes)


def sidebar_stores() -> list[str]:
    """Chọn store ở sidebar; lựa chọn giữ qua các trang bằng `session_state`."""
    found = stores()
    with st.sidebar:
        st.subheader("Trace store")
        if st.button("Quét lại", help="Tìm lại store dưới results/ và biến TRACES_DB"):
            st.session_state["_scan"] = st.session_state.get("_scan", 0) + 1
            st.rerun()
        if not found:
            st.info("Chưa tìm thấy trace store nào (results/**.sqlite|.db hoặc TRACES_DB).")
            return []
        labels = {td.store_label(Path(p)): p for p in found}
        default = [k for k in st.session_state.get(SELECTED_KEY, []) if k in labels]
        picked = st.multiselect(
            "Store đang xem", list(labels), default=default or list(labels)[:1],
            help="Chọn nhiều store để gộp nhiều lô.",
        )
        st.session_state[SELECTED_KEY] = picked
        st.caption("Dashboard chỉ đọc (SQLite mode=ro).")
    return [labels[k] for k in picked]


def filters(df: pd.DataFrame, columns: tuple[str, ...], *, key: str) -> dict[str, list[str]]:
    """Một multiselect mỗi cột có > 1 giá trị; trả `{cột: giá trị chọn}`."""
    picked: dict[str, list[str]] = {}
    shown = [c for c in columns if c in df and len(td.options(df, c)) > 1]
    if not shown:
        return picked
    grid = st.columns(min(4, len(shown)))
    for i, col in enumerate(shown):
        with grid[i % len(grid)]:
            picked[col] = st.multiselect(col, td.options(df, col), key=f"{key}:{col}")
    return picked


def pct(x: float | None) -> str:
    return "—" if x is None or pd.isna(x) else f"{100 * x:.1f}%"
