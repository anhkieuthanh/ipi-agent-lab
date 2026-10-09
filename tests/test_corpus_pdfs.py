"""Kiểm 15 báo giá PDF của kho tài liệu.

Test này canh đúng một lỗi đã từng xảy ra: PDF sinh bằng font base-14
`/Helvetica` (không nhúng, không ToUnicode) làm mất toàn bộ dấu tiếng Việt khi
trích text ('Khách hàng: Công ty TNHH Kn thunt Sn Minn Trung'). 15/40 tài liệu
hỏng ⇒ embedding sai ⇒ retrieval sai ⇒ `delivered` của kênh K1 bị nhiễu bởi lỗi
kỹ thuật thay vì bởi phòng thủ (xem `scripts/gen_corpus_pdfs.py`).

Test chạy trên file PDF ĐÃ COMMIT, không sinh lại — nên nó bắt được cả trường
hợp ai đó thay file bằng bản hỏng mà quên chạy generator.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pypdf
import pytest

from gen_corpus_pdfs import QUOTES, quote_lines

CORPUS_DIR = Path(__file__).resolve().parent.parent / "src" / "rag" / "corpus"
MANIFEST = CORPUS_DIR.parent / "corpus_manifest.csv"

# Dấu hiệu font hỏng: ký tự thay thế của pypdf/pdfminer khi không map được glyph.
BROKEN_GLYPH_MARKERS = ("�", "■", "\x00")


def _text_of(pdf_path: Path) -> str:
    """Text trích từ PDF, đã gộp mọi khoảng trắng/xuống dòng thành 1 dấu cách.

    Ngắt dòng theo layout là chuyện của trình render, không phải của nội dung —
    khâu chunk ở src/rag/ingest.py cũng chuẩn hóa như vậy trước khi embedding.
    """
    reader = pypdf.PdfReader(str(pdf_path))
    raw = "\n".join(page.extract_text() or "" for page in reader.pages)
    return re.sub(r"\s+", " ", raw).strip()


@pytest.fixture(scope="module")
def corpus_texts() -> dict[str, str]:
    return {q["id"]: _text_of(CORPUS_DIR / f"{q['id']}.pdf") for q in QUOTES}


def test_du_15_bao_gia():
    assert len(QUOTES) == 15
    on_disk = sorted(p.stem for p in CORPUS_DIR.glob("BG-*.pdf"))
    assert on_disk == sorted(q["id"] for q in QUOTES)


@pytest.mark.parametrize("quote", QUOTES, ids=[q["id"] for q in QUOTES])
def test_trich_duoc_nguyen_van_tieng_viet(quote, corpus_texts):
    """Mọi dòng của bảng nguồn phải xuất hiện NGUYÊN VĂN trong text trích ra."""
    text = corpus_texts[quote["id"]]
    assert f"BÁO GIÁ SỐ {quote['id']}" in text
    for label, value in quote_lines(quote):
        expected = re.sub(r"\s+", " ", f"{label}: {value}")
        assert expected in text, f"{quote['id']}: thiếu/sai dòng {label!r}"


@pytest.mark.parametrize("quote", QUOTES, ids=[q["id"] for q in QUOTES])
def test_khong_co_glyph_hong(quote, corpus_texts):
    text = corpus_texts[quote["id"]]
    for marker in BROKEN_GLYPH_MARKERS:
        assert marker not in text, f"{quote['id']}: có ký tự hỏng {marker!r}"
    # Chốt chặn cuối: phải còn ít nhất vài chữ có dấu tổ hợp tiếng Việt.
    assert re.search(r"[ăâđêôơưĂÂĐÊÔƠƯáàảãạếệốộớợừữ]", text)


def test_khach_hang_khop_manifest(corpus_texts):
    """Tên khách hàng trong PDF phải khớp mô tả ở corpus_manifest.csv."""
    with MANIFEST.open(encoding="utf-8") as f:
        desc = {r["file_name"]: r["description"] for r in csv.DictReader(f)}
    for quote in QUOTES:
        file_name = f"{quote['id']}.pdf"
        assert file_name in desc, f"{file_name} thiếu trong manifest"
        assert quote["customer"] in desc[file_name], (
            f"{file_name}: khách hàng trong PDF ({quote['customer']!r}) "
            f"không khớp manifest ({desc[file_name]!r})"
        )


def test_cap_doi_chieu_ct02(corpus_texts):
    """CT-02 (STT-18) so sánh BG-2026-014 với BG-2026-021 trên 2 tiêu chí.

    Nếu ai đó sửa nội dung 2 báo giá này thành giống nhau thì tác vụ chở CT-02
    mất ý nghĩa mà không có gì báo động — nên khóa lại ở đây.
    """
    a, b = corpus_texts["BG-2026-014"], corpus_texts["BG-2026-021"]
    assert "TRẢ CHẬM 45 ngày" in a
    assert "không áp dụng trả chậm" in b
    assert "7 ngày làm việc" in a
    assert "15 ngày làm việc" in b
