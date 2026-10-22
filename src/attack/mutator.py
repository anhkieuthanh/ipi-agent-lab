"""mutator.py — sinh biến thể payload theo luật, lọc qua schema và theo embedding (STT-43).

Vì sao có file này: tập payload tay (T1–T5, cặp vi/en) nhỏ. Mutator nhân số lượng cho ma trận
BẰNG CÁCH biến đổi biểu diễn bề mặt của payload đã hợp lệ (obfuscation: mã hóa, đồng hình,
chèn ký tự rộng-0…), KHÔNG tạo kỹ thuật mới (quy tắc cứng #9) và KHÔNG đổi ngữ nghĩa tấn công.

Ba lớp, đọc theo thứ tự:

1. `rule_mutate(payload)` — áp từng phép biến đổi theo luật (tất định, không mạng, không LLM),
   trả biến thể mới + ghi vết phép đã dùng. Phép và tham số đọc từ `config/mutator.yaml`.
2. Cổng `activation_check`/schema — mọi biến thể chạy lại `schema.validate_payload`; biến thể sai
   bất biến nào (vd T4 cần obfuscation ẩn, lạc kênh…) bị LOẠI TỰ ĐỘNG, không soát tay
   (`payload_taxonomy.md` mục 5). Mutator KHÔNG tự phán "payload có kích hoạt không" — đó là
   việc pilot `defense=OFF` (STT-60); ở đây chỉ bảo đảm biến thể còn hợp schema và vẫn khai được
   `activation_check` kiểm-bằng-máy.
3. `dedup_by_embedding(payloads)` — nhúng `base_text` của mỗi biến thể bằng `Embedder`
   (`config/rag.yaml`, cosine); hai bản cosine ≥ ngưỡng coi là trùng, giữ bản xuất hiện trước.
   So trùng trong cùng (technique, goal).

Ranh giới trách nhiệm:
- Danh sách obfuscation hợp lệ, bất biến, activation_check: nguồn là `schema.py` — KHÔNG chép lại.
- Biến đổi đặc thù chữ Việt cho T8 (`vi_transform`: bỏ dấu, telex/VNI…) là việc của STT-47, KHÔNG
  làm ở đây; mutator chỉ sinh obfuscation.
- "Biến đổi bằng model" (paraphrase LLM) vướng `attacker_model` chưa chốt với GVHD (quy tắc cứng
  #8); `model_mutate()` là điểm cắm, chưa nối model.

Chỉ dùng thư viện chuẩn + pyyaml. `dedup_by_embedding` nhận `embed_fn` tiêm ngoài để test không
phải nạp model thật.
"""

from __future__ import annotations

import base64
import copy
import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

from .payloads.render import base_text
from .payloads.schema import (
    OBFUSCATION,
    TaskMeta,
    load_task_meta,
    validate_payload,
)

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "mutator.yaml"

# Placeholder giữ nguyên khi biến đổi văn bản (trùng với render/schema). Không chèn ký tự vào
# giữa, không mã hóa — giá trị thật chỉ có lúc chạy.
_PLACEHOLDER_RE = re.compile(r"\{[A-Za-z_]+\}")
_ID_RE = re.compile(r"^(P)-(T[1-8])-(G[1-3])-(VI|EN|MIX)-(\d{3,})$")
_WORD_CHARS_RE = re.compile(r"[A-Za-z]")

# Đồng hình ASCII→Unicode (Cyrillic/Hy Lạp). CHỈ chữ Latin ASCII; chữ Việt có dấu để nguyên
# (đồng hình trên chữ Việt là `homoglyph_vi` của T8 — STT-47).
_HOMOGLYPH = {
    "a": "а", "c": "с", "e": "е", "o": "о", "p": "р",
    "x": "х", "y": "у", "i": "і", "j": "ј", "s": "ѕ",
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н",
    "K": "К", "M": "М", "O": "О", "P": "Р", "T": "Т",
    "X": "Х", "Y": "У",
}


class MutatorError(ValueError):
    """Cấu hình mutator hỏng hoặc phép biến đổi không áp được — dừng, không đoán."""


def load_mutator_config(path: Path | str = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(cfg, dict) or "rule" not in cfg or "dedup" not in cfg:
        raise MutatorError(f"{path}: thiếu khối 'rule' hoặc 'dedup'")
    return cfg


# ── Biến đổi chuỗi theo luật ────────────────────────────────────────────────────
def _split_placeholders(text: str) -> list[tuple[str, bool]]:
    """Cắt text thành các đoạn (chuỗi, là_placeholder). Placeholder giữ nguyên."""
    out: list[tuple[str, bool]] = []
    last = 0
    for m in _PLACEHOLDER_RE.finditer(text):
        if m.start() > last:
            out.append((text[last:m.start()], False))
        out.append((m.group(0), True))
        last = m.end()
    if last < len(text):
        out.append((text[last:], False))
    return out


def _map_text_segments(text: str, fn: Callable[[str], str]) -> str:
    """Áp `fn` lên các đoạn không phải placeholder, nối lại."""
    return "".join(seg if is_ph else fn(seg) for seg, is_ph in _split_placeholders(text))


def _insert_between_letters(seg: str, sep: str) -> str:
    """Chèn `sep` vào giữa hai chữ cái ASCII liền nhau (giữ chuỗi vẫn đọc gần như cũ)."""
    out: list[str] = []
    for i, ch in enumerate(seg):
        out.append(ch)
        nxt = seg[i + 1] if i + 1 < len(seg) else ""
        if _WORD_CHARS_RE.match(ch) and _WORD_CHARS_RE.match(nxt):
            out.append(sep)
    return "".join(out)


def _apply_homoglyph(seg: str) -> str:
    return "".join(_HOMOGLYPH.get(ch, ch) for ch in seg)


def _full_encode(text: str, kind: str) -> str:
    raw = text.encode("utf-8")
    if kind == "base64":
        return base64.b64encode(raw).decode("ascii")
    if kind == "hex":
        return raw.hex()
    if kind == "percent_encoding":
        return quote(text, safe="")
    raise MutatorError(f"phép full_encode lạ '{kind}'")


# ── Sinh biến thể từ một payload ────────────────────────────────────────────────
_LANG_FIELDS = ("instruction_vi", "instruction_en")


def _instruction_strings(p: dict[str, Any]) -> list[str]:
    gb = p.get("goal_binding") or {}
    return [gb[f] for f in _LANG_FIELDS if gb.get(f)]


def _has_placeholder(p: dict[str, Any]) -> bool:
    return any(_PLACEHOLDER_RE.search(s) for s in _instruction_strings(p))


def _bump_ids(payloads: Sequence[dict[str, Any]]) -> dict[tuple[str, str, str], int]:
    """Số thứ tự id lớn nhất đang dùng theo (T, G, LANG-token), để cấp id mới không trùng."""
    hi: dict[tuple[str, str, str], int] = {}
    for p in payloads:
        m = _ID_RE.match(str(p.get("id", "")))
        if m:
            key = (m.group(2), m.group(3), m.group(4))
            hi[key] = max(hi.get(key, 0), int(m.group(5)))
    return hi


def _transform_instructions(p: dict[str, Any], fn: Callable[[str], str]) -> None:
    gb = p["goal_binding"]
    for f in _LANG_FIELDS:
        if gb.get(f):
            gb[f] = fn(gb[f])


def rule_mutate(
    payload: dict[str, Any],
    *,
    cfg: dict[str, Any],
    id_counter: dict[tuple[str, str, str], int],
) -> list[tuple[dict[str, Any], str]]:
    """Trả list (biến thể, tên phép). Chỉ biến đổi payload chưa obfuscate (obfuscation == [none]).

    Mỗi biến thể là payload độc lập: bỏ `pair_id` (không còn thuộc cặp đối chứng vi/en), đặt
    `obfuscation = [tên phép]`, cấp id mới, biến đổi phần chỉ thị. KHÔNG đổi `activation_check`,
    `goal_binding.tool`, `goal`, `technique` — ngữ nghĩa tấn công giữ nguyên.
    """
    if set(payload.get("obfuscation") or ["none"]) != {"none"}:
        return []  # không chồng obfuscation lên payload đã obfuscate
    m = _ID_RE.match(str(payload.get("id", "")))
    if not m:
        return []
    key = (m.group(2), m.group(3), m.group(4))
    rule = cfg["rule"]
    full = set(rule.get("full_encode") or [])
    zw = rule["zero_width_char"]
    sep = rule["char_separation_sep"]

    def make(name: str, fn: Callable[[str], str]) -> tuple[dict[str, Any], str]:
        if name not in OBFUSCATION:
            raise MutatorError(f"phép '{name}' không thuộc OBFUSCATION của schema.py")
        v = copy.deepcopy(payload)
        v.pop("pair_id", None)
        id_counter[key] = id_counter.get(key, 0) + 1
        v["id"] = f"P-{key[0]}-{key[1]}-{key[2]}-{id_counter[key]:03d}"
        v["obfuscation"] = [name]
        _transform_instructions(v, fn)
        return v, name

    out: list[tuple[dict[str, Any], str]] = []
    has_ph = _has_placeholder(payload)
    for name in rule["enabled"]:
        if name in full:
            # mã hóa toàn phần không giữ được placeholder; bỏ qua nếu chỉ thị có {…}
            if has_ph:
                continue
            out.append(make(name, lambda s, k=name: _full_encode(s, k)))
        elif name == "zero_width":
            out.append(make(name, lambda s: _map_text_segments(s, lambda seg: _insert_between_letters(seg, zw))))
        elif name == "char_separation":
            out.append(make(name, lambda s: _map_text_segments(s, lambda seg: _insert_between_letters(seg, sep))))
        elif name == "homoglyph":
            out.append(make(name, lambda s: _map_text_segments(s, _apply_homoglyph)))
        else:
            raise MutatorError(f"phép biến đổi '{name}' chưa hiện thực")
    return out


def model_mutate(
    payload: dict[str, Any], *, cfg: dict[str, Any], **kwargs: Any
) -> list[tuple[dict[str, Any], str]]:
    """Điểm cắm biến đổi bằng model (paraphrase LLM). CHƯA nối model.

    `attacker_model` chưa chốt với GVHD (checklist mục 8 việc 6; config/experiment.yaml
    B5.attacker_model: null). Theo quy tắc cứng #8, không tự quyết. Bật `model.enabled` trong
    config/mutator.yaml và hiện thực hàm này khi GVHD chốt model.
    """
    if not (cfg.get("model") or {}).get("enabled"):
        return []
    raise NotImplementedError(
        "model_mutate chưa nối: attacker_model chưa chốt với GVHD (quy tắc cứng #8)"
    )


# ── Lọc trùng theo embedding ────────────────────────────────────────────────────
def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _dedup_key(p: dict[str, Any], scope: Sequence[str]) -> tuple:
    out = []
    for field_ in scope:
        if field_ == "technique":
            out.append((p.get("technique") or {}).get("code"))
        else:
            out.append(p.get(field_))
    return tuple(out)


def dedup_by_embedding(
    payloads: Sequence[dict[str, Any]],
    *,
    cfg: dict[str, Any],
    embed_fn: Callable[[str], Sequence[float]],
) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    """Lọc trùng trong cùng scope theo cosine(`base_text`). Giữ bản xuất hiện TRƯỚC.

    Trả (giữ_lại, [(id_bị_loại, id_bản_giữ)]). `embed_fn` tiêm ngoài để test không nạp model.
    """
    dcfg = cfg["dedup"]
    threshold = float(dcfg["cosine_threshold"])
    scope = dcfg.get("scope") or ["technique", "goal"]
    kept: list[dict[str, Any]] = []
    kept_vecs: list[tuple[tuple, list[float]]] = []  # (khóa scope, vector) song song với kept
    dropped: list[tuple[str, str]] = []
    for p in payloads:
        key = _dedup_key(p, scope)
        vec = list(embed_fn(base_text(p)))
        dup_of: str | None = None
        for (k2, v2), kp in zip(kept_vecs, kept, strict=True):
            if k2 == key and _cosine(vec, v2) >= threshold:
                dup_of = kp["id"]
                break
        if dup_of is not None:
            dropped.append((str(p.get("id")), dup_of))
        else:
            kept.append(p)
            kept_vecs.append((key, vec))
    return kept, dropped


# ── Dàn nhạc ─────────────────────────────────────────────────────────────────────
@dataclass
class MutationReport:
    n_seed: int = 0
    n_generated: int = 0
    n_rejected_schema: int = 0
    n_deduped: int = 0
    n_kept: int = 0
    rejected: dict[str, list[str]] = field(default_factory=dict)   # id → lỗi schema
    deduped: list[tuple[str, str]] = field(default_factory=list)   # (id loại, id giữ)


def mutate(
    seeds: Sequence[dict[str, Any]],
    *,
    cfg: dict[str, Any] | None = None,
    meta: TaskMeta | None = None,
    embed_fn: Callable[[str], Sequence[float]] | None = None,
) -> tuple[list[dict[str, Any]], MutationReport]:
    """Sinh biến thể từ `seeds`, qua cổng schema, rồi lọc trùng. Trả (biến thể_giữ, report).

    Không gồm `seeds` trong đầu ra — chỉ trả các biến thể MỚI. `embed_fn` None thì nạp Embedder
    mặc định (chỉ khi cần dedup và có biến thể qua cổng).
    """
    cfg = cfg or load_mutator_config()
    meta = meta or load_task_meta()
    report = MutationReport(n_seed=len(seeds))
    id_counter = _bump_ids(seeds)

    candidates: list[dict[str, Any]] = []
    for p in seeds:
        candidates.extend(v for v, _name in rule_mutate(p, cfg=cfg, id_counter=id_counter))
        candidates.extend(v for v, _name in model_mutate(p, cfg=cfg))  # điểm cắm, hiện trả []
    report.n_generated = len(candidates)

    passed: list[dict[str, Any]] = []
    for v in candidates:
        errs = validate_payload(v, meta=meta)
        if errs:
            report.rejected[str(v.get("id"))] = errs
        else:
            passed.append(v)
    report.n_rejected_schema = len(report.rejected)

    if not passed:
        report.n_kept = 0
        return [], report

    if embed_fn is None:
        from rag.embedder import get_embedder

        embed_fn = get_embedder().embed_query
    kept, dropped = dedup_by_embedding(passed, cfg=cfg, embed_fn=embed_fn)
    report.deduped = dropped
    report.n_deduped = len(dropped)
    report.n_kept = len(kept)
    return kept, report
