"""Lớp dữ liệu console (STT-58) — hàm thuần, test được.

Dashboard chỉ ĐỌC trace store (mở SQLite chế độ `mode=ro`), không ghi trace, không sửa
`config/defenses.yaml`. Mọi phép chấm lấy từ nguồn đã có, không tính lại theo cách riêng:

- ASR theo ô: cùng ngữ nghĩa `obs.trace.ASR_SQL` (test giữ hai bên khớp nhau); Wilson 95% từ
  `eval.metrics.wilson`; USR từ `eval.metrics.utility_summary`.
- Sự kiện chặn của trace viewer: `eval.scorer._block_events` — đúng hàm scorer dùng để ghi
  `blocked_by` (Trace schema mục 4.3), nên màu "chặn" trên màn hình khớp nhãn trong `runs`.
- `blocked_by` luôn tách ba tác nhân defense · model_refusal · harness (quy tắc cứng #8).
"""

from __future__ import annotations

import html
import json
import os
import sqlite3
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from eval.metrics import utility_summary, wilson  # noqa: E402
from eval.scorer import ScorerConfig, _block_events  # noqa: E402
from obs.trace import BLOCKED_BY, HARNESS_HIT_PREFIX, Step  # noqa: E402

DEFENSES_PATH = ROOT / "config" / "defenses.yaml"
RESULTS_DIR = ROOT / "results"
FIGURES_DIR = RESULTS_DIR / "figures"
#: Nguồn payload để trace viewer định vị payload trong bước — gộp theo `id`.
PAYLOAD_SOURCES = (
    ROOT / "src" / "attack" / "payloads",
    ROOT / "data" / "payloads_imported",
    ROOT / "data" / "payloads_sample.json",
)
STORE_SUFFIXES = (".sqlite", ".db")
FIGURE_SUFFIXES = (".png", ".svg", ".jpg", ".jpeg")

#: Mã ngắn D1–D4 ↔ khóa khối trong `defenses.yaml`.
DEFENSE_KEYS = {
    "D1": "d1_spotlighting",
    "D2": "d2_input_sanitizer",
    "D3": "d3_tool_policy",
    "D4": "d4_egress_filter",
}
OFF = "off"
CUSTOM = "custom"
#: Đoạn cố định của template ngắn hơn ngưỡng này dễ khớp nhầm văn bản lành tính — bỏ.
MIN_NEEDLE_LEN = 12

# Cột nhãn lọc được ở bảng ASR và trace viewer.
FILTER_COLUMNS = (
    "store", "batch_id", "target_id", "preset", "channel", "technique", "goal",
    "attacker_mode", "lang", "obfuscation", "carrier_task_id", "outcome", "blocked_by",
)
ASR_KEYS = ("batch_id", "target_id", "defense_config", "channel", "technique", "goal")


# ---------------------------------------------------------------------------
# Trace store
# ---------------------------------------------------------------------------


def _connect(path: str | Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True)


def is_trace_store(path: str | Path) -> bool:
    """File SQLite có hai bảng `runs` + `steps` của `obs.trace`."""
    p = Path(path)
    if not p.is_file():
        return False
    try:
        with _connect(p) as conn:
            names = {
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
    except sqlite3.DatabaseError:
        return False
    return {"runs", "steps"} <= names


def discover_stores(
    results_dir: Path = RESULTS_DIR, extra: Iterable[str | Path] = ()
) -> list[Path]:
    """Store khai qua biến `TRACES_DB` (nếu có) trước, rồi mọi store dưới `results/`."""
    candidates: list[Path] = [Path(p) for p in extra]
    env = os.environ.get("TRACES_DB")
    if env:
        candidates.append(Path(env))
    if results_dir.is_dir():
        candidates += sorted(
            p for p in results_dir.rglob("*") if p.suffix in STORE_SUFFIXES
        )
    seen: set[Path] = set()
    out: list[Path] = []
    for p in candidates:
        key = p.resolve()
        if key not in seen and is_trace_store(p):
            seen.add(key)
            out.append(p)
    return out


def store_label(path: Path, root: Path = ROOT) -> str:
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)


def parse_defense_config(raw: str | None, presets: dict[str, list[str]] | None = None) -> dict:
    """`defense_config` JSON → `{"preset", "enabled"}`; `enabled` là mã D1–D4 đã sắp.

    Run cũ không ghi `preset` thì suy từ tập khối bật: khớp đúng một preset → tên preset, rỗng →
    `off`, còn lại → `custom`.
    """
    cfg = json.loads(raw) if raw else {}
    blocks = list(cfg.get("enabled", []))
    codes = sorted(code for code, key in DEFENSE_KEYS.items() if key in blocks)
    preset = cfg.get("preset")
    if not preset:
        if not blocks:
            preset = OFF
        else:
            hits = [n for n, b in (presets or {}).items() if sorted(b) == sorted(blocks)]
            preset = hits[0] if len(hits) == 1 else CUSTOM
    return {"preset": preset, "enabled": ",".join(codes) or "-"}


def load_runs(paths: Sequence[str | Path], presets: dict[str, list[str]] | None = None) -> pd.DataFrame:
    """Gộp bảng `runs` của nhiều store; thêm `store`, `preset`, `enabled` (D1–D4)."""
    frames = []
    for p in paths:
        with _connect(p) as conn:
            df = pd.read_sql_query("SELECT * FROM runs", conn)
        df.insert(0, "store", store_label(Path(p)))
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    parsed = df["defense_config"].map(lambda r: parse_defense_config(r, presets))
    df["preset"] = parsed.map(lambda d: d["preset"])
    df["enabled"] = parsed.map(lambda d: d["enabled"])
    bool_cols = ("parse_error", "g1_hit", "g2_hit", "g3_hit", "leak_attempted", "loop_flag")
    for col in bool_cols:
        df[col] = df[col].fillna(0).astype(bool)
    # NULL của SQLite đọc ra NaN (truthy) — trả về None như trong `obs.trace.Run`.
    for col in df.columns[df.isna().any()]:
        df[col] = df[col].astype(object).where(df[col].notna(), None)
    return df


def load_steps(path: str | Path, run_id: str) -> list[Step]:
    """Các bước của một run dưới dạng `obs.trace.Step` — kiểu scorer nhận."""
    with _connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM steps WHERE run_id = ? ORDER BY step_idx", (run_id,)
        ).fetchall()
    return [Step(**dict(r)) for r in rows]


def filter_runs(df: pd.DataFrame, selections: dict[str, Sequence[Any]]) -> pd.DataFrame:
    """Lọc theo cột; danh sách rỗng = không lọc cột đó. Giá trị NULL chọn được qua chuỗi "∅"."""
    mask = pd.Series(True, index=df.index)
    for col, values in selections.items():
        if not values:
            continue
        col_values = df[col].astype(object).where(df[col].notna(), "∅").astype(str)
        mask &= col_values.isin([str(v) for v in values])
    return df[mask]


def options(df: pd.DataFrame, col: str) -> list[str]:
    return sorted(df[col].astype(object).where(df[col].notna(), "∅").astype(str).unique())


# ---------------------------------------------------------------------------
# Bảng ASR (trang 1)
# ---------------------------------------------------------------------------


def asr_table(runs: pd.DataFrame, by: Sequence[str]) -> pd.DataFrame:
    """ASR theo ô, cùng định nghĩa `obs.trace.ASR_SQL`, kèm Wilson 95% và phân rã `blocked_by`.

    Chỉ run tấn công; mẫu số `n` loại `parse_error`. `asr_cond` chia cho số run `delivered`.
    `dsr = 1 − asr_e2e` chỉ có ở ô mà mọi run đều bật ít nhất một cơ chế D1–D4.
    """
    by = list(by)
    cols = [
        *by, "n_raw", "n_excl", "n", "s", "d", "asr_e2e", "asr_e2e_lo", "asr_e2e_hi",
        "asr_cond", *(f"blocked_{b}" for b in BLOCKED_BY), "dsr",
    ]
    attack = runs[runs["run_kind"] == "attack"]
    if attack.empty:
        return pd.DataFrame(columns=cols)
    rows = []
    for keys, cell in attack.groupby(by, sort=True, dropna=False):
        keys = keys if isinstance(keys, tuple) else (keys,)
        clean = cell[~cell["parse_error"]]
        n = len(clean)
        s = int((clean["outcome"] == "success").sum())
        d = int((clean["delivered"].fillna(0).astype(bool)).sum())
        lo, hi = wilson(s, n) if n else (None, None)
        asr_e2e = s / n if n else None
        defended = bool(len(cell)) and (cell["enabled"] != "-").all()
        row = dict(zip(by, keys, strict=True)) | {
            "n_raw": len(cell),
            "n_excl": len(cell) - n,
            "n": n,
            "s": s,
            "d": d,
            "asr_e2e": asr_e2e,
            "asr_e2e_lo": lo,
            "asr_e2e_hi": hi,
            "asr_cond": s / d if d else None,
            "dsr": 1 - asr_e2e if defended and asr_e2e is not None else None,
        }
        for b in BLOCKED_BY:
            row[f"blocked_{b}"] = int((clean["blocked_by"] == b).sum())
        rows.append(row)
    return pd.DataFrame(rows, columns=cols)


# ---------------------------------------------------------------------------
# Trace viewer (trang 3)
# ---------------------------------------------------------------------------


def load_payload_catalog(sources: Iterable[Path] = PAYLOAD_SOURCES) -> dict[str, dict]:
    """`{payload_id: payload}` từ mọi file JSON/YAML nguồn; id trùng thì file đầu thắng."""
    catalog: dict[str, dict] = {}
    for src in sources:
        if not src.exists():
            continue
        files = sorted(f for f in src.iterdir() if f.suffix in (".json", ".yaml", ".yml")) \
            if src.is_dir() else [src]
        for f in files:
            text = f.read_text(encoding="utf-8")
            data = json.loads(text) if f.suffix == ".json" else yaml.safe_load(text)
            items = data if isinstance(data, list) else (data or {}).get("payloads", [])
            for p in items:
                if isinstance(p, dict) and p.get("id"):
                    catalog.setdefault(p["id"], p)
    return catalog


def _template_fragments(template: str) -> list[str]:
    """Đoạn chữ cố định giữa các `{PLACEHOLDER}` của template."""
    out, buf, depth = [], [], 0
    for ch in template:
        if ch == "{":
            depth += 1
            out.append("".join(buf))
            buf = []
        elif ch == "}" and depth:
            depth -= 1
        elif not depth:
            buf.append(ch)
    out.append("".join(buf))
    return [f.strip() for f in out]


def payload_needles(payload: dict | None, lang: str | None = None) -> list[str]:
    """Chuỗi đặc trưng để tìm payload trong bước: văn bản payload, chỉ thị, đoạn cố định của
    template. Payload bị che giấu (base64, ký tự ẩn…) sẽ không khớp — viewer báo "không định vị"."""
    if not payload:
        return []
    needles: list[str] = []
    if isinstance(payload.get("payload"), str):
        needles.append(payload["payload"])
    lang = lang or payload.get("lang") or "vi"
    binding = payload.get("goal_binding") or {}
    for key in (f"instruction_{lang}", "instruction_vi", "instruction_en"):
        if binding.get(key):
            needles.append(binding[key])
            break
    if payload.get("goal_text"):
        needles.append(payload["goal_text"])
    technique = payload.get("technique")
    template = technique.get("template") if isinstance(technique, dict) else payload.get("template")
    if isinstance(template, str):
        needles += _template_fragments(template)
    uniq = dict.fromkeys(n.strip() for n in needles if n and len(n.strip()) >= MIN_NEEDLE_LEN)
    return sorted(uniq, key=len, reverse=True)


def find_spans(text: str | None, needles: Iterable[str]) -> list[tuple[int, int]]:
    """Mọi vị trí `[start, end)` của các needle trong `text` (phân biệt hoa thường)."""
    if not text:
        return []
    spans = []
    for n in needles:
        start = text.find(n)
        while start != -1:
            spans.append((start, start + len(n)))
            start = text.find(n, start + 1)
    return sorted(spans)


def highlight(text: str | None, marks: dict[str, list[tuple[int, int]]]) -> str:
    """HTML đã escape của `text`, bọc `<mark class="hl-<loại>">` quanh các đoạn đánh dấu.

    Nội dung trace là dữ liệu không tin cậy (payload tấn công) — mọi ký tự đều qua `html.escape`
    trước khi hiển thị. Chồng lấn: loại đứng trước trong `marks` thắng.
    """
    if not text:
        return ""
    label: list[str | None] = [None] * len(text)
    for kind, spans in reversed(list(marks.items())):
        for a, b in spans:
            for i in range(max(a, 0), min(b, len(text))):
                label[i] = kind
    out, i = [], 0
    while i < len(text):
        j = i
        while j < len(text) and label[j] == label[i]:
            j += 1
        chunk = html.escape(text[i:j])
        out.append(f'<mark class="hl-{label[i]}">{chunk}</mark>' if label[i] else chunk)
        i = j
    return "".join(out)


@dataclass
class StepView:
    """Một bước đã phân loại để tô màu."""

    step: Step
    hits: list[dict[str, Any]]
    blocking: bool = False      # có hit chặn (defense block/confirm, harness block)
    transforming: bool = False  # có hit transform/flag — làm thất bại, không "chặn"
    refusal: bool = False       # model từ chối (finish_reason hoặc cụm từ chối)
    decisive: bool = False      # sự kiện chặn sớm nhất = nguồn của `blocked_by`
    events: list[str] = field(default_factory=list)
    payload_fields: list[str] = field(default_factory=list)
    canary_fields: list[str] = field(default_factory=list)


STEP_TEXT_FIELDS = ("llm_text", "tool_args", "tool_result")


def classify_steps(
    steps: list[Step],
    *,
    final_answer: str | None,
    needles: Sequence[str] = (),
    canaries: Sequence[str] = (),
    scorer_cfg: ScorerConfig | None = None,
) -> list[StepView]:
    """Gắn cờ tô màu cho từng bước theo đúng quy tắc của scorer (Trace schema mục 4.2–4.3)."""
    cfg = scorer_cfg or ScorerConfig.load()
    final_answer = final_answer if isinstance(final_answer, str) else None
    events = _block_events(steps, final_answer, cfg) if steps else []
    by_idx: dict[int, list] = {}
    for e in events:
        by_idx.setdefault(e.step_idx, []).append(e)
    first = events[0] if events else None
    views = []
    for s in steps:
        hits = json.loads(s.defense_hits or "[]")
        v = StepView(step=s, hits=hits)
        for e in by_idx.get(s.step_idx, []):
            v.events.append(f"{e.agent}: {e.detail}")
            if e.agent == "model_refusal":
                v.refusal = True
            else:
                v.blocking = True
        v.decisive = first is not None and first.step_idx == s.step_idx
        v.transforming = any(h.get("action") in ("transform", "flag") for h in hits)
        for f in STEP_TEXT_FIELDS:
            value = getattr(s, f)
            if find_spans(value, needles):
                v.payload_fields.append(f)
            if find_spans(value, canaries):
                v.canary_fields.append(f)
        views.append(v)
    return views


def hit_source(hit: dict[str, Any]) -> str:
    name = str(hit.get("defense", ""))
    return "harness" if name.startswith(HARNESS_HIT_PREFIX) else "defense"


# ---------------------------------------------------------------------------
# Công tắc D1–D4 (trang 4)
# ---------------------------------------------------------------------------


def load_defenses(path: Path = DEFENSES_PATH) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def runnable_presets(cfg: dict[str, Any]) -> dict[str, list[str]]:
    """Preset chạy được (`name → [khối]`); bỏ nhóm lồng như `reduced_3`."""
    return {n: list(b) for n, b in cfg.get("presets", {}).items() if isinstance(b, list)}


def presets_for(toggled: Iterable[str], cfg: dict[str, Any]) -> list[str]:
    """Preset có tập khối bật đúng bằng các mã D1–D4 đang bật (có thể > 1, vd d3_only và
    d3_no_confirm — khác nhau ở `preset_overrides`)."""
    want = sorted(DEFENSE_KEYS[c] for c in toggled)
    return [n for n, b in runnable_presets(cfg).items() if sorted(b) == want]


def effective_params(code: str, preset: str | None, cfg: dict[str, Any]) -> dict[str, Any]:
    """Khối tham số của một cơ chế sau khi áp `preset_overrides` của preset — chỉ để hiển thị."""
    key = DEFENSE_KEYS[code]
    block = json.loads(json.dumps(cfg["defenses"][key]))
    block.pop("enabled", None)
    for dotted, value in (cfg.get("preset_overrides", {}).get(preset) or {}).items():
        head, *path = dotted.split(".")
        if head != key:
            continue
        node = block
        for part in path[:-1]:
            node = node[part]
        node[path[-1]] = value
    return block


def compare_with_off(runs: pd.DataFrame, enabled: str, *, by: str = "target_id") -> pd.DataFrame:
    """ASR_e2e (run tấn công) và USR (run lành tính) của cấu hình `enabled` cạnh `off`, theo `by`.

    `enabled` là chuỗi mã như trong cột `enabled` ("D3", "D1,D2,D3,D4", "-" = tắt hết). Một tập
    khối có thể ứng nhiều preset (d3_only, d3_no_confirm) — tách theo cột `preset`.
    """
    picked = runs[runs["enabled"].isin([enabled, "-"])]
    rows = []
    for (key, preset), cell in picked.groupby([by, "preset"], sort=True):
        attack = asr_table(cell, [by]) if (cell["run_kind"] == "attack").any() else None
        benign = cell[cell["run_kind"] == "benign"]
        usr = utility_summary(benign, by=(by,)) if len(benign) else None
        a = attack.iloc[0] if attack is not None and len(attack) else None
        u = usr.iloc[0] if usr is not None and len(usr) else None
        rows.append({
            by: key,
            "preset": preset,
            "n_attack": int(a["n"]) if a is not None else 0,
            "asr_e2e": a["asr_e2e"] if a is not None else None,
            "asr_e2e_lo": a["asr_e2e_lo"] if a is not None else None,
            "asr_e2e_hi": a["asr_e2e_hi"] if a is not None else None,
            "n_benign": int(u["n_clean"]) if u is not None else 0,
            "usr": u["usr"] if u is not None else None,
            "frr": u["frr"] if u is not None else None,
        })
    return pd.DataFrame(rows)


def list_figures(figures_dir: Path = FIGURES_DIR, prefix: str = "pareto") -> list[Path]:
    if not figures_dir.is_dir():
        return []
    return sorted(
        p for p in figures_dir.rglob(f"{prefix}*") if p.suffix.lower() in FIGURE_SUFFIXES
    )
