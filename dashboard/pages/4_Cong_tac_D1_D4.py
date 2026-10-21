"""Trang 4 — công tắc bật/tắt D1–D4 (STT-58).

Bật/tắt từng cơ chế → trang đổi ngay sang số đo của đúng tổ hợp đó trong trace, đặt cạnh cấu hình
`off`: ASR_e2e (run tấn công) và USR, FRR (run lành tính). Kèm tham số hiệu lực đọc từ
`config/defenses.yaml` sau `preset_overrides`.

Công tắc KHÔNG ghi `defenses.yaml` — file đó là hợp đồng của ma trận (quy tắc cứng #4). Chạy agent
trực tiếp từ trang này cần `defense.pipeline` (STT-55); trang tự báo khi module đã có.
"""

import importlib.util

import streamlit as st
import yaml

import tracedata as td
import ui

st.set_page_config(page_title="Công tắc D1–D4", layout="wide")
st.title("Công tắc D1–D4")

cfg = td.load_defenses()
names = {
    "D1": "Spotlighting",
    "D2": "Lọc đầu vào",
    "D3": "Chính sách tool",
    "D4": "Lọc đầu ra (egress)",
}
cols = st.columns(4)
toggled = [
    code for i, code in enumerate(td.DEFENSE_KEYS)
    if cols[i].toggle(f"{code} · {names[code]}", key=f"toggle:{code}")
]
enabled = ",".join(toggled) or "-"
matches = td.presets_for(toggled, cfg)
if matches:
    st.success(f"Tổ hợp ứng preset: {', '.join(f'`{m}`' for m in matches)}")
else:
    st.warning("Tổ hợp này không có preset trong `defenses.yaml` — ma trận không chạy nó.")

paths = ui.sidebar_stores()
if paths:
    df = ui.runs(paths)
    by = st.radio("So theo", ["target_id", "channel", "technique", "goal"], horizontal=True)
    table = td.compare_with_off(df, enabled, by=by)
    if table.empty:
        st.info("Trace đang chọn không có run nào với tổ hợp này hoặc với `off`.")
    else:
        if not toggled:
            st.caption("Đang tắt hết — bảng chỉ có cấu hình `off`.")
        elif not (table["preset"] != td.OFF).any():
            st.info("Chưa có run nào với tổ hợp này — bảng chỉ có cấu hình `off`.")
        pct = ["asr_e2e", "asr_e2e_lo", "asr_e2e_hi", "usr", "frr"]
        st.dataframe(
            table,
            hide_index=True,
            width="stretch",
            column_config={c: st.column_config.NumberColumn(c, format="percent") for c in pct},
        )
        st.caption(
            "ASR_e2e kèm Wilson 95%, đã loại parse_error. FRR = run lành tính bị D1–D4 chặn — "
            "model tự từ chối không tính vào FRR (quy tắc cứng #8)."
        )

st.subheader("Tham số hiệu lực")
if not toggled:
    st.caption("Bật một cơ chế để xem tham số.")
preset = matches[0] if len(matches) == 1 else None
if len(matches) > 1:
    preset = st.radio("Preset (khác nhau ở preset_overrides)", matches, horizontal=True)
for code in toggled:
    with st.expander(f"{code} · `{td.DEFENSE_KEYS[code]}`"):
        st.code(
            yaml.safe_dump(
                td.effective_params(code, preset, cfg), allow_unicode=True, sort_keys=False
            ),
            language="yaml",
        )

st.subheader("Chạy trực tiếp")
if importlib.util.find_spec("defense.pipeline") is None:
    st.info(
        "Chưa có `defense.pipeline` (STT-55) — trang hiện so sánh trên trace đã ghi. "
        "Chạy agent với tổ hợp đang bật sẽ nối vào đây khi pipeline có."
    )
else:
    st.info("`defense.pipeline` đã có — nối runner một ca vào trang này là việc kế tiếp.")
