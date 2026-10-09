"""Kiểm ingest pipeline (kênh K1).

Chia hai nhóm:

  * **Không cần Qdrant** — chunking, đọc tài liệu, tiền tố embedding. Đây là
    nhóm chạy trong CI, và cũng là nhóm bắt được các lỗi im lặng nguy hiểm
    nhất (tokenizer cắt cụt, thiếu tiền tố E5).
  * **Cần Qdrant** (`@pytest.mark.qdrant`) — chèn/xóa theo run và ngưỡng thời
    gian của DoD. Tự bỏ qua khi không có server, vì CI không dựng Qdrant.
"""

from __future__ import annotations

import uuid

import pytest

from rag.embedder import get_embedder, resolve_prefixes
from rag.ingest import (
    CORPUS_DIR,
    PREP_BUDGET_S,
    RagConfig,
    bench_inject_cleanup,
    chunk_text,
    cleanup_doc,
    connect,
    count_points,
    ensure_collection,
    inject_doc,
    iter_corpus_files,
    point_id,
    read_document,
)


@pytest.fixture(scope="module")
def embedder():
    return get_embedder()


@pytest.fixture(scope="module")
def cfg():
    return RagConfig.load()


# --------------------------------------------------------------------------- #
# Tiền tố E5
# --------------------------------------------------------------------------- #


def test_e5_co_tien_to_query_va_passage():
    """Thiếu tiền tố thì E5 vẫn chạy, chỉ tệ đi — phải khóa bằng test."""
    assert resolve_prefixes("intfloat/multilingual-e5-large") == ("query: ", "passage: ")


def test_model_khong_thuoc_ho_co_quy_uoc_thi_khong_them_gi():
    assert resolve_prefixes("BAAI/bge-large-en-v1.5") == ("", "")


def test_embedder_gan_dung_tien_to(embedder):
    assert embedder.query_prefix == "query: "
    assert embedder.passage_prefix == "passage: "


def test_so_chieu_doc_tu_model_khong_viet_cung(embedder):
    assert embedder.dim == 1024
    assert embedder.spec.dim == embedder.dim


# --------------------------------------------------------------------------- #
# Chunking — nhóm bắt lỗi im lặng
# --------------------------------------------------------------------------- #


def test_tokenizer_chunking_da_tat_truncation(embedder):
    """Bẫy chính của ingest.

    Tokenizer đi kèm model bật `truncation.max_length = 512`. Nếu chia chunk
    bằng nó, mọi tài liệu dài chỉ còn 512 token đầu và phần sau biến mất không
    dấu vết. Test này so số token đếm được với số token thật.
    """
    text = "Điều khoản thanh toán trả chậm ba mươi ngày kể từ ngày giao hàng. " * 200
    n_tokens = len(embedder.chunking_tokenizer.encode(text, add_special_tokens=False).ids)
    assert n_tokens > 512, "văn bản mẫu phải dài hơn giới hạn thì test mới có nghĩa"
    assert embedder.chunking_tokenizer.truncation is None


def test_chunk_khong_mat_phan_duoi(embedder):
    text = "Điều khoản thanh toán trả chậm ba mươi ngày kể từ ngày giao hàng. " * 200
    chunks = chunk_text(text, embedder, 512, 64)
    assert len(chunks) > 1, "tài liệu dài phải sinh nhiều chunk, không phải một"
    # Câu cuối của văn bản gốc phải còn nằm trong chunk cuối.
    assert "giao hàng" in chunks[-1]


def test_moi_chunk_vua_gioi_han_model(embedder):
    text = "Bảng giá thiết bị đo lường công nghiệp quý ba năm 2026. " * 300
    for chunk in chunk_text(text, embedder, 512, 64):
        n = len(embedder.chunking_tokenizer.encode(chunk, add_special_tokens=False).ids)
        assert n <= 512, f"chunk {n} token, vượt giới hạn ngữ cảnh của model"


def test_chunk_co_chong_lan(embedder):
    text = " ".join(f"đoạn{i}" for i in range(2000))
    chunks = chunk_text(text, embedder, 512, 64)
    assert len(chunks) >= 2
    # Chồng lấn tồn tại thì đuôi chunk trước phải xuất hiện lại ở đầu chunk sau.
    tail = chunks[0].split()[-5:]
    assert any(tok in chunks[1] for tok in tail)


def test_overlap_lon_hon_max_thi_bao_loi(embedder):
    with pytest.raises(ValueError, match="nhỏ hơn max_tokens"):
        chunk_text("abc", embedder, 128, 128)


def test_van_ban_rong_cho_ra_khong_chunk(embedder):
    assert chunk_text("", embedder, 512, 64) == []


# --------------------------------------------------------------------------- #
# Đọc tài liệu
# --------------------------------------------------------------------------- #


def test_doc_du_40_file():
    assert len(list(iter_corpus_files())) == 40


def test_pdf_trich_duoc_tieng_viet_co_dau():
    """Khóa lại kết quả sửa font của gen_corpus_pdfs từ phía ingest."""
    text = read_document(CORPUS_DIR / "BG-2026-001.pdf")
    assert "BÁO GIÁ SỐ" in text


def test_docx_lay_ca_noi_dung_bang():
    text = read_document(CORPUS_DIR / "HD-2026-009_hop_dong_phan_phoi.docx")
    assert "HD-2026-009" in text
    assert "Nam Phát" in text, "thiếu tên khách hàng — có thể đang bỏ qua bảng"


def test_moi_file_trong_corpus_doc_ra_noi_dung():
    for path in iter_corpus_files():
        assert read_document(path).strip(), f"{path.name} đọc ra rỗng"


def test_point_id_on_dinh_giua_cac_lan_chay():
    """Cùng (doc_id, chunk_index) phải cho cùng id, nếu không ingest lại sẽ
    nhân bản điểm thay vì ghi đè."""
    assert point_id("a.pdf", 0) == point_id("a.pdf", 0)
    assert point_id("a.pdf", 0) != point_id("a.pdf", 1)
    assert point_id("a.pdf", 0) != point_id("b.pdf", 0)


# --------------------------------------------------------------------------- #
# Cần Qdrant
# --------------------------------------------------------------------------- #


def _qdrant_san_sang(cfg: RagConfig) -> bool:
    try:
        connect(cfg).get_collections()
        return True
    except Exception:
        return False


@pytest.fixture
def live_client(cfg, embedder):
    if not _qdrant_san_sang(cfg):
        pytest.skip(f"Qdrant không chạy ở {cfg.qdrant_url} — `make up` trước")
    client = connect(cfg)
    ensure_collection(client, cfg, embedder)
    return client


@pytest.mark.qdrant
def test_chen_roi_xoa_tra_ve_dung_so_diem(live_client, cfg, embedder):
    run_id = f"test-{uuid.uuid4().hex[:8]}"
    content = "Báo giá số BG-2026-099. " + ("Điều khoản trả chậm 45 ngày. " * 30)

    n = inject_doc(run_id, content, cfg=cfg, client=live_client, embedder=embedder)
    assert n >= 1
    assert count_points(cfg=cfg, client=live_client, run_id=run_id) == n

    cleanup_doc(run_id, cfg=cfg, client=live_client)
    assert count_points(cfg=cfg, client=live_client, run_id=run_id) == 0


@pytest.mark.qdrant
def test_cleanup_khong_dung_toi_collection_nen(live_client, cfg, embedder):
    """DoD: 'collection nền không bị đụng tới'."""
    truoc = count_points(cfg=cfg, client=live_client, source=cfg.base_marker)
    run_id = f"test-{uuid.uuid4().hex[:8]}"
    inject_doc(run_id, "Tài liệu nhiễm độc thử nghiệm.", cfg=cfg, client=live_client,
               embedder=embedder)
    cleanup_doc(run_id, cfg=cfg, client=live_client)
    assert count_points(cfg=cfg, client=live_client, source=cfg.base_marker) == truoc


@pytest.mark.qdrant
def test_hai_run_khong_thay_tai_lieu_cua_nhau(live_client, cfg, embedder):
    a, b = f"test-{uuid.uuid4().hex[:8]}", f"test-{uuid.uuid4().hex[:8]}"
    inject_doc(a, "Tài liệu của run A.", cfg=cfg, client=live_client, embedder=embedder)
    inject_doc(b, "Tài liệu của run B.", cfg=cfg, client=live_client, embedder=embedder)
    cleanup_doc(a, cfg=cfg, client=live_client)
    assert count_points(cfg=cfg, client=live_client, run_id=a) == 0
    assert count_points(cfg=cfg, client=live_client, run_id=b) >= 1
    cleanup_doc(b, cfg=cfg, client=live_client)


@pytest.mark.qdrant
def test_run_id_rong_bi_tu_choi(live_client, cfg, embedder):
    """`cleanup_doc('')` mà chạy được thì filter sẽ khớp cả tài liệu nền."""
    with pytest.raises(ValueError):
        inject_doc("", "x", cfg=cfg, client=live_client, embedder=embedder)
    with pytest.raises(ValueError):
        cleanup_doc("", cfg=cfg, client=live_client)


@pytest.mark.qdrant
def test_khau_chuan_bi_kb_duoi_nguong(live_client):
    """Ngưỡng / rủi ro R8: chèn + xóa một tài liệu < 10 giây."""
    r = bench_inject_cleanup()
    assert r["total_s"] < PREP_BUDGET_S, (
        f"chèn+xóa mất {r['total_s']:.2f}s, vượt ngưỡng {PREP_BUDGET_S}s"
    )


# --------------------------------------------------------------------------- #
# Chống rác khi run chết giữa chừng — phát hiện khi soát W2 (07/08/2026)
# --------------------------------------------------------------------------- #


@pytest.mark.qdrant
def test_injected_doc_don_sach_khi_than_with_nem_loi(live_client, cfg, embedder):
    """Đây là kịch bản đã xảy ra thật: exception giữa inject và cleanup để lại
    tài liệu nhiễm độc vĩnh viễn trong `kb`, và mọi run sau truy hồi trúng nó."""
    from rag.ingest import injected_doc

    run_id = f"test-ctx-{uuid.uuid4().hex[:8]}"
    with pytest.raises(RuntimeError):
        with injected_doc(
            run_id, "Tài liệu nhiễm độc thử nghiệm.", cfg=cfg, client=live_client,
            embedder=embedder,
        ):
            raise RuntimeError("giả lập agent chết giữa chừng")

    assert count_points(cfg=cfg, client=live_client, run_id=run_id) == 0


@pytest.mark.qdrant
def test_injected_doc_don_sach_khi_thanh_cong(live_client, cfg, embedder):
    from rag.ingest import injected_doc

    run_id = f"test-ctx-{uuid.uuid4().hex[:8]}"
    with injected_doc(
        run_id, "Tài liệu nhiễm độc thử nghiệm.", cfg=cfg, client=live_client,
        embedder=embedder,
    ) as n:
        assert n >= 1
        assert count_points(cfg=cfg, client=live_client, run_id=run_id) == n
    assert count_points(cfg=cfg, client=live_client, run_id=run_id) == 0


@pytest.mark.qdrant
def test_purge_injected_khong_dung_toi_nen(live_client, cfg, embedder):
    from rag.ingest import purge_injected

    nen_truoc = count_points(cfg=cfg, client=live_client, source=cfg.base_marker)
    inject_doc(f"test-purge-{uuid.uuid4().hex[:8]}", "rác thử nghiệm",
               cfg=cfg, client=live_client, embedder=embedder)
    purge_injected(cfg=cfg, client=live_client)

    assert count_points(cfg=cfg, client=live_client, source=cfg.inject_marker) == 0
    assert count_points(cfg=cfg, client=live_client, source=cfg.base_marker) == nen_truoc
