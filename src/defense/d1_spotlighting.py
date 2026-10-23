"""d1_spotlighting.py — D1 Spotlighting dạng delimiting (STT-51).

Vì sao có file này: dựng lại ranh giới dữ liệu / chỉ thị lúc ghép prompt, để mô hình có cơ sở coi
nội dung không tin cậy (K1, K2a, K2b) là DỮ LIỆU chứ không phải chỉ thị. Dựa trên spotlighting
dạng *delimiting* (Hines và cs., 2024). Đặc tả hành vi, chữ ký, hit và điều kiện đạt:
`docs/04. Design/defense_spec.md` mục 3. Hook: `CONTEXT_ASSEMBLY` (interfaces.py).

Nguyên tắc (defense_spec mục 1):
- Mọi tham số hành vi đọc từ `config/defenses.yaml` → `defenses.d1_spotlighting`, KHÔNG hard-code
  (quy tắc cứng #4). Hằng trong file này chỉ là thứ KHÔNG phải tham số điều chỉnh được: dấu thay
  thế cố định và tập ký tự đánh dấu "cố định" mà spec §3.1 bước 4–5 nhắc tới.
- D1 sinh delimiter ngẫu nhiên có chủ ý (một lần mỗi run, nguồn mật mã), nhưng phép bọc đi cùng
  delimiter đó là tất định. Không gọi LLM, không thêm lượt gọi mô hình.

Delimiter theo run (defense_spec §3.2):
- Sinh MỘT lần cho mỗi `run_id`, giữ trong cache module, dùng chung cho mọi nguồn của run đó.
- Đổi giữa các run; KHÔNG suy ra tất định từ nội dung, tên tool hay chính `run_id`.
- Kẻ tấn công thích ứng biết D1 làm gì nhưng KHÔNG biết delimiter của run đang chạy (Threat Model
  NL3) — không có đường nào trong module này làm lộ delimiter ra ngoài trace/log.
- `clear_run(run_id)` cho lõi agent / test dọn cache sau mỗi run.

Chỉ dùng thư viện chuẩn + pyyaml.
"""

from __future__ import annotations

import re
import secrets
import string
from pathlib import Path
from typing import Any

import yaml

from interfaces import DefenseHit, HookStage, Transformed

__all__ = ["spotlight", "load_d1_config", "clear_run", "clear_all_runs"]

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "defenses.yaml"

#: Bảng chữ sinh delimiter: chữ-số ASCII, tránh ký tự dễ đụng cú pháp Markdown/JSON của context.
_DELIMITER_ALPHABET = string.ascii_letters + string.digits

#: Dấu thay thế cố định khi content chứa chính delimiter (spec §3.1 bước 4). Không phải tham số.
_DELIMITER_REPLACEMENT = "[¤]"

#: Tập ký tự đánh dấu cố định cho datamarking (spec §3.1 bước 5); chọn ngẫu nhiên theo run.
_DATAMARK_CHARS = ("⸱", "·", "•")  # ⸱  ·  •

_DEFENSE_KEY = "d1_spotlighting"
_STAGE = HookStage.CONTEXT_ASSEMBLY.value  # "context_assembly" — khớp DefenseHit.stage

# Cache theo run — xem docstring. Một delimiter + một ký tự datamark cho mỗi run_id.
_RUN_DELIMITERS: dict[str, str] = {}
_RUN_DATAMARKS: dict[str, str] = {}

_WHITESPACE_RE = re.compile(r"\s+")


def load_d1_config(path: Path | str = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Nạp khối `defenses.d1_spotlighting` từ defenses.yaml. Tách ra để test tiêm cấu hình."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return raw["defenses"][_DEFENSE_KEY]


def _run_delimiter(run_id: str, length: int) -> str:
    """Delimiter của run: sinh một lần bằng nguồn mật mã, giữ theo `run_id`, chung cho mọi nguồn."""
    delim = _RUN_DELIMITERS.get(run_id)
    if delim is None:
        delim = "".join(secrets.choice(_DELIMITER_ALPHABET) for _ in range(length))
        _RUN_DELIMITERS[run_id] = delim
    return delim


def _run_datamark(run_id: str) -> str:
    """Ký tự đánh dấu của run: chọn ngẫu nhiên một lần từ tập cố định, giữ theo `run_id`."""
    mark = _RUN_DATAMARKS.get(run_id)
    if mark is None:
        mark = secrets.choice(_DATAMARK_CHARS)
        _RUN_DATAMARKS[run_id] = mark
    return mark


def clear_run(run_id: str) -> None:
    """Xóa delimiter và ký tự datamark đã cấp cho `run_id`. Lõi agent gọi sau mỗi run."""
    _RUN_DELIMITERS.pop(run_id, None)
    _RUN_DATAMARKS.pop(run_id, None)


def clear_all_runs() -> None:
    """Dọn toàn bộ cache. Chủ yếu cho test giữ các ca độc lập nhau."""
    _RUN_DELIMITERS.clear()
    _RUN_DATAMARKS.clear()


def spotlight(
    content: str,
    *,
    source: str,
    run_id: str,
    enabled: bool,
    config: dict[str, Any] | None = None,
) -> Transformed:
    """Bọc nội dung không tin cậy giữa cặp delimiter của run (D1 — spec §3).

    `content` đã qua D2 (nếu D2 bật). `source ∈ {kb_chunk, tool_description, tool_result}`. Trả
    `Transformed(text, hits)`; không tác động thì `hits` rỗng (spec mục 6: không hit = không tác động).

    `config` mặc định đọc từ `defenses.yaml`; cho phép tiêm để test không phụ thuộc file.
    """
    # Bước 1 — tắt thì trả nguyên văn, không hit.
    if not enabled:
        return Transformed(text=content)

    params = (config if config is not None else load_d1_config())["params"]

    # Bước 2 — nguồn ngoài wrap_sources: không bọc.
    if source not in params["wrap_sources"]:
        return Transformed(text=content)

    # Bước 3 — delimiter của run.
    delimiter = _run_delimiter(run_id, int(params["delimiter_length"]))

    # Bước 4 — content chứa chính delimiter (cách giả mạo ranh giới): thay bằng dấu cố định.
    body = content
    if delimiter in body:
        body = body.replace(delimiter, _DELIMITER_REPLACEMENT)

    # Bước 5 — datamarking (tùy chọn, mặc định tắt): chèn ký tự đánh dấu vào giữa các từ.
    if params.get("datamarking", False):
        mark = _run_datamark(run_id)
        body = _WHITESPACE_RE.sub(mark, body)

    # Bước 6 — bọc: câu thông báo + khối {delimiter} ⏎ body ⏎ {delimiter}.
    source_label = params["source_labels_vi"][source]
    notice = params["notice_template_vi"].format(source_label=source_label, delimiter=delimiter)
    text = f"{notice}\n{delimiter}\n{body}\n{delimiter}"

    # Bước 7 — ghi hit.
    hit = DefenseHit(
        defense=_DEFENSE_KEY,
        stage=_STAGE,
        action="transform",
        detail=f"spotlight source={source}",
    )
    return Transformed(text=text, hits=(hit,))
