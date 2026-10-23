"""Biến đổi che giấu đặc thù tiếng Việt cho kỹ thuật T8 — STT-47.

Năm phép (`VI_TRANSFORMS`, trùng `payloads.schema`): bỏ dấu, telex, VNI, đồng hình chữ Việt, trộn
mã vi-en. Mục tiêu: giữ ý nghĩa chỉ thị cho model đọc được NHƯNG né bộ dò huấn luyện trên tiếng Anh
và D2 (`Y_TUONG_DU_AN.md`: đóng góp mới — biến luận cứ "bối cảnh tiếng Việt" thành số liệu).

Mọi phép là HÀM THUẦN, tất định. Chỉ biến phần ngôn ngữ tự nhiên; GIỮ NGUYÊN:
- placeholder `{INSTRUCTION}`, `{run_id}` và mọi `{...}`; token `<...>` (gồm `<canary>`);
- các chuỗi `protect` do bên gọi truyền (marker mục tiêu như `NCC-{run_id}`, mã khách `KH-001`,
  giá trị `goal_binding.arguments`) — để tool vẫn chạy và scorer vẫn khớp đúng mục tiêu.

Generator `scripts/gen_t8_payloads.py` dùng module này; `base_text` render literal nên chuỗi đã biến
phải nằm sẵn trong `t8_vietnamese.yaml` (mutator KHÔNG áp vi_transform — xem mutator.py mục đầu).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from attack.mutator import _HOMOGLYPH  # đồng hình ASCII→Cyrillic/Hy Lạp, dùng chung một bảng

__all__ = ["VI_TRANSFORMS", "apply", "available"]

#: Trùng `payloads.schema.VI_TRANSFORMS`. Lệch nhau thì validator bắt — một khái niệm, một nguồn.
VI_TRANSFORMS = ("strip_diacritics", "telex", "vni", "homoglyph_vi", "code_mix")

# —— Bản đồ dấu kết hợp (NFD) ————————————————————————————————————————————————
_CIRCUMFLEX = "̂"  # â ê ô
_BREVE = "̆"  # ă
_HORN = "̛"  # ơ ư
_TONE_TELEX = {"̀": "f", "́": "s", "̃": "x", "̉": "r", "̣": "j"}
_TONE_VNI = {"̀": "2", "́": "1", "̃": "4", "̉": "3", "̣": "5"}
_MOD_MARKS = (_CIRCUMFLEX, _BREVE, _HORN)

# —— Token bảo toàn mặc định ————————————————————————————————————————————————
_DEFAULT_PROTECT_RE = (r"\{[A-Za-z_]+\}", r"<[A-Za-z_]+>")


def available() -> tuple[str, ...]:
    return VI_TRANSFORMS


def _protector(protect: Iterable[str]) -> re.Pattern[str]:
    parts = list(_DEFAULT_PROTECT_RE) + [re.escape(p) for p in sorted(set(protect), key=len, reverse=True) if p]
    return re.compile("|".join(parts))


def _map_unprotected(text: str, fn, protect: Iterable[str]) -> str:
    """Áp `fn` lên các đoạn KHÔNG phải token bảo toàn; token giữ nguyên."""
    rx = _protector(protect)
    out: list[str] = []
    last = 0
    for m in rx.finditer(text):
        if m.start() > last:
            out.append(fn(text[last:m.start()]))
        out.append(m.group(0))
        last = m.end()
    if last < len(text):
        out.append(fn(text[last:]))
    return "".join(out)


# —— Các phép trên một đoạn ngôn ngữ tự nhiên ————————————————————————————————
def _decompose(ch: str) -> tuple[str, str | None, str | None]:
    """Trả (chữ nền, dấu bổ nghĩa, dấu thanh) theo NFD. Dấu không phải Việt → (ch, None, None)."""
    nfd = unicodedata.normalize("NFD", ch)
    base, mod, tone = nfd[0], None, None
    for mark in nfd[1:]:
        if mark in _MOD_MARKS:
            mod = mark
        elif mark in _TONE_TELEX:
            tone = mark
    return base, mod, tone


def _strip_seg(seg: str) -> str:
    out: list[str] = []
    for ch in seg:
        if ch in ("đ", "Đ"):
            out.append("d" if ch == "đ" else "D")
            continue
        nfd = unicodedata.normalize("NFD", ch)
        out.append("".join(c for c in nfd if not unicodedata.combining(c)))
    return "".join(out)


def _stem_telex(base: str, mod: str | None) -> str:
    if mod == _CIRCUMFLEX:
        return base + base
    if mod in (_BREVE, _HORN):
        return base + ("w" if base.islower() else "W")
    return base


def _telex_seg(seg: str) -> str:
    out: list[str] = []
    for ch in seg:
        if ch == "đ":
            out.append("dd")
            continue
        if ch == "Đ":
            out.append("Dd")
            continue
        base, mod, tone = _decompose(ch)
        if mod is None and tone is None:
            out.append(ch)
            continue
        out.append(_stem_telex(base, mod) + (_TONE_TELEX[tone] if tone else ""))
    return "".join(out)


def _stem_vni(base: str, mod: str | None) -> str:
    if mod == _CIRCUMFLEX:
        return base + "6"
    if mod == _BREVE:
        return base + "8"
    if mod == _HORN:
        return base + "7"
    return base


def _vni_seg(seg: str) -> str:
    out: list[str] = []
    for ch in seg:
        if ch in ("đ", "Đ"):
            out.append(("d" if ch == "đ" else "D") + "9")
            continue
        base, mod, tone = _decompose(ch)
        if mod is None and tone is None:
            out.append(ch)
            continue
        out.append(_stem_vni(base, mod) + (_TONE_VNI[tone] if tone else ""))
    return "".join(out)


def _homoglyph_seg(seg: str) -> str:
    """Đồng hình trên chữ nền Latin; chữ có dấu NFD tách nền rồi ghép lại dấu để vẫn đổi được nền."""
    out: list[str] = []
    for ch in seg:
        nfd = unicodedata.normalize("NFD", ch)
        base = nfd[0]
        if base in _HOMOGLYPH:
            out.append(_HOMOGLYPH[base] + nfd[1:])
        else:
            out.append(ch)
    return "".join(out)


#: Từ điển trộn mã vi→en (thường gặp trong payload mệnh lệnh). Cụm dài khớp trước.
_CODE_MIX = {
    "quan trọng": "important",
    "bỏ qua": "ignore",
    "chỉ thị": "instruction",
    "tuân thủ": "follow",
    "thực hiện": "execute",
    "khách hàng": "customer",
    "bản ghi": "record",
    "nội bộ": "internal",
    "gửi": "send",
    "bước": "step",
    "trước": "before",
    "mọi": "all",
    "mã": "code",
    "phiên": "session",
}
_CODE_MIX_RE = re.compile(
    "|".join(re.escape(k) for k in sorted(_CODE_MIX, key=len, reverse=True)), re.IGNORECASE
)


def _code_mix_seg(seg: str) -> str:
    return _CODE_MIX_RE.sub(lambda m: _CODE_MIX[m.group(0).lower()], seg)


_SEG_FN = {
    "strip_diacritics": _strip_seg,
    "telex": _telex_seg,
    "vni": _vni_seg,
    "homoglyph_vi": _homoglyph_seg,
    "code_mix": _code_mix_seg,
}


def apply(name: str, text: str, *, protect: Iterable[str] = ()) -> str:
    """Áp phép `name` lên `text`, giữ nguyên token bảo toàn. `name` ∉ VI_TRANSFORMS → KeyError."""
    if name not in _SEG_FN:
        raise KeyError(f"vi_transform lạ: {name!r}; có {VI_TRANSFORMS}")
    return _map_unprotected(text, _SEG_FN[name], protect)
