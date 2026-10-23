"""d2_input_sanitizer.py — D2 Input Sanitizer (STT-52).

Vì sao có file này: làm sạch cú pháp TẤT ĐỊNH nội dung không tin cậy (K1 lúc truy hồi, K2b lúc
tool-result về) trước khi nó vào context, để gỡ các dấu hiệu tiêm nhiễm có hình thái cú pháp khả
nghi (ký tự ẩn, comment, CSS giấu chữ, khối mã hóa, câu mệnh lệnh). Đặc tả hành vi, hit và điều
kiện đạt: `docs/04. Design/defense_spec.md` §4. Hook: `KB_RETRIEVAL` (kb_chunk) và `TOOL_RESULT`
(tool_result) trong interfaces.py.

Nguyên tắc (defense_spec §4.2):
- Hàm THUẦN của (text, cấu hình): tất định, O(n), KHÔNG gọi mạng, KHÔNG gọi LLM.
- Idempotent: `sanitize(sanitize(x)) == sanitize(x)`. Mọi dấu thay thế là hằng thấp-entropy nên
  không tự kích hoạt lại bước 5/6 ở lần chạy sau.
- Mọi tham số hành vi đọc từ `config/defenses.yaml` → `defenses.d2_input_sanitizer`, KHÔNG
  hard-code (quy tắc cứng #4). Hằng trong file này chỉ là thứ KHÔNG phải tham số điều chỉnh được.
- Chạy trên chunk ĐÃ truy hồi, không trên văn bản ingest ⇒ `delivered` không đổi giữa D2 bật/tắt.

Điểm mù có chủ ý (defense_spec §4.4): T3/T5 không có dấu hiệu cú pháp; T8 bỏ dấu/telex/VNI né tập
mệnh lệnh có dấu chuẩn (bước 6); K2a (tool_description) KHÔNG qua D2 theo mặc định (§4.5).

Chỉ dùng thư viện chuẩn + pyyaml.
"""

from __future__ import annotations

import math
import re
import unicodedata
from pathlib import Path
from typing import Any

from interfaces import DefenseHit, HookStage, Source, Transformed

__all__ = [
    "sanitize_input",
    "load_d2_config",
    "load_imperative_patterns",
    "clear_pattern_cache",
]

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "defenses.yaml"
_REPO_ROOT = Path(__file__).resolve().parents[2]

_DEFENSE_KEY = "d2_input_sanitizer"

#: Nguồn → stage của hit. D2 chạy ở hai hook; stage ghi vào trace lấy theo nguồn (interfaces.py).
_SOURCE_STAGE: dict[str, str] = {
    "kb_chunk": HookStage.KB_RETRIEVAL.value,
    "tool_result": HookStage.TOOL_RESULT.value,
}

#: Ký tự khoảng trắng GIỮ LẠI ở bước 2 dù thuộc Cc (điều khiển): xuống dòng, tab, về đầu dòng.
_KEEP_CONTROL = {"\n", "\t", "\r"}

#: Bảng chữ của khối "mã hóa" bước 5: base64 (gồm url-safe) + hex đã nằm trong đây.
_ENCODED_ALPHABET = re.compile(r"[A-Za-z0-9+/=_-]")
#: Một khối ứng viên liền mạch (không khoảng trắng) để xét entropy ở bước 5.
_CANDIDATE_BLOCK = re.compile(r"[A-Za-z0-9+/=_-]+")

#: Comment HTML (bước 3). DOTALL để bắt comment nhiều dòng.
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)

#: Phần tử HTML có thuộc tính style nội tuyến (bước 4). Không lồng — baseline xử lý mẫu T4 phổ biến.
_STYLED_ELEMENT = re.compile(
    r"<(?P<tag>[a-zA-Z][\w-]*)\b[^>]*\bstyle\s*=\s*(?P<q>['\"])(?P<style>.*?)(?P=q)[^>]*>"
    r"(?P<inner>.*?)</(?P=tag)\s*>",
    re.DOTALL | re.IGNORECASE,
)

#: Tách câu cho bước 6: theo xuống dòng và theo dấu kết câu + khoảng trắng.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?。！？])\s+|\n+")

# Cache mẫu mệnh lệnh đã compile, khóa theo đường dẫn file. Mẫu không đổi giữa các run.
_PATTERN_CACHE: dict[str, list[tuple[str, re.Pattern[str]]]] = {}

_FLAG_MAP = {"IGNORECASE": re.IGNORECASE, "MULTILINE": re.MULTILINE, "DOTALL": re.DOTALL}


def load_d2_config(path: Path | str = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Nạp khối `defenses.d2_input_sanitizer` từ defenses.yaml. Tách ra để test tiêm cấu hình."""
    import yaml

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return raw["defenses"][_DEFENSE_KEY]


def load_imperative_patterns(rel_path: str) -> list[tuple[str, re.Pattern[str]]]:
    """Nạp và compile tập regex mệnh lệnh (bước 6). Trả [(id, compiled), …], cache theo đường dẫn.

    `rel_path` lấy từ `params.imperative_patterns_file`, hiểu tương đối với gốc repo ipi-agent-lab.
    """
    cached = _PATTERN_CACHE.get(rel_path)
    if cached is not None:
        return cached

    import yaml

    full = rel_path if Path(rel_path).is_absolute() else _REPO_ROOT / rel_path
    doc = yaml.safe_load(Path(full).read_text(encoding="utf-8"))
    compiled: list[tuple[str, re.Pattern[str]]] = []
    for item in doc["patterns"]:
        flags = 0
        for name in item.get("flags", []):
            flags |= _FLAG_MAP[name]
        compiled.append((item["id"], re.compile(item["pattern"], flags)))
    _PATTERN_CACHE[rel_path] = compiled
    return compiled


def clear_pattern_cache() -> None:
    """Dọn cache mẫu đã compile. Chủ yếu cho test nạp file mẫu khác nhau."""
    _PATTERN_CACHE.clear()


def _shannon_bits_per_char(block: str) -> float:
    """Entropy Shannon (bit/ký tự) của một khối. Khối rỗng ⇒ 0."""
    if not block:
        return 0.0
    counts: dict[str, int] = {}
    for ch in block:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(block)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _hex_color(style: str, prop: str) -> str | None:
    """Rút giá trị màu của thuộc tính CSS `prop` trong `style` (dạng #rgb/#rrggbb), chuẩn hóa thường."""
    m = re.search(rf"{prop}\s*:\s*(#[0-9a-fA-F]{{3,8}})", style, re.IGNORECASE)
    return m.group(1).lower() if m else None


def _is_hidden_style(style: str, max_px: float) -> bool:
    """Style nội tuyến có giấu chữ không (bước 4): display:none · visibility:hidden · font-size nhỏ ·
    màu chữ trùng màu nền."""
    s = style.lower()
    if re.search(r"display\s*:\s*none", s):
        return True
    if re.search(r"visibility\s*:\s*hidden", s):
        return True
    m = re.search(r"font-size\s*:\s*([0-9.]+)\s*px", s)
    if m and float(m.group(1)) <= max_px:
        return True
    color = _hex_color(s, "color")
    background = _hex_color(s, "background-color") or _hex_color(s, "background")
    if color is not None and color == background:
        return True
    return False


def sanitize_input(
    text: str,
    *,
    source: Source,
    enabled: bool,
    config: dict[str, Any] | None = None,
) -> Transformed:
    """Làm sạch cú pháp `text` theo 6 bước của D2 (defense_spec §4.1).

    `source ∈ {kb_chunk, tool_result}`. `enabled=false` hoặc `source ∉ apply_to_sources` ⇒ trả
    nguyên văn, không hit. Mỗi bước đổi văn bản ⇒ một `DefenseHit(rule="S1".."S6")`.

    `config` mặc định đọc từ defenses.yaml; cho phép tiêm để test không phụ thuộc file.
    """
    cfg = config if config is not None else load_d2_config()

    # Bước 0 — tắt hoặc nguồn ngoài apply_to_sources: trả nguyên văn, không hit.
    if not enabled or source not in cfg["apply_to_sources"]:
        return Transformed(text=text)

    params = cfg["params"]
    stage = _SOURCE_STAGE[source]
    token = params["replacement_token"]
    hits: list[DefenseHit] = []

    def _hit(rule: str, action: str, detail: str) -> None:
        hits.append(DefenseHit(defense=_DEFENSE_KEY, stage=stage, action=action, rule=rule, detail=detail))

    # Bước 1 — chuẩn hóa Unicode (NFKC).
    after = unicodedata.normalize(params["unicode_form"], text)
    if after != text:
        _hit("S1", "transform", f"normalize {params['unicode_form']}")
    text = after

    # Bước 2 — loại ký tự ẩn theo category (Cf zero-width, Cc điều khiển), trừ \n \t \r.
    strip_cats = set(params["strip_categories"])
    after = "".join(
        ch for ch in text if ch in _KEEP_CONTROL or unicodedata.category(ch) not in strip_cats
    )
    if after != text:
        _hit("S2", "transform", f"strip categories {sorted(strip_cats)}")
    text = after

    # Bước 3 — gỡ HTML comment.
    if params.get("strip_hidden_html", False):
        after = _HTML_COMMENT.sub("", text)
        if after != text:
            _hit("S3", "transform", "strip <!-- comment -->")
        text = after

    # Bước 4 — gỡ phần tử HTML bị CSS giấu chữ.
    if params.get("strip_hidden_css", False):
        max_px = float(params["hidden_font_size_max_px"])

        def _drop_hidden(m: re.Match[str]) -> str:
            return "" if _is_hidden_style(m.group("style"), max_px) else m.group(0)

        after = _STYLED_ELEMENT.sub(_drop_hidden, text)
        if after != text:
            _hit("S4", "transform", "strip CSS-hidden element")
        text = after

    # Bước 5 — thay khối mã hóa entropy cao bằng dấu thay thế.
    min_len = int(params["min_suspicious_block_len"])
    threshold = float(params["entropy_threshold_bits_per_char"])

    def _redact_encoded(m: re.Match[str]) -> str:
        block = m.group(0)
        if len(block) < min_len:
            return block
        if _shannon_bits_per_char(block) < threshold:
            return block
        return token

    after = _CANDIDATE_BLOCK.sub(_redact_encoded, text)
    if after != text:
        _hit("S5", "transform", f"redact encoded block (>= {min_len} chars, entropy >= {threshold})")
    text = after

    # Bước 6 — thay / đánh dấu câu khớp mẫu mệnh lệnh.
    patterns = load_imperative_patterns(params["imperative_patterns_file"])
    action = params["imperative_action"]  # "redact" | "flag"
    matched_ids: list[str] = []
    out_parts: list[str] = []
    pos = 0
    for sep in _SENTENCE_SPLIT.finditer(text):
        _apply_imperative(text[pos : sep.start()], patterns, action, token, out_parts, matched_ids)
        out_parts.append(sep.group(0))
        pos = sep.end()
    _apply_imperative(text[pos:], patterns, action, token, out_parts, matched_ids)
    after = "".join(out_parts)
    if matched_ids:
        hit_action = "transform" if action == "redact" else "flag"
        _hit("S6", hit_action, f"imperative {action}: {','.join(matched_ids)}")
    if action == "redact":
        text = after

    return Transformed(text=text, hits=tuple(hits))


def _apply_imperative(
    sentence: str,
    patterns: list[tuple[str, re.Pattern[str]]],
    action: str,
    token: str,
    out_parts: list[str],
    matched_ids: list[str],
) -> None:
    """Xét một câu với mọi mẫu; khớp thì ghi id và (nếu redact) thay cả câu bằng dấu thay thế."""
    if not sentence.strip():
        out_parts.append(sentence)
        return
    for pid, rx in patterns:
        if rx.search(sentence):
            matched_ids.append(pid)
            out_parts.append(token if action == "redact" else sentence)
            return
    out_parts.append(sentence)
