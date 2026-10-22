"""Kiểm bộ tạo tài liệu chèn ẩn payload T4 trên kênh K1 (STT-42).

Bất biến T4 phải giữ cho MỌI bề mặt: parser/RAG TRÍCH RA chỉ thị, người duyệt render KHÔNG thấy
(hoặc thấy ở vùng độ-chú-ý-thấp). Test khẳng định đúng hai vế đó, không phải chỉ "file sinh ra".

Lệnh trích chuẩn cho PDF là `pdftotext` (sheet STT-42 yêu cầu). Test ưu tiên pypdf để chạy được
không cần poppler; thêm một test riêng bằng `pdftotext` binary, tự bỏ qua khi máy không có.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile

import pytest
from make_hidden_pdf import (
    SAMPLE_PAYLOAD,
    HiddenDocError,
    extract_pdf_metadata,
    extract_pdf_text,
    load_spec,
    render_html,
    render_pdf,
    visible_text_of_html,
)

SPEC = load_spec()
PDF_SURFACES = [n for n, s in SPEC["surfaces"].items() if s["media"] == "pdf"]
HTML_SURFACES = [n for n, s in SPEC["surfaces"].items() if s["media"] == "html"]


def test_spec_obfuscation_hop_le():
    """Mọi bề mặt phải ánh xạ về mã obfuscation CÓ SẴN trong schema (hướng a, không mã mới)."""
    from attack.payloads.schema import OBFUSCATION

    for name, s in SPEC["surfaces"].items():
        assert s["obfuscation"] in OBFUSCATION, f"{name}: mã obfuscation lạ {s['obfuscation']!r}"


# ————————————————————————————————————— PDF —————————————————————————————————————

@pytest.mark.parametrize("surface", PDF_SURFACES)
def test_pdf_parser_doc_ra_payload(surface):
    """Parser phải đọc ra payload — ở thân văn (white_1pt/footer) hoặc metadata (pdf_metadata)."""
    data = render_pdf(SAMPLE_PAYLOAD, surface)
    norm = re.sub(r"\s+", " ", SAMPLE_PAYLOAD).strip()
    if SPEC["surfaces"][surface]["verify"] == "pdf_metadata":
        md = extract_pdf_metadata(data)
        assert norm in re.sub(r"\s+", " ", md["subject"]).strip()
        assert norm not in extract_pdf_text(data), "metadata không được lọt vào thân văn"
    else:
        assert norm in extract_pdf_text(data), f"{surface}: pdftotext/pypdf không trích được payload"


def test_pdf_white_1pt_vo_hinh_voi_nguoi_doc():
    """Chữ trắng 1pt: màu trùng nền + cỡ 1pt — bằng chứng bất đối xứng, không chỉ là 'có trích ra'."""
    s = SPEC["surfaces"]["pdf_white_1pt"]
    assert s["color_rgb"] == [255, 255, 255]
    assert s["font_size_pt"] == 1
    assert s["visible_to_reviewer"] is False


def test_pdf_tai_lap_byte_identical():
    """Sinh hai lần cùng payload cho bytes y hệt (creation date cố định)."""
    a = render_pdf(SAMPLE_PAYLOAD, "pdf_white_1pt")
    b = render_pdf(SAMPLE_PAYLOAD, "pdf_white_1pt")
    assert a == b


@pytest.mark.skipif(not shutil.which("pdftotext"), reason="cần poppler/pdftotext")
def test_pdftotext_binary_trich_duoc():
    """Đúng công cụ sheet yêu cầu: chạy `pdftotext` thật trên file white_1pt."""
    data = render_pdf(SAMPLE_PAYLOAD, "pdf_white_1pt")
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(data)
        f.flush()
        out = subprocess.run(
            ["pdftotext", "-enc", "UTF-8", f.name, "-"],
            capture_output=True, text=True, check=True,
        ).stdout
    assert re.sub(r"\s+", " ", SAMPLE_PAYLOAD).strip() in re.sub(r"\s+", " ", out).strip()


# ———————————————————————————————————— HTML ————————————————————————————————————

@pytest.mark.parametrize("surface", HTML_SURFACES)
def test_html_bat_doi_xung(surface):
    """Payload có trong HTML thô nhưng biến mất khỏi text người duyệt thấy (bỏ comment + thẻ)."""
    doc = render_html(SAMPLE_PAYLOAD, surface)
    # Thô: payload hiện diện (comment nguyên văn; alt đã escape nên so trên bản escape).
    if surface == "html_comment":
        assert SAMPLE_PAYLOAD in doc
    else:  # html_alt_text — so sau khi unescape phần alt
        import html as _html
        assert SAMPLE_PAYLOAD in _html.unescape(doc)
    # Hiển thị: không còn payload.
    assert SAMPLE_PAYLOAD not in visible_text_of_html(doc)


# ———————————————————————————————————— lỗi ————————————————————————————————————

def test_vuot_gioi_han_bao_loi_khong_cat():
    big = "x" * (SPEC["max_payload_chars"] + 1)
    with pytest.raises(HiddenDocError):
        render_pdf(big, "pdf_white_1pt")


def test_sai_media_bao_loi():
    with pytest.raises(HiddenDocError):
        render_pdf(SAMPLE_PAYLOAD, "html_comment")  # bề mặt html gọi nhầm render_pdf
    with pytest.raises(HiddenDocError):
        render_html(SAMPLE_PAYLOAD, "pdf_white_1pt")


def test_be_mat_la_bao_loi():
    with pytest.raises(HiddenDocError):
        render_pdf(SAMPLE_PAYLOAD, "khong_ton_tai")
