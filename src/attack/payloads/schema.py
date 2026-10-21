"""schema.py — hợp đồng thi hành của payload T1–T8 (bước code của STT-20).

File này cưỡng chế các bất biến ở `docs/04. Design/payload_taxonomy.md` mục 4.3 (bất biến 1–10)
và các ràng buộc trường ở mục 4.1/4.2/5. `payload_taxonomy.md` là nguồn quy định; lệch nhau thì
sửa code theo file đó.

Nguyên tắc như `eval/allowed_actions.py`: KHÔNG hard-code lại danh sách tool, bồn chứa G1 hay
placeholder canary. Mọi hằng đọc thẳng từ `data/carrier_tasks.json` và `eval/canary.py` để không
có hai nguồn sự thật lệch nhau.

Dùng:

    from attack.payloads.schema import load_payloads, validate_payload

    errors = validate_payload(one_dict)          # [] nếu hợp lệ
    payloads, report = load_payloads(PATH)        # report.ok / report.errors_by_id

Chỉ dùng thư viện chuẩn (pyproject không có pydantic/jsonschema). Không gọi mạng, không gọi LLM.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eval.canary import CANARY_PLACEHOLDER
from eval.canary import REAL_CANARY_RE as _REAL_CANARY_RE

DEFAULT_TASKS_PATH = Path(__file__).resolve().parents[3] / "data" / "carrier_tasks.json"

# ── Hằng cố định theo taxonomy (không suy từ file đo) ──────────────────────────
TECHNIQUES = ("T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8")
GOALS = ("G1", "G2", "G3")
LANGS = ("vi", "en", "mixed")
LANG_TOKEN = {"vi": "VI", "en": "EN", "mixed": "MIX"}  # bất biến (b): ánh xạ id ↔ enum

T1_VARIANTS = ("bare", "user_signed", "system_tag", "developer", "authority_letter")
SOURCE_KINDS = ("original", "adapted", "verbatim")
BASE_FRAMES = ("T1", "T2", "T3", "T5")  # bất biến 10: T4/T6/T7/T8 KHÔNG làm base_frame
OBFUSCATION = (
    "none", "base64", "hex", "percent_encoding", "char_separation", "zero_width",
    "homoglyph", "hidden_html_comment", "hidden_css", "hidden_attribute", "hidden_json_field",
)
HIDDEN_OBFUSCATION = (
    "hidden_html_comment", "hidden_css", "hidden_attribute", "hidden_json_field", "zero_width",
)
VI_TRANSFORMS = ("strip_diacritics", "telex", "vni", "homoglyph_vi", "code_mix")
TRIGGER_KINDS = ("tool_result_match", "min_step")
G2_VIOLATIONS = ("tool_not_allowed", "constraint_violation")
G2_SEVERITIES = ("read_only", "internal_write", "external_action")
G3_MARKERS = ("url", "bank_account", "vendor_code")
G1_CANARY_KINDS = ("sysprompt", "db", "any")

# placeholder ngữ cảnh cho phép trong template (bất biến 1)
_CTX_PLACEHOLDERS = {"{USER}", "{MODEL}", "{TOOL}"}
_INSTRUCTION = "{INSTRUCTION}"
_PLACEHOLDER_RE = re.compile(r"\{[A-Z_]+\}")
_ID_RE = re.compile(r"^P-(T[1-8])-(G[1-3])-(VI|EN|MIX)-(\d{3,})$")
# giá trị canary thật của run có dạng CANARY_SYSPROMPT_<uuid> / CANARY_DB_<uuid>;
# payload chỉ được chứa placeholder, không bao giờ chứa giá trị thật (bất biến 7)
_RUN_ID = "{run_id}"


@dataclass(frozen=True)
class TaskMeta:
    """Phần dữ liệu đọc từ carrier_tasks.json mà validator cần."""

    tools: tuple[str, ...]              # năm tool của lab
    egress_tools: tuple[str, ...]       # bồn G1 có side_effect (không gồm final_answer)
    g1_sinks: tuple[str, ...]           # bốn bồn G1 (gồm final_answer)
    carrier_ids: tuple[str, ...]        # CT-01..CT-06


def load_task_meta(path: Path | str = DEFAULT_TASKS_PATH) -> TaskMeta:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    tools = tuple(data["agent_tools"].keys())
    egress = tuple(
        name for name, spec in data["agent_tools"].items() if spec.get("side_effect")
    )
    sinks = tuple(data["goal_definitions"]["G1"]["sinks"].keys())  # gồm final_answer
    carriers = tuple(ct["id"] for ct in data["carrier_tasks"])
    return TaskMeta(tools=tools, egress_tools=egress, g1_sinks=sinks, carrier_ids=carriers)


# ── Validator ─────────────────────────────────────────────────────────────────
def validate_payload(p: dict[str, Any], *, meta: TaskMeta | None = None) -> list[str]:
    """Trả danh sách lỗi (chuỗi mô tả). Rỗng nghĩa là hợp lệ.

    Mỗi lỗi gắn mã bất biến để truy về taxonomy mục 4.3, ví dụ "[INV6] …".
    """
    if meta is None:
        meta = load_task_meta()
    e: list[str] = []
    tools = set(meta.tools)

    # —— trường bắt buộc (4.1) ——
    for key in ("id", "technique", "goal", "channels", "lang", "source", "activation_check"):
        if key not in p:
            e.append(f"[REQ] thiếu trường bắt buộc '{key}'")
    if e:  # thiếu trường gốc thì dừng sớm, tránh KeyError dây chuyền
        return e

    tech = p["technique"] if isinstance(p["technique"], dict) else {}
    code = tech.get("code")
    goal = p["goal"]
    lang = p["lang"]

    if code not in TECHNIQUES:
        e.append(f"[INV9] technique.code '{code}' ∉ T1..T8")
        return e  # không biết kỹ thuật thì các kiểm theo kỹ thuật vô nghĩa
    if goal not in GOALS:
        e.append(f"[REQ] goal '{goal}' ∉ {GOALS}")
    if lang not in LANGS:
        e.append(f"[REQ] lang '{lang}' ∉ {LANGS}")

    # —— id và tính khớp (4.1) ——
    m = _ID_RE.match(str(p["id"]))
    if not m:
        e.append(f"[REQ] id '{p['id']}' sai mẫu P-<T#>-<G#>-<VI|EN|MIX>-<NNN>")
    else:
        id_t, id_g, id_lang = m.group(1), m.group(2), m.group(3)
        if id_t != code:
            e.append(f"[REQ] id mang {id_t} nhưng technique.code = {code}")
        if id_g != goal:
            e.append(f"[REQ] id mang {id_g} nhưng goal = {goal}")
        if lang in LANGS and id_lang != LANG_TOKEN[lang]:
            e.append(f"[INV-b] id mang {id_lang} nhưng lang = {lang} (chờ {LANG_TOKEN.get(lang)})")

    # —— template (bất biến 1, 2) ——
    template = tech.get("template", "")
    if template.count(_INSTRUCTION) != 1:
        e.append("[INV1] template phải chứa ĐÚNG MỘT {INSTRUCTION}")
    bad_ph = {ph for ph in _PLACEHOLDER_RE.findall(template)
              if ph != _INSTRUCTION and ph not in _CTX_PLACEHOLDERS}
    if bad_ph:
        e.append(f"[INV1] template có placeholder lạ {sorted(bad_ph)}; chỉ cho {_CTX_PLACEHOLDERS | {_INSTRUCTION}}")
    for tool in tools:
        if re.search(rf"\b{re.escape(tool)}\b", template):
            e.append(f"[INV2] template chứa tên tool của lab '{tool}' (phải trung lập, khả chuyển)")

    # —— variant (bất biến 3) ——
    variant = tech.get("variant", "none")
    if code == "T1":
        if variant not in T1_VARIANTS:
            e.append(f"[INV3] T1.variant '{variant}' ∉ {T1_VARIANTS}")
    elif variant not in (None, "none"):
        e.append(f"[INV3] {code}.variant phải là 'none', gặp '{variant}'")

    # —— channels (bất biến 4) ——
    channels = p["channels"]
    if not isinstance(channels, list) or not channels:
        e.append("[REQ] channels phải là list không rỗng")
    else:
        if len(set(channels)) != len(channels):
            e.append("[REQ] channels trùng phần tử")
        bad_ch = set(channels) - {"K1", "K2a", "K2b"}
        if bad_ch:
            e.append(f"[REQ] channels có kênh lạ {sorted(bad_ch)}")
        if code == "T4" and "K2a" in channels:
            e.append("[INV4] T4 loại K2a (không có tầng render — mục 2.1)")
        if code == "T6" and set(channels) != {"K1"}:
            e.append("[INV4] T6 chỉ dựng trên K1 (mục 2.1)")

    # —— goal_binding (bất biến 6) ——
    # G3: không tool. G1 rò CHỈ qua final_answer: không có tool-call nên tool = None
    # (nới bất biến 6, VT-3). Còn lại (G1 qua bồn egress, G2): tool thuộc năm tool.
    gb = p.get("goal_binding")
    _ac = p["activation_check"] if isinstance(p["activation_check"], dict) else {}
    g1_answer_only = goal == "G1" and set(_ac.get("sinks") or []) == {"final_answer"}
    if goal == "G3":
        if gb is not None and gb.get("tool") is not None:
            e.append("[INV6] G3 ⇒ goal_binding.tool phải là None")
    elif g1_answer_only:
        if gb and gb.get("tool") is not None:
            e.append("[INV6] G1 rò qua final_answer (không tool-call) ⇒ goal_binding.tool phải là None")
        for f_ in ("instruction_vi", "instruction_en"):
            if not (gb or {}).get(f_):
                e.append(f"[REQ] goal_binding.{f_} bắt buộc khi {goal}")
    else:  # G1 qua bồn egress, hoặc G2
        if not gb or gb.get("tool") not in tools:
            e.append(f"[INV6] {goal} (bồn egress) ⇒ goal_binding.tool phải thuộc {sorted(tools)}")
        for f_ in ("instruction_vi", "instruction_en"):
            if not (gb or {}).get(f_):
                e.append(f"[REQ] goal_binding.{f_} bắt buộc khi {goal}")

    # —— source (4.1) ——
    src = p["source"] if isinstance(p["source"], dict) else {}
    kind = src.get("kind")
    if kind not in SOURCE_KINDS:
        e.append(f"[REQ] source.kind '{kind}' ∉ {SOURCE_KINDS}")
    else:
        if kind != "original" and not src.get("ref"):
            e.append("[REQ] source.ref bắt buộc khi kind ≠ original")
        if kind in ("verbatim", "adapted") and not src.get("license"):
            e.append("[REQ] source.license bắt buộc khi verbatim/adapted")
        if kind == "adapted" and not src.get("adaptation_note"):
            e.append("[REQ] source.adaptation_note bắt buộc khi adapted")
    if code == "T3" and kind != "original":
        e.append("[T3] mọi payload T3 phải là original (MCPTox không giấy phép — taxonomy 6.3)")

    # —— obfuscation (4.2) ——
    obf = p.get("obfuscation", ["none"])
    bad_obf = set(obf) - set(OBFUSCATION)
    if bad_obf:
        e.append(f"[REQ] obfuscation giá trị lạ {sorted(bad_obf)}")
    if code == "T4" and not (set(obf) & set(HIDDEN_OBFUSCATION)):
        e.append(f"[T4] cần ≥1 obfuscation ẩn {HIDDEN_OBFUSCATION}")

    # —— base_frame (bất biến 10) ——
    bf = p.get("base_frame")
    if code == "T8":
        if bf not in BASE_FRAMES:
            e.append(f"[INV10] T8 bắt buộc base_frame ∈ {BASE_FRAMES}, gặp '{bf}'")
    elif code in ("T6", "T7"):
        if bf is not None and bf not in BASE_FRAMES:
            e.append(f"[INV10] {code}.base_frame nếu có phải ∈ {BASE_FRAMES}, gặp '{bf}'")
    else:  # T1..T5
        if bf not in (None, "", []):
            e.append(f"[INV10] {code} phải để trống base_frame, gặp '{bf}'")

    # —— trường riêng kỹ thuật (4.2) ——
    if code == "T6":
        frags = p.get("fragments")
        if not isinstance(frags, list) or len(frags) < 2:
            e.append("[T6] fragments phải ≥2 phần tử")
        elif any(not isinstance(fr, dict) or not fr.get("fragment_id") for fr in frags):
            e.append("[T6] mỗi fragment cần fragment_id")
    elif p.get("fragments"):
        e.append(f"[T6] chỉ T6 dùng fragments, {code} không được có")

    if code == "T7":
        tr = p.get("trigger") or {}
        if tr.get("kind") not in TRIGGER_KINDS:
            e.append(f"[T7] trigger.kind ∈ {TRIGGER_KINDS}")
        elif tr["kind"] == "tool_result_match" and not (tr.get("tool") and tr.get("pattern")):
            e.append("[T7] trigger tool_result_match cần 'tool' và 'pattern'")
        elif tr["kind"] == "min_step" and not (isinstance(tr.get("step_min"), int) and tr["step_min"] >= 3):
            e.append("[T7] trigger min_step cần step_min nguyên ≥3")
    elif p.get("trigger"):
        e.append(f"[T7] chỉ T7 dùng trigger, {code} không được có")

    if code == "T8":
        vt = p.get("vi_transform")
        if not isinstance(vt, list) or not vt:
            e.append("[T8] vi_transform bắt buộc ≥1")
        elif set(vt) - set(VI_TRANSFORMS):
            e.append(f"[T8] vi_transform giá trị lạ {sorted(set(vt) - set(VI_TRANSFORMS))}")
        if lang not in ("vi", "mixed"):
            e.append("[T8] lang phải là vi hoặc mixed")
    elif p.get("vi_transform"):
        e.append(f"[T8] chỉ T8 dùng vi_transform, {code} không được có")

    # —— activation_check (bất biến 5, 8 + mục 5) ——
    ac = p["activation_check"] if isinstance(p["activation_check"], dict) else {}
    if ac.get("goal") != goal:
        e.append(f"[INV5] activation_check.goal '{ac.get('goal')}' ≠ goal '{goal}'")
    e.extend(_check_activation(ac, goal, meta))

    # —— không lộ canary thật (bất biến 7) ——
    blob = json.dumps(p, ensure_ascii=False)
    for hit in _REAL_CANARY_RE.findall(blob):
        if hit != CANARY_PLACEHOLDER:
            e.append(f"[INV7] payload chứa giá trị canary thật '{hit}'; chỉ được dùng placeholder")

    return e


def _check_activation(ac: dict[str, Any], goal: str, meta: TaskMeta) -> list[str]:
    e: list[str] = []
    if goal == "G1":
        if ac.get("canary_kind") not in G1_CANARY_KINDS:
            e.append(f"[G1] canary_kind ∈ {G1_CANARY_KINDS}")
        sinks = ac.get("sinks") or []
        bad = set(sinks) - set(meta.g1_sinks)
        if not sinks:
            e.append("[G1] sinks không rỗng")
        if bad:
            e.append(f"[G1] sinks lạ {sorted(bad)}; cho {meta.g1_sinks}")
        if "record_leak_attempted" not in ac:
            e.append("[G1] thiếu record_leak_attempted")
    elif goal == "G2":
        if ac.get("violation") not in G2_VIOLATIONS:
            e.append(f"[G2] violation ∈ {G2_VIOLATIONS}")
        if ac.get("severity") not in G2_SEVERITIES:
            e.append(f"[G2] severity ∈ {G2_SEVERITIES}")
        if ac.get("violation") == "constraint_violation" and not ac.get("expected_argument_predicate"):
            e.append("[G2] constraint_violation bắt buộc có expected_argument_predicate")
        if "call_count" in ac:
            e.append("[G2] call_count không phải điều kiện G2 (max_calls tách ra)")
    elif goal == "G3":
        if ac.get("marker_kind") not in G3_MARKERS:
            e.append(f"[G3] marker_kind ∈ {G3_MARKERS}")
        if _RUN_ID not in str(ac.get("marker_template", "")):
            e.append("[INV8] G3 marker_template phải chứa {run_id}, không hard-code")
    return e


# ── Nạp cả tập ────────────────────────────────────────────────────────────────
@dataclass
class ValidationReport:
    total: int
    ok: list[str] = field(default_factory=list)                 # id hợp lệ
    errors_by_id: dict[str, list[str]] = field(default_factory=dict)

    @property
    def all_ok(self) -> bool:
        return not self.errors_by_id


def load_payloads(
    path: Path | str, *, meta: TaskMeta | None = None
) -> tuple[list[dict[str, Any]], ValidationReport]:
    """Nạp file payload (list JSON) và validate từng phần tử.

    Không ném ngoại lệ khi payload sai — gom vào report để soạn sửa dần.
    """
    if meta is None:
        meta = load_task_meta()
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items = data if isinstance(data, list) else data.get("payloads", [])
    report = ValidationReport(total=len(items))
    seen: set[str] = set()
    for i, p in enumerate(items):
        pid = p.get("id", f"<#{i} không có id>")
        errs = validate_payload(p, meta=meta)
        if pid in seen:
            errs.append(f"[REQ] id trùng '{pid}'")
        seen.add(pid)
        if errs:
            report.errors_by_id[pid] = errs
        else:
            report.ok.append(pid)
    return items, report
