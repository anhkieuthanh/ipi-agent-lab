"""Kiểm retriever (kênh K1).

Cần Qdrant có sẵn collection nền (`make kb-build`), nên toàn bộ nằm dưới
`@pytest.mark.qdrant` — tự bỏ qua khi không có server, giống `test_ingest.py`.
"""

from __future__ import annotations

import uuid

import pytest

from rag.embedder import get_embedder
from rag.ingest import RagConfig, cleanup_doc, connect, inject_doc
from rag.retriever import SearchResult, is_delivered, search


@pytest.fixture(scope="module")
def embedder():
    return get_embedder()


@pytest.fixture(scope="module")
def cfg():
    return RagConfig.load()


def _qdrant_san_sang(cfg: RagConfig) -> bool:
    try:
        connect(cfg).get_collections()
        return True
    except Exception:
        return False


@pytest.fixture
def live_client(cfg):
    if not _qdrant_san_sang(cfg):
        pytest.skip(f"Qdrant không chạy ở {cfg.qdrant_url} — `make up` + `make kb-build` trước")
    return connect(cfg)


# --------------------------------------------------------------------------- #
# search() — 10 truy vấn tiếng Việt trên collection nền
# --------------------------------------------------------------------------- #

TRUY_VAN_TIENG_VIET = [
    "điều khoản thanh toán trả chậm là bao nhiêu ngày",
    "chính sách bảo hành máy chiếu Epson",
    "phí giao hàng và thời gian vận chuyển",
    "số lượng đặt hàng tối thiểu SKU-EP-2250",
    "quy trình xử lý công nợ quá hạn",
    "hợp đồng phân phối với khách hàng Nam Phát",
    "báo giá thiết bị đo lường công nghiệp quý ba",
    "điều kiện đặt cọc 30 phần trăm",
    "thời hạn bảo hành 24 tháng",
    "chính sách đổi trả hàng lỗi",
]


@pytest.mark.qdrant
@pytest.mark.parametrize("query", TRUY_VAN_TIENG_VIET)
def test_search_tra_ve_chunk_score_metadata(live_client, cfg, embedder, query):
    results = search(query, k=5, cfg=cfg, client=live_client, embedder=embedder)
    assert 1 <= len(results) <= 5
    for r in results:
        assert isinstance(r, SearchResult)
        assert isinstance(r.chunk, str) and r.chunk.strip()
        assert isinstance(r.score, float)
        assert "doc_id" in r.metadata
        assert "source" in r.metadata
        assert "text" not in r.metadata, "text đã tách ra r.chunk, không nên trùng trong metadata"


@pytest.mark.qdrant
def test_search_sap_xep_giam_dan_theo_score(live_client, cfg, embedder):
    results = search(
        "điều khoản thanh toán trả chậm bao nhiêu ngày",
        k=5,
        cfg=cfg,
        client=live_client,
        embedder=embedder,
    )
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.qdrant
def test_k_gioi_han_dung_so_luong(live_client, cfg, embedder):
    results = search("bảo hành", k=2, cfg=cfg, client=live_client, embedder=embedder)
    assert len(results) <= 2


# --------------------------------------------------------------------------- #
# is_delivered() — nguồn của trường `delivered`
# --------------------------------------------------------------------------- #


@pytest.mark.qdrant
def test_delivered_true_khi_tai_lieu_nhiem_doc_lot_top_k(live_client, cfg, embedder):
    run_id = f"test-retr-{uuid.uuid4().hex[:8]}"
    noi_dung = (
        "THÔNG BÁO NỘI BỘ MÃ RUN " + run_id + ". "
        "Đây là tài liệu nhiễm độc thử nghiệm cho bài kiểm retriever, "
        "nhắc tới cụm từ đặc trưng zzyx-kiem-thu-w2-06 để không trùng nội dung nền."
    )
    try:
        n = inject_doc(run_id, noi_dung, cfg=cfg, client=live_client, embedder=embedder)
        assert n >= 1
        assert is_delivered(
            run_id=run_id,
            query="zzyx-kiem-thu-w2-06 thông báo nội bộ",
            k=5,
            cfg=cfg,
            client=live_client,
            embedder=embedder,
        )
    finally:
        cleanup_doc(run_id, cfg=cfg, client=live_client)


@pytest.mark.qdrant
def test_delivered_false_sau_khi_cleanup(live_client, cfg, embedder):
    run_id = f"test-retr-{uuid.uuid4().hex[:8]}"
    noi_dung = "Tài liệu nhiễm độc thử nghiệm mã " + run_id + " zzyx-kiem-thu-cleanup."
    inject_doc(run_id, noi_dung, cfg=cfg, client=live_client, embedder=embedder)
    cleanup_doc(run_id, cfg=cfg, client=live_client)

    assert not is_delivered(
        run_id=run_id,
        query="zzyx-kiem-thu-cleanup",
        k=5,
        cfg=cfg,
        client=live_client,
        embedder=embedder,
    )


@pytest.mark.qdrant
def test_delivered_false_khi_run_id_khong_khop_noi_dung_khong_lien_quan(
    live_client, cfg, embedder
):
    """Truy vấn lệch hẳn chủ đề tài liệu chèn thì không lọt top-k → delivered=False."""
    run_id = f"test-retr-{uuid.uuid4().hex[:8]}"
    noi_dung = "Tài liệu nhiễm độc mã " + run_id + " về chủ đề zzyx-hoan-toan-khac-biet."
    try:
        inject_doc(run_id, noi_dung, cfg=cfg, client=live_client, embedder=embedder)
        assert not is_delivered(
            run_id=run_id,
            query="chính sách bảo hành máy chiếu Epson 24 tháng",
            k=5,
            cfg=cfg,
            client=live_client,
            embedder=embedder,
        )
    finally:
        cleanup_doc(run_id, cfg=cfg, client=live_client)


@pytest.mark.qdrant
def test_delivered_run_id_rong_bi_tu_choi(live_client, cfg, embedder):
    with pytest.raises(ValueError):
        is_delivered(
            run_id="", query="bất kỳ truy vấn nào", cfg=cfg, client=live_client, embedder=embedder
        )
