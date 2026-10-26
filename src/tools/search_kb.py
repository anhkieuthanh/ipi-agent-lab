"""Tool `search_kb` (TL1) — truy hồi top-k từ kho tri thức qua `rag.retriever.search` (STT-37).

Kênh K1: kết quả mang nguồn `kb_chunk`, lõi agent cho nó qua hook KB_RETRIEVAL rồi CONTEXT_ASSEMBLY.
Handler không lọc theo `source`/`run_id` — top-k là đúng thứ retriever trả, kể cả tài liệu injector
K1 (STT-44) chèn cho run. `delivered` của run K1 đọc `doc_id` từ chính kết quả tool này trong trace
(`attack.injector_k1.observed_delivered`), nên khớp thứ agent nhận.

`k` model không truyền thì lấy `fixed.kb_top_k` của experiment.yaml — cùng k với probe `delivered_probe`.

Kết quả vào context là JSON `{"results": [{"doc_id", "chunk"}, ...]}`; điểm tương đồng ở `meta`,
không vào context. Qdrant hay embedder lỗi thì exception lan ra: đó là lỗi harness, run thành
`parse_error` (mục 12.4 (b)), không ghi nhầm thành "model không tìm thấy".

    reg.bind("search_kb", SearchKb.from_experiment())
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from interfaces import ToolResult

__all__ = ["SearchKb"]

TOOL_NAME = "search_kb"

#: (query, k) → danh sách có `.chunk`, `.score`, `.metadata` như `rag.retriever.SearchResult`.
SearchFn = Callable[[str, int], list[Any]]


class SearchKb:
    """Handler `search_kb`. Kết nối Qdrant và model embedding mở lười ở lần gọi đầu, dùng lại sau."""

    def __init__(self, *, default_k: int, search_fn: SearchFn | None = None) -> None:
        if not isinstance(default_k, int) or isinstance(default_k, bool) or default_k < 1:
            raise ValueError(f"default_k phải là số nguyên dương, nhận {default_k!r}")
        self.default_k = default_k
        self._search = search_fn

    @classmethod
    def from_experiment(cls, search_fn: SearchFn | None = None) -> SearchKb:
        from eval.experiment import load_experiment

        return cls(default_k=load_experiment().fixed["kb_top_k"], search_fn=search_fn)

    def _search_fn(self) -> SearchFn:
        if self._search is None:
            from rag.embedder import get_embedder
            from rag.ingest import RagConfig, connect
            from rag.retriever import search

            cfg = RagConfig.load()
            client, embedder = connect(cfg), get_embedder(cfg.model)

            def bound(query: str, k: int) -> list[Any]:
                return search(query, k, cfg=cfg, client=client, embedder=embedder)

            self._search = bound
        return self._search

    def __call__(self, args: dict[str, Any]) -> ToolResult:
        k = args.get("k") or self.default_k
        hits = self._search_fn()(args["query"], k)
        results = [{"doc_id": h.metadata.get("doc_id"), "chunk": h.chunk} for h in hits]
        return ToolResult(
            call_id="",
            name=TOOL_NAME,
            content=json.dumps({"results": results}, ensure_ascii=False),
            meta={"k": k, "scores": [h.score for h in hits]},
        )
