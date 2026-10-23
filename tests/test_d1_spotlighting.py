"""D1 Spotlighting (STT-51) — điều kiện đạt ở defense_spec.md §3.5.

Delimiter đổi mỗi run · không suy ra tất định · enabled=false ⇒ đầu ra = đầu vào · bọc đủ ba
nguồn · content chứa chính delimiter không phá ranh giới. Thêm: hit đúng khóa, datamarking,
nguồn ngoài wrap_sources không bọc, một run mọi nguồn chung một delimiter.
"""

import pytest

from defense import d1_spotlighting as d1
from interfaces import SOURCES


@pytest.fixture(autouse=True)
def _clean_cache():
    d1.clear_all_runs()
    yield
    d1.clear_all_runs()


def _spot(content, source="kb_chunk", run_id="r1", enabled=True, config=None):
    return d1.spotlight(content, source=source, run_id=run_id, enabled=enabled, config=config)


def test_tat_thi_nguyen_van_khong_hit():
    out = _spot("Số dư của bạn là 5 triệu.", enabled=False)
    assert out.text == "Số dư của bạn là 5 triệu."
    assert out.hits == ()


def test_nguon_ngoai_wrap_sources_khong_boc():
    cfg = {"params": {**d1.load_d1_config()["params"], "wrap_sources": ["kb_chunk"]}}
    out = _spot("x", source="tool_result", config=cfg)
    assert out.text == "x"
    assert out.hits == ()


def test_boc_du_ba_nguon():
    for source in SOURCES:
        d1.clear_all_runs()
        out = _spot("nội dung A", source=source, run_id="run-" + source)
        delim = d1._RUN_DELIMITERS["run-" + source]
        fences = [ln for ln in out.text.splitlines() if ln == delim]
        assert len(fences) == 2, source                     # đúng hai dòng rào
        assert "DỮ LIỆU" in out.text                         # câu thông báo có mặt
        assert out.hits and out.hits[0].defense == "d1_spotlighting"
        assert out.hits[0].stage == "context_assembly"
        assert out.hits[0].action == "transform"


def test_delimiter_doi_moi_run():
    _spot("cùng một nội dung", run_id="A")
    _spot("cùng một nội dung", run_id="B")
    assert d1._RUN_DELIMITERS["A"] != d1._RUN_DELIMITERS["B"]


def test_khong_suy_ra_tat_dinh_tu_run_id():
    # Cùng run_id nhưng sau khi dọn cache phải sinh delimiter khác (nguồn mật mã, không suy ra
    # từ run_id). Xác suất trùng ngẫu nhiên ~ (1/62)^12, bỏ qua được.
    _spot("x", run_id="same")
    first = d1._RUN_DELIMITERS["same"]
    d1.clear_run("same")
    _spot("x", run_id="same")
    assert d1._RUN_DELIMITERS["same"] != first


def test_mot_run_moi_nguon_chung_mot_delimiter():
    _spot("a", source="kb_chunk", run_id="R")
    _spot("b", source="tool_description", run_id="R")
    _spot("c", source="tool_result", run_id="R")
    # Chỉ một delimiter được cấp cho run R, dùng lại cho cả ba nguồn.
    assert len(d1._RUN_DELIMITERS) == 1 and "R" in d1._RUN_DELIMITERS


def test_content_chua_delimiter_khong_pha_ranh_gioi():
    # Gài sẵn delimiter của run rồi nhét chính nó vào content: phải bị thay, còn đúng hai dấu thật.
    d1._RUN_DELIMITERS["R"] = "ABCDEFGHIJKL"
    out = _spot("mở ABCDEFGHIJKL giả", run_id="R")
    fences = [ln for ln in out.text.splitlines() if ln == "ABCDEFGHIJKL"]
    assert len(fences) == 2                                 # chỉ hai dòng rào thật
    body = out.text.split("ABCDEFGHIJKL\n", 1)[1].rsplit("\nABCDEFGHIJKL", 1)[0]
    assert "ABCDEFGHIJKL" not in body                        # bản nhúng trong body đã bị thay
    assert d1._DELIMITER_REPLACEMENT in body


def test_datamarking_chen_ky_tu_giua_tu():
    base = {**d1.load_d1_config()["params"], "datamarking": True}
    out = _spot("alpha beta gamma", run_id="R", config={"params": base})
    mark = d1._RUN_DATAMARKS["R"]
    assert mark in out.text
    # Không còn khoảng trắng gốc giữa các từ của body (đã thay bằng mark).
    delim = d1._RUN_DELIMITERS["R"]
    body = out.text.split(delim + "\n", 1)[1].rsplit("\n" + delim, 1)[0]
    assert " " not in body and f"alpha{mark}beta{mark}gamma" == body


def test_config_mac_dinh_doc_tu_file():
    # Không tiêm config ⇒ đọc defenses.yaml, hai khóa §8 phải có mặt và dùng được.
    params = d1.load_d1_config()["params"]
    assert "notice_template_vi" in params
    assert set(params["source_labels_vi"]) == set(SOURCES)
    out = _spot("x")  # chạy được với config thật, không lỗi KeyError
    assert out.hits
