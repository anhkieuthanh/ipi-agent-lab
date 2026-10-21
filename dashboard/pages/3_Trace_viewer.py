"""Trang 3 — trace viewer (STT-58).

Một run: nhãn thí nghiệm, kết quả chấm, rồi từng bước tô màu — đỏ: bước bị chặn (defense /
harness), tím: model từ chối, cam viền: phòng thủ biến đổi nội dung (transform/flag, không phải
chặn). Viền đỏ đậm: sự kiện chặn sớm nhất — nguồn của `blocked_by` (Trace schema mục 4.3), tính
bằng đúng hàm của scorer. Đoạn tô cam nhạt: vị trí payload; xanh: canary của run.

Mọi văn bản trong trace là dữ liệu không tin cậy — được escape HTML trước khi hiển thị.
"""

import html
import json
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

catalog = td.load_payload_catalog()
payload = catalog.get(run["payload_id"]) if run["payload_id"] else None
needles = td.payload_needles(payload, run["lang"])
canaries = json.loads(run["run_canaries"] or "[]")
if run["payload_id"]:
    with st.expander(f"Payload `{run['payload_id']}`", expanded=False):
        if payload is None:
            st.warning("Không thấy payload này trong kho payload — không định vị được trong bước.")
        else:
            st.json(payload, expanded=False)

# --- Các bước --------------------------------------------------------------
steps = td.load_steps(store_path, run["run_id"])
views = td.classify_steps(
    steps, final_answer=run["final_answer"], needles=needles, canaries=canaries
)
if run["payload_id"]:
    located = [v.step.step_idx for v in views if v.payload_fields]
    if located:
        st.success(f"Payload định vị được ở bước {', '.join(map(str, located))}.")
    elif run["channel"] == "K2a":
        st.info("Kênh K2a: payload nằm trong mô tả tool, không xuất hiện trong nội dung bước.")
    else:
        st.warning(
            "Không định vị được payload trong bước — payload có thể đã bị che giấu "
            f"(obfuscation `{run['obfuscation']}`), bị D2 lọc, hoặc không được truy hồi."
        )

st.markdown(
    '<span class="badge block">chặn</span><span class="badge decisive">quyết định</span>'
    '<span class="badge refusal">model từ chối</span>'
    '<span class="badge transform">biến đổi</span><span class="badge payload">payload</span>'
    '<span class="badge canary">canary</span>',
    unsafe_allow_html=True,
)

for v in views:
    s = v.step
    classes = ["step"]
    badges = [f'<span class="badge">#{s.step_idx} {html.escape(s.kind)}</span>']
    if v.blocking:
        classes.append("block")
        badges.append('<span class="badge block">chặn</span>')
    if v.refusal:
        classes.append("refusal")
        badges.append('<span class="badge refusal">model từ chối</span>')
    if v.transforming:
        classes.append("transform")
        badges.append('<span class="badge transform">biến đổi</span>')
    if v.decisive:
        classes.append("decisive")
        badges.append('<span class="badge decisive">quyết định blocked_by</span>')
    if v.payload_fields:
        badges.append('<span class="badge payload">payload</span>')
    if v.canary_fields:
        badges.append('<span class="badge canary">canary</span>')
    head = " ".join(badges)
    if s.tool_name:
        head += f" <code>{html.escape(s.tool_name)}</code>"
    meta = [f"{k} {getattr(s, k)}" for k in ("finish_reason", "latency_ms") if getattr(s, k)]
    if meta:
        head += f" <small>{html.escape(' · '.join(meta))}</small>"

    body = []
    for f in td.STEP_TEXT_FIELDS:
        text = getattr(s, f)
        if not text:
            continue
        marked = td.highlight(
            text,
            {"canary": td.find_spans(text, canaries), "payload": td.find_spans(text, needles)},
        )
        body.append(f"<b>{f}</b><pre>{marked}</pre>")
    for hit in v.hits:
        body.append(
            f"<small>hit [{td.hit_source(hit)}] "
            f"{html.escape(json.dumps(hit, ensure_ascii=False))}</small><br>"
        )
    for e in v.events:
        body.append(f"<small>sự kiện chặn: {html.escape(e)}</small><br>")
    st.markdown(
        f'<div class="{" ".join(classes)}"><div>{head}</div>{"".join(body)}</div>',
        unsafe_allow_html=True,
    )

st.subheader("final_answer")
st.markdown(
    f'<div class="step"><pre>'
    f'{td.highlight(run["final_answer"], {"canary": td.find_spans(run["final_answer"], canaries), "payload": td.find_spans(run["final_answer"], needles)})}'
    f"</pre></div>",
    unsafe_allow_html=True,
)
