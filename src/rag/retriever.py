"""Truy hồi kho tri thức (kênh K1).

`search()` là điểm gọi duy nhất mà lớp attack (injector K1, STT-44) và lớp
đo lường dùng để lấy top-k từ collection `kb`. `is_delivered()` xây trên đúng
kết quả của `search()` — không truy vấn riêng — để "có nằm trong top-k hay
không" luôn khớp với những gì agent thực sự nhận được.

Dùng chung `RagConfig`/`Embedder` với `ingest.py`: đổi model hay tiền tố ở một
chỗ, ingest và retriever không thể lệch nhau (xem `embedder.py`).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from qdrant_client import QdrantClient

if __package__ in (None, ""):  # chạy trực tiếp `python src/rag/retriever.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag.embedder import Embedder, get_embedder  # noqa: E402
from rag.ingest import RagConfig, connect  # noqa: E402


@dataclass(frozen=True)
class SearchResult:
    """Một kết quả truy hồi. `metadata` là payload Qdrant trừ `text`."""

    chunk: str
    score: float
    metadata: dict


def search(
    query: str,
    k: int = 5,
    *,
    cfg: RagConfig | None = None,
    client: QdrantClient | None = None,
    embedder: Embedder | None = None,
) -> list[SearchResult]:
    """Truy hồi `k` chunk gần nhất với `query` từ collection `kb`.

    Không lọc theo `source`/`run_id`: collection nền và tài liệu chèn theo run
    nằm chung một chỗ (xem `ingest.py`), nên top-k phản ánh đúng những gì
    agent thật sự nhận được — kể cả khi tài liệu nhiễm độc lọt vào.
    """
    cfg = cfg or RagConfig.load()
    embedder = embedder or get_embedder(cfg.model)
    client = client or connect(cfg)

    vector = embedder.embed_query(query)
    hits = client.query_points(
        collection_name=cfg.collection,
        query=vector,
        limit=k,
    ).points

    results = []
    for hit in hits:
        payload = dict(hit.payload or {})
        chunk = payload.pop("text", "")
        results.append(SearchResult(chunk=chunk, score=hit.score, metadata=payload))
    return results


def is_delivered(
    *,
    run_id: str,
    query: str,
    k: int = 5,
    cfg: RagConfig | None = None,
    client: QdrantClient | None = None,
    embedder: Embedder | None = None,
) -> bool:
    """Tài liệu nhiễm độc của `run_id` có nằm trong top-k của `query` không.

    Đây là nguồn của trường `delivered` (trace schema STT-19; dùng ở STT-44):
    `delivered=False` không tính là tấn công thất bại — nó rời khỏi mẫu tính
    ASR có điều kiện, chứ không rời mẫu ASR đầu-cuối.

    **Hai tham số đều bắt buộc theo tên.** Trước đây chúng là tham số vị trí
    `(run_id, query)`, mà cả hai cùng kiểu `str` nên gọi đảo thứ tự vẫn chạy
    và **trả `False` im lặng** — không `run_id` nào trùng nội dung câu hỏi.
    Hậu quả: `delivered` luôn False ⇒ mọi run rời khỏi mẫu ASR có điều kiện ⇒
    đúng lỗ hổng A2 mà trace schema (STT-19) dựng trường này để chặn, chỉ khác là hỏng từ phía
    đo chứ không từ phía tấn công. Ép keyword-only để lỗi đó không xảy ra được.
    """
    if not run_id:
        raise ValueError("run_id rỗng — không tài liệu nào mang run_id rỗng để khớp")
    results = search(query, k, cfg=cfg, client=client, embedder=embedder)
    return any(r.metadata.get("run_id") == run_id for r in results)
