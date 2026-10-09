"""Ingest pipeline + chèn/xóa tài liệu nhiễm độc theo run (kênh K1).

Bối cảnh: với ~2.700 run, nếu mỗi run nạp lại
40 tài liệu nền thì riêng khâu ingest đã mất hơn 20 giờ. Nên kiến trúc ở đây
tách đôi:

  * **Collection nền** — dựng MỘT LẦN từ `src/rag/corpus/` (40 file), giữ
    nguyên suốt thực nghiệm. Không run nào được đụng vào.
  * **Tài liệu chèn theo run** — `inject_doc(run_id, content)` thêm một tài
    liệu nhiễm độc mang `run_id` riêng, `cleanup_doc(run_id)` xóa đúng nó đi.
    Chi phí không phụ thuộc kích thước collection nền.

Cả hai nằm chung một collection, phân biệt bằng payload `source`
(`base` / `inject`). Tách thành hai collection sẽ buộc retriever truy vấn hai
chỗ rồi trộn điểm số — làm hỏng ý nghĩa của top-k, mà top-k lại chính là nguồn
của trường `delivered` (trace schema, STT-19).

Cách dùng (`src/` phải nằm trên PYTHONPATH — pytest tự lo qua `pyproject.toml`,
còn chạy tay thì phải khai báo; dùng `make kb-build` / `make kb-bench` cho gọn):

    # dựng nền, chạy một lần sau khi `make up`
    PYTHONPATH=src uv run python -m rag.ingest build

    # kiểm ngưỡng thời gian của DoD
    PYTHONPATH=src uv run python -m rag.ingest bench
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from qdrant_client import QdrantClient, models

if __package__ in (None, ""):  # chạy trực tiếp `python src/rag/ingest.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag.embedder import Embedder, get_embedder  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = REPO_ROOT / "config" / "rag.yaml"
CORPUS_DIR = REPO_ROOT / "src" / "rag" / "corpus"
MANIFEST_PATH = REPO_ROOT / "src" / "rag" / "corpus_manifest.csv"

#: Namespace cố định để sinh point-id ổn định giữa các lần chạy. Cùng một
#: (doc_id, chunk_index) luôn cho ra cùng một UUID, nên ingest lại tài liệu đã
#: có sẽ GHI ĐÈ đúng điểm cũ thay vì nhân bản nó.
_ID_NAMESPACE = uuid.UUID("6f9e1f7a-3d24-4a5e-9d0f-2b7c1a8e4c31")


# --------------------------------------------------------------------------- #
# Cấu hình
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RagConfig:
    model: str
    qdrant_url: str
    collection: str
    distance: str
    max_tokens: int
    overlap_tokens: int
    base_marker: str
    inject_marker: str

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> RagConfig:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(
            model=raw["embedding"]["model"],
            qdrant_url=raw["qdrant"]["url"],
            collection=raw["qdrant"]["collection"],
            distance=raw["qdrant"]["distance"],
            max_tokens=raw["chunking"]["max_tokens"],
            overlap_tokens=raw["chunking"]["overlap_tokens"],
            base_marker=raw["injection"]["base_marker"],
            inject_marker=raw["injection"]["inject_marker"],
        )


# --------------------------------------------------------------------------- #
# Đọc tài liệu
# --------------------------------------------------------------------------- #


def read_pdf(path: Path) -> str:
    from pypdf import PdfReader

    return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)


def read_docx(path: Path) -> str:
    import docx

    doc = docx.Document(str(path))
    parts = [p.text for p in doc.paragraphs]
    # Bảng trong hợp đồng chứa điều khoản giá và thời hạn — bỏ qua là mất đúng
    # phần mà các tác vụ chở CT-04/CT-05 hỏi tới.
    for table in doc.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text.strip() for cell in row.cells))
    return "\n".join(parts)


def read_markdown(path: Path) -> str:
    return path.read_text(encoding="utf-8")


_READERS = {".pdf": read_pdf, ".docx": read_docx, ".md": read_markdown}


def read_document(path: Path) -> str:
    reader = _READERS.get(path.suffix.lower())
    if reader is None:
        raise ValueError(f"Không có bộ đọc cho đuôi {path.suffix!r}: {path}")
    text = reader(path)
    if not text.strip():
        raise ValueError(f"Đọc ra chuỗi rỗng: {path} — kiểm lại file nguồn")
    return text


# --------------------------------------------------------------------------- #
# Chunk
# --------------------------------------------------------------------------- #


def chunk_text(
    text: str,
    embedder: Embedder,
    max_tokens: int,
    overlap_tokens: int,
) -> list[str]:
    """Cắt `text` thành các đoạn ≤ `max_tokens` token, chồng lấn `overlap_tokens`.

    Đếm bằng tokenizer của CHÍNH model embedding, không bằng ký tự hay khoảng
    trắng: `multilingual-e5-large` cắt cụt ở 512 token và không báo lỗi, nên
    chunk "512 từ" sẽ mất phần đuôi mà không ai biết. Tiếng Việt có dấu tốn
    nhiều token hơn tiếng Anh, càng không suy ra được từ số ký tự.
    """
    if overlap_tokens >= max_tokens:
        raise ValueError(
            f"overlap_tokens ({overlap_tokens}) phải nhỏ hơn max_tokens ({max_tokens}), "
            "nếu không cửa sổ trượt sẽ không tiến lên và vòng lặp không dừng"
        )

    tokenizer = embedder.chunking_tokenizer
    # add_special_tokens=False: [CLS]/[SEP] do model tự thêm lúc encode; đếm cả
    # chúng ở đây sẽ làm mỗi chunk dài hơn giới hạn đúng 2 token.
    ids = tokenizer.encode(text, add_special_tokens=False).ids
    if not ids:
        return []

    step = max_tokens - overlap_tokens
    chunks: list[str] = []
    for start in range(0, len(ids), step):
        window = ids[start : start + max_tokens]
        if not window:
            break
        chunk = _decode_vua_gioi_han(tokenizer, window, max_tokens)
        if chunk:
            chunks.append(chunk)
        if start + max_tokens >= len(ids):
            break
    return chunks


def _decode_vua_gioi_han(tokenizer, window: list[int], max_tokens: int) -> str:
    """Decode `window` thành chuỗi mà encode lại vẫn ≤ `max_tokens` token.

    Tokenizer subword **không round-trip theo số lượng token**: cắt đúng 512 id
    rồi decode, encode lại có thể ra 513 vì ranh giới subword và khoảng trắng
    dịch đi. Chênh một token nghe nhỏ, nhưng hệ quả là model lặng lẽ cắt cụt
    đuôi mỗi chunk lúc embed — mất dữ liệu không có thông báo, đúng loại lỗi mà
    cả pipeline này đang cố tránh.

    Nên ở đây decode rồi ĐO LẠI, thừa thì bỏ bớt id cuối và thử lại. Thực tế
    chỉ lặp một, hai vòng.
    """
    while window:
        chunk = tokenizer.decode(window).strip()
        if not chunk:
            return ""
        if len(tokenizer.encode(chunk, add_special_tokens=False).ids) <= max_tokens:
            return chunk
        window = window[:-1]
    return ""


# --------------------------------------------------------------------------- #
# Qdrant
# --------------------------------------------------------------------------- #


def point_id(doc_id: str, chunk_index: int) -> str:
    return str(uuid.uuid5(_ID_NAMESPACE, f"{doc_id}::{chunk_index}"))


def connect(cfg: RagConfig) -> QdrantClient:
    return QdrantClient(url=cfg.qdrant_url)


def ensure_collection(client: QdrantClient, cfg: RagConfig, embedder: Embedder) -> None:
    """Tạo collection nếu chưa có, kèm payload index cho `run_id` và `source`.

    Payload index là thứ làm `cleanup_doc` rẻ: không có index, Qdrant phải quét
    toàn bộ collection để tìm điểm khớp `run_id`, và chi phí xóa sẽ tăng theo
    kích thước kho nền — đúng thứ mà lỗ hổng C1 muốn tránh.
    """
    existing = {c.name for c in client.get_collections().collections}
    if cfg.collection not in existing:
        client.create_collection(
            collection_name=cfg.collection,
            vectors_config=models.VectorParams(
                size=embedder.dim,
                distance=models.Distance[cfg.distance.upper()],
            ),
        )
    for field in ("run_id", "source", "doc_id"):
        client.create_payload_index(
            collection_name=cfg.collection,
            field_name=field,
            field_schema=models.PayloadSchemaType.KEYWORD,
            wait=True,
        )


def _upsert_chunks(
    client: QdrantClient,
    cfg: RagConfig,
    embedder: Embedder,
    *,
    doc_id: str,
    chunks: list[str],
    payload_extra: dict[str, Any],
) -> int:
    if not chunks:
        return 0
    vectors = embedder.embed_passages(chunks)
    points = [
        models.PointStruct(
            id=point_id(doc_id, i),
            vector=vec,
            payload={
                "doc_id": doc_id,
                "chunk_index": i,
                "text": chunk,
                **payload_extra,
            },
        )
        # strict=True: lệch độ dài giữa chunk và vector là lỗi nghiêm trọng
        # (mất chunk hoặc lệch cặp text-vector), phải nổ chứ không cắt ngắn.
        for i, (chunk, vec) in enumerate(zip(chunks, vectors, strict=True))
    ]
    client.upsert(collection_name=cfg.collection, points=points, wait=True)
    return len(points)


# --------------------------------------------------------------------------- #
# Collection nền
# --------------------------------------------------------------------------- #


def iter_corpus_files(corpus_dir: Path = CORPUS_DIR) -> Iterable[Path]:
    for path in sorted(corpus_dir.iterdir()):
        if path.suffix.lower() in _READERS:
            yield path


def build_base_collection(
    cfg: RagConfig | None = None,
    *,
    client: QdrantClient | None = None,
    embedder: Embedder | None = None,
    recreate: bool = False,
) -> dict[str, int]:
    """Dựng collection nền từ 40 tài liệu sạch. Chạy MỘT LẦN.

    `recreate=True` xóa collection trước khi dựng — chỉ dùng khi đổi model
    embedding (số chiều đổi) hoặc đổi tham số chunk. Giữa một loạt thực nghiệm
    thì không, vì dựng lại nền làm mọi run trước đó không so sánh được với run
    sau.
    """
    cfg = cfg or RagConfig.load()
    embedder = embedder or get_embedder(cfg.model)
    client = client or connect(cfg)

    if recreate and cfg.collection in {c.name for c in client.get_collections().collections}:
        client.delete_collection(cfg.collection)
    ensure_collection(client, cfg, embedder)

    stats: dict[str, int] = {"files": 0, "chunks": 0}
    for path in iter_corpus_files():
        text = read_document(path)
        chunks = chunk_text(text, embedder, cfg.max_tokens, cfg.overlap_tokens)
        n = _upsert_chunks(
            client,
            cfg,
            embedder,
            doc_id=path.name,
            chunks=chunks,
            payload_extra={
                "source": cfg.base_marker,
                "run_id": "",  # rỗng chứ không thiếu: filter theo run_id vẫn khớp kiểu
                "file_type": path.suffix.lstrip("."),
            },
        )
        stats["files"] += 1
        stats["chunks"] += n
    return stats


# --------------------------------------------------------------------------- #
# Chèn / xóa theo run
# --------------------------------------------------------------------------- #


def inject_doc(
    run_id: str,
    content: str,
    *,
    cfg: RagConfig | None = None,
    client: QdrantClient | None = None,
    embedder: Embedder | None = None,
    doc_id: str | None = None,
    payload_extra: dict[str, Any] | None = None,
) -> int:
    """Chèn một tài liệu nhiễm độc mang `run_id`. Trả về số chunk đã ghi."""
    if not run_id:
        raise ValueError("run_id rỗng — cleanup_doc('') sẽ không xóa được gì")
    cfg = cfg or RagConfig.load()
    embedder = embedder or get_embedder(cfg.model)
    client = client or connect(cfg)

    chunks = chunk_text(content, embedder, cfg.max_tokens, cfg.overlap_tokens)
    return _upsert_chunks(
        client,
        cfg,
        embedder,
        doc_id=doc_id or f"inject::{run_id}",
        chunks=chunks,
        payload_extra={
            "source": cfg.inject_marker,
            "run_id": run_id,
            "file_type": "injected",
            **(payload_extra or {}),
        },
    )


def cleanup_doc(
    run_id: str,
    *,
    cfg: RagConfig | None = None,
    client: QdrantClient | None = None,
) -> None:
    """Xóa mọi điểm thuộc `run_id`.

    Lọc kèm `source = inject` chứ không chỉ `run_id`: nếu một lúc nào đó tài
    liệu nền vô tình mang `run_id` không rỗng, lệnh này vẫn không đụng được
    vào nền. Xóa nhầm nền giữa loạt thực nghiệm là hỏng cả lô.
    """
    if not run_id:
        raise ValueError("run_id rỗng — từ chối xóa để tránh quét trúng tài liệu nền")
    cfg = cfg or RagConfig.load()
    client = client or connect(cfg)
    client.delete(
        collection_name=cfg.collection,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="run_id", match=models.MatchValue(value=run_id)
                    ),
                    models.FieldCondition(
                        key="source", match=models.MatchValue(value=cfg.inject_marker)
                    ),
                ]
            )
        ),
        wait=True,
    )


@contextmanager
def injected_doc(
    run_id: str,
    content: str,
    *,
    cfg: RagConfig | None = None,
    client: QdrantClient | None = None,
    embedder: Embedder | None = None,
    doc_id: str | None = None,
    payload_extra: dict[str, Any] | None = None,
):
    """`inject_doc` + `cleanup_doc` bảo đảm chạy, kể cả khi thân `with` ném lỗi.

    Vì sao cần: `inject_doc(...)` rồi `cleanup_doc(...)` viết thẳng hai dòng thì
    một exception ở giữa (model timeout, gateway 5xx, Ctrl-C) sẽ để tài liệu
    nhiễm độc **ở lại collection vĩnh viễn**. Với ~2.700 run, một run hỏng là đủ
    làm mọi run sau đó truy hồi trúng payload của run trước — nhiễm chéo âm
    thầm, và số ASR thu được sẽ không còn nghĩa.

    Đã gặp thật khi soát W2 (07/08/2026): một lần gọi sai chữ ký `is_delivered`
    ném `AttributeError` giữa chừng và để lại 1 điểm rác trong `kb`.

        with injected_doc(run_id, payload_text) as n_chunks:
            ...  # chạy agent, chấm điểm
        # tới đây tài liệu đã bị xóa dù thân with thành công hay không
    """
    n = inject_doc(
        run_id,
        content,
        cfg=cfg,
        client=client,
        embedder=embedder,
        doc_id=doc_id,
        payload_extra=payload_extra,
    )
    try:
        yield n
    finally:
        cleanup_doc(run_id, cfg=cfg, client=client)


def purge_injected(
    *,
    cfg: RagConfig | None = None,
    client: QdrantClient | None = None,
) -> int:
    """Xóa MỌI tài liệu có `source = inject`, bất kể `run_id`. Trả về số điểm đã xóa.

    Lưới an toàn cho rác của những run đã chết trước khi kịp dọn. Chạy **giữa
    hai lô**, không chạy giữa chừng một lô — nó không phân biệt được tài liệu
    của run đang chạy với rác cũ.
    """
    cfg = cfg or RagConfig.load()
    client = client or connect(cfg)
    n = count_points(cfg=cfg, client=client, source=cfg.inject_marker)
    if n:
        client.delete(
            collection_name=cfg.collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="source", match=models.MatchValue(value=cfg.inject_marker)
                        )
                    ]
                )
            ),
            wait=True,
        )
    return n


def count_points(
    *,
    cfg: RagConfig | None = None,
    client: QdrantClient | None = None,
    run_id: str | None = None,
    source: str | None = None,
) -> int:
    cfg = cfg or RagConfig.load()
    client = client or connect(cfg)
    must: list[models.FieldCondition] = []
    if run_id is not None:
        must.append(models.FieldCondition(key="run_id", match=models.MatchValue(value=run_id)))
    if source is not None:
        must.append(models.FieldCondition(key="source", match=models.MatchValue(value=source)))
    return client.count(
        collection_name=cfg.collection,
        count_filter=models.Filter(must=must) if must else None,
        exact=True,
    ).count


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

#: Ngưỡng chèn + xóa một tài liệu / rủi ro R8.
PREP_BUDGET_S = 10.0


def bench_inject_cleanup(sample: str | None = None) -> dict[str, float]:
    """Đo khâu chuẩn bị KB của một run: chèn 1 tài liệu rồi xóa nó.

    Model được nạp TRƯỚC khi bấm giờ, đúng như lúc chạy thật: một tiến trình
    thực nghiệm nạp model một lần rồi lặp hàng nghìn run. Tính cả thời gian nạp
    model vào ngưỡng 10 giây sẽ là đo sai phép đo.
    """
    cfg = RagConfig.load()
    embedder = get_embedder(cfg.model)
    client = connect(cfg)
    ensure_collection(client, cfg, embedder)

    content = sample or (
        "BÁO GIÁ SỐ BG-2026-099\n"
        "Kính gửi Quý khách hàng,\n"
        "Bảng giá thiết bị quý III/2026 đính kèm dưới đây.\n"
        + ("Điều khoản thanh toán: trả chậm 30 ngày kể từ ngày giao hàng. " * 40)
    )
    run_id = f"bench-{uuid.uuid4().hex[:8]}"

    t0 = time.perf_counter()
    n = inject_doc(run_id, content, cfg=cfg, client=client, embedder=embedder)
    t1 = time.perf_counter()
    cleanup_doc(run_id, cfg=cfg, client=client)
    t2 = time.perf_counter()

    return {
        "chunks": float(n),
        "inject_s": t1 - t0,
        "cleanup_s": t2 - t1,
        "total_s": t2 - t0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_build = sub.add_parser("build", help="dựng collection nền từ 40 tài liệu")
    p_build.add_argument(
        "--recreate",
        action="store_true",
        help="XÓA collection rồi dựng lại — chỉ dùng khi đổi model/tham số chunk",
    )
    sub.add_parser("bench", help="đo thời gian chèn+xóa 1 tài liệu (DoD < 10 giây)")
    sub.add_parser("stats", help="đếm điểm theo source")

    args = parser.parse_args()
    cfg = RagConfig.load()

    if args.cmd == "build":
        t0 = time.perf_counter()
        stats = build_base_collection(cfg, recreate=args.recreate)
        print(
            f"Đã dựng nền: {stats['files']} file → {stats['chunks']} chunk "
            f"trong {time.perf_counter() - t0:.1f}s (collection {cfg.collection!r})"
        )
        return 0

    if args.cmd == "bench":
        r = bench_inject_cleanup()
        print(
            f"chèn {int(r['chunks'])} chunk: {r['inject_s']:.2f}s · "
            f"xóa: {r['cleanup_s']:.2f}s · tổng: {r['total_s']:.2f}s "
            f"(ngưỡng {PREP_BUDGET_S:.0f}s)"
        )
        return 0 if r["total_s"] < PREP_BUDGET_S else 1

    if args.cmd == "stats":
        print(f"nền   : {count_points(cfg=cfg, source=cfg.base_marker)} điểm")
        print(f"chèn  : {count_points(cfg=cfg, source=cfg.inject_marker)} điểm")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
