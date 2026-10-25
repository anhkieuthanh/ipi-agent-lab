"""Trang 0 — demo trực tiếp (STT-82).

Chọn một kịch bản tấn công dựng sẵn, chạy thật trên một model với nhiều preset phòng thủ, rồi so
song song: tấn công thành công hay bị chặn, ai chặn, agent đã gọi tool gì. Chạy được khi dashboard
khởi động bằng `make demo` (biến `DEMO_LIVE=1`, trên máy host, có `.env`); dashboard trong
container chỉ xem lại các lượt demo đã chạy.

Mọi văn bản trong trace là dữ liệu không tin cậy — trace hiển thị qua `ui.render_trace`, đã escape.
"""

import html
import os

import streamlit as st

import demo
import tracedata as td
import ui

st.set_page_config(page_title="Demo trực tiếp", layout="wide")
st.markdown(ui.CSS, unsafe_allow_html=True)
st.markdown(
    """
<style>
.verdict {border-radius: 8px; padding: .8rem 1rem; margin-bottom: .6rem; color: #fff;}
.verdict h3 {margin: 0; color: #fff; font-size: 1.15rem;}
.verdict p {margin: .3rem 0 0; font-size: .9rem;}
.verdict.attack {background: #c5221f;} .verdict.defense {background: #188038;}
.verdict.refusal {background: #8e44ad;} .verdict.neutral {background: #5f6368;}
.scenario {border-left: 6px solid #e8710a; padding: .5rem .9rem; margin: .4rem 0;
           background: rgba(232,113,10,.08); border-radius: 4px;}
</style>
""",
    unsafe_allow_html=True,
)
st.title("Demo trực tiếp — tấn công tiêm nhiễm gián tiếp")
LIVE = os.getenv("DEMO_LIVE") == "1"

# --- Kịch bản --------------------------------------------------------------
titles = {s.title: s for s in demo.SCENARIOS}
s = titles[st.selectbox("Kịch bản", list(titles))]
st.markdown(f'<div class="scenario">{html.escape(s.story)}</div>', unsafe_allow_html=True)

c = st.columns(2)
with c[0]:
    st.markdown("**Nhân viên hỏi agent** (tác vụ hợp lệ)")
    st.info(demo.carrier_query(s.carrier_task_id))
    st.caption(f"Tác vụ chở `{s.carrier_task_id}` · kênh `{s.channel}` · kỹ thuật `{s.technique}`")
with c[1]:
    st.markdown("**Payload kẻ tấn công cài vào dữ liệu** (nhân viên không thấy)")
    st.code(demo.payload_text(s), language=None, wrap_lines=True)
    st.caption(f"Payload `{s.payload_id}` · mục tiêu `{s.goal}`: {demo.GOAL_TEXT[s.goal]}")

# --- Chạy ------------------------------------------------------------------
presets_all = list(td.runnable_presets(td.load_defenses()))
active, variants = demo.prompt_variants()
c = st.columns([1, 1, 2, 1])
target = c[0].selectbox("Model đích", ["A3", "A2", "A1"], help="A3 rẻ nhất, A1 đắt nhất")
variant = c[1].selectbox(
    "System prompt", variants, index=variants.index(active),
    help=f"Biến thể trong config/prompts.yaml, xếp từ thận trọng tới cả tin. Lô thực nghiệm dùng "
    f"`{active}`.",
)
presets = c[2].multiselect(
    "Cấu hình phòng thủ so sánh", presets_all, default=list(demo.DEFAULT_PRESETS)
)
run_clicked = c[3].button(
    "▶ Chạy tấn công", type="primary", disabled=not (LIVE and presets), width="stretch"
)
if not LIVE:
    st.caption("Chế độ xem lại. Để chạy trực tiếp: `make demo` rồi mở http://localhost:8502.")

if run_clicked:
    with st.status(f"Đang chạy {len(presets)} lượt trên {target}…", expanded=True) as status:
        def progress(preset: str, event: str) -> None:
            if event == "start":
                st.write(f"⏳ `{preset}` — agent đang xử lý tác vụ…")
            else:
                st.write(f"✅ `{preset}` — đã chấm xong")

        try:
            result = demo.run_demo(
                s, target=target, presets=presets, prompt_variant=variant,
                on_progress=progress,
            )
        except Exception as e:  # noqa: BLE001 — báo lỗi lên màn hình demo thay vì vỡ trang
            status.update(label="Không chạy được", state="error")
            st.error(f"{type(e).__name__}: {e}")
            st.stop()
        status.update(
            label=f"Xong · {result.spent_usd:.4f} USD · ngân sách {result.budget_status}",
            state="complete",
            expanded=False,
        )
    st.session_state["demo_batch"] = result.batch_id

# --- Kết quả ---------------------------------------------------------------
if not demo.DEMO_STORE.is_file():
    st.info("Chưa có lượt demo nào.")
    st.stop()
df = ui.runs([str(demo.DEMO_STORE)])
df = df[df["batch_id"].str.startswith("demo-")]
if df.empty:
    st.info("Chưa có lượt demo nào.")
    st.stop()

batches = sorted(df["batch_id"].unique(), reverse=True)
default = st.session_state.get("demo_batch")
batch = st.selectbox(
    "Lượt demo", batches, index=batches.index(default) if default in batches else 0
)
runs = df[df["batch_id"] == batch].sort_values("created_at")
first = runs.iloc[0]
st.subheader("Kết quả so sánh")
st.caption(
    f"Model `{first['model_id']}` · kênh `{first['channel']}` · kỹ thuật `{first['technique']}` · "
    f"mục tiêu `{first['goal']}` · payload `{first['payload_id']}` · tác vụ `{first['carrier_task_id']}`"
    f" · system prompt `{demo.variant_of(first['env_hash'], first['harness_version']) or '?'}`"
)

cols = st.columns(len(runs))
for col, (_, run) in zip(cols, runs.iterrows(), strict=True):
    v = demo.verdict(run)
    with col:
        st.markdown(f"**Phòng thủ: `{run['preset']}`**")
        st.markdown(
            f'<div class="verdict {v.tone}"><h3>{html.escape(v.label)}</h3>'
            f"<p>{html.escape(v.detail)}</p></div>",
            unsafe_allow_html=True,
        )
        m = st.columns(3)
        m[0].metric("Bước", int(run["n_steps"]))
        m[1].metric("Token", f"{(run['tokens_in'] + run['tokens_out']) / 1000:.1f}k")
        m[2].metric("Thời gian", f"{run['latency_ms'] / 1000:.0f} s")
        st.caption(
            f"blocked_by `{run['blocked_by'] or '∅'}` · G1 {'✔' if run['g1_hit'] else '✘'} · "
            f"G2 {'✔' if run['g2_hit'] else '✘'} · G3 {'✔' if run['g3_hit'] else '✘'} · "
            f"payload tới ngữ cảnh: {'có' if run['delivered'] else 'không'}"
        )
        st.markdown("**Tool agent đã gọi**")
        actions = demo.tool_actions(demo.DEMO_STORE, run["run_id"], run["payload_id"])
        if run["outcome"] == "success" and not any(a.follows_payload for a in actions):
            st.warning(
                "Scorer chấm thành công nhưng agent không gọi tool mà payload đòi — vi phạm có thể "
                "đến từ hành vi tự phát của agent, không do payload (Việc treo VT-16)."
            )
        if not actions:
            st.caption("Không gọi tool nào.")
        for a in actions:
            icon = "⛔ bị chặn" if a.blocked else "✅ đã chạy"
            tag = " · **làm theo payload**" if a.follows_payload else ""
            st.markdown(f"{icon} `{a.tool}`{tag}")
            st.caption(a.args[:240])

st.subheader("Agent đã làm gì — từng bước")
tabs = st.tabs([f"{r['preset']}" for _, r in runs.iterrows()])
for tab, (_, run) in zip(tabs, runs.iterrows(), strict=True):
    with tab:
        ui.render_trace(demo.DEMO_STORE, run)
