"""Lớp bọc mô hình embedding cho kho tri thức (kênh K1).

Vì sao có file này thay vì gọi thẳng `fastembed.TextEmbedding`:

1. **Prefix của họ E5 là bắt buộc và fastembed KHÔNG tự thêm.** Model
   `intfloat/multilingual-e5-large` được huấn luyện với hai tiền tố `query: `
   và `passage: `; bỏ tiền tố đi thì vector vẫn sinh ra bình thường, không lỗi,
   chỉ là chất lượng truy hồi tụt — một lỗi im lặng đúng kiểu khó phát hiện
   nhất. Đã kiểm bản fastembed đang ghim: `passage_embed()` mặc định gọi thẳng
   `embed()`, và trong toàn bộ package không có chuỗi `"passage: "` nào. Vì vậy
   mọi lời gọi embedding trong lab đi qua đây, không ai gọi trực tiếp.

2. **Ingest và truy hồi phải dùng chung một model và một quy ước tiền tố.**
   Tách ra một chỗ để `ingest.py` và `retriever.py` không thể
   lệch nhau.

3. **Đổi model chỉ bằng đổi một chuỗi** — xem `config/rag.yaml`. Số chiều vector
   được đọc từ chính model chứ không viết cứng, nên đổi model không kéo theo
   sửa code khởi tạo collection.

Vì sao không dùng `bge-m3`: bản
`fastembed` hiện hành không hỗ trợ `bge-m3` ở bất kỳ dạng nào (dense, sparse,
late-interaction), nên lab dùng `intfloat/multilingual-e5-large` — cùng 1024
chiều, cùng nhóm đa ngữ có tiếng Việt.

**Phiên bản fastembed là một phần của tính tái lập.** Bản đang ghim dùng mean
pooling cho họ E5; bản ≤ 0.5.1 dùng CLS pooling. Cùng một câu, hai bản cho ra
hai vector khác nhau — nâng `fastembed` sau khi đã dựng collection nền sẽ làm
truy vấn mới không cùng không gian với vector cũ, mà Qdrant không hề báo lỗi.
Nâng phiên bản ⇒ phải dựng lại nền (`ingest.py build --recreate`).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache

from fastembed import TextEmbedding

#: Model mặc định. Đổi ở đây (hoặc qua `config/rag.yaml`) là đổi toàn hệ thống.
DEFAULT_MODEL = "intfloat/multilingual-e5-large"

#: Tiền tố theo họ model. Key là tiền tố khớp tên model, value là (query, passage).
#: Model không khớp key nào thì không thêm gì — đó là hành vi đúng cho các họ
#: không dùng tiền tố (bge-*, gte-*, snowflake-*), KHÔNG phải fallback im lặng.
_PREFIX_RULES: dict[str, tuple[str, str]] = {
    # Họ E5 (intfloat/*e5*): bắt buộc, xem model card.
    "e5": ("query: ", "passage: "),
    # Họ nomic: dùng nhãn tác vụ thay vì query/passage.
    "nomic-embed": ("search_query: ", "search_document: "),
}


def resolve_prefixes(model_name: str) -> tuple[str, str]:
    """Trả về (tiền tố truy vấn, tiền tố tài liệu) cho `model_name`."""
    lowered = model_name.lower()
    for key, prefixes in _PREFIX_RULES.items():
        if key in lowered:
            return prefixes
    return ("", "")


@dataclass(frozen=True)
class EmbeddingSpec:
    """Thông tin của model đang dùng — ghi vào metadata collection để truy nguồn.

    Nếu sau này đổi model mà quên dựng lại collection nền, so `model` và `dim`
    ở đây với payload đã lưu sẽ bắt được ngay, thay vì để vector hai không gian
    khác nhau nằm lẫn trong cùng một collection.
    """

    model: str
    dim: int
    query_prefix: str
    passage_prefix: str


class Embedder:
    """Bọc `TextEmbedding`, tự gắn tiền tố đúng cho từng loại văn bản."""

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self.model_name = model_name
        self._model = TextEmbedding(model_name)
        self.query_prefix, self.passage_prefix = resolve_prefixes(model_name)
        self._chunking_tokenizer = None
        # Lấy số chiều từ chính model thay vì viết cứng — đổi model là đổi số
        # chiều, và collection Qdrant phải khớp nếu không upsert sẽ lỗi.
        self.dim = len(next(iter(self._model.embed(["x"]))))

    @property
    def chunking_tokenizer(self):
        """Tokenizer dùng để ĐẾM token khi chia chunk — đã tắt truncation.

        Bẫy: tokenizer đi kèm model bật sẵn `truncation.max_length = 512`, nên
        `encode()` một tài liệu dài chỉ trả về 512 token đầu tiên và **im lặng
        vứt phần còn lại**. Nếu chia chunk bằng chính nó thì mỗi file dài chỉ
        sinh ra đúng một chunk, và 40 tài liệu vào kho chỉ còn phần mở đầu —
        hỏng toàn bộ truy hồi mà không có lỗi nào được ném ra.

        Vì vậy ở đây dùng một BẢN SAO độc lập đã gọi `no_truncation()`. Không
        sửa tokenizer gốc: lúc embed thì cắt ở 512 là hành vi đúng và cần giữ,
        vì `chunk_text` đã bảo đảm mỗi chunk vừa trong giới hạn.
        """
        if self._chunking_tokenizer is None:
            from tokenizers import Tokenizer

            clone = Tokenizer.from_str(self._model.model.tokenizer.to_str())
            clone.no_truncation()
            clone.no_padding()
            self._chunking_tokenizer = clone
        return self._chunking_tokenizer

    @property
    def spec(self) -> EmbeddingSpec:
        return EmbeddingSpec(
            model=self.model_name,
            dim=self.dim,
            query_prefix=self.query_prefix,
            passage_prefix=self.passage_prefix,
        )

    def embed_passages(self, texts: Iterable[str]) -> list[list[float]]:
        """Nhúng các đoạn tài liệu (dùng khi ingest)."""
        prefixed = [f"{self.passage_prefix}{t}" for t in texts]
        return [v.tolist() for v in self._model.embed(prefixed)]

    def embed_query(self, text: str) -> list[float]:
        """Nhúng một truy vấn (dùng khi tìm kiếm)."""
        prefixed = f"{self.query_prefix}{text}"
        return next(iter(self._model.embed([prefixed]))).tolist()


@lru_cache(maxsize=4)
def get_embedder(model_name: str = DEFAULT_MODEL) -> Embedder:
    """Dùng lại một instance cho mỗi model.

    Nạp model tốn vài giây và vài trăm MB RAM; ngưỡng "<10 giây mỗi run" của
    Ngưỡng chèn + xóa < 10 giây chỉ đạt được nếu model đã nằm sẵn trong tiến trình, không nạp lại
    mỗi lần chèn tài liệu.
    """
    return Embedder(model_name)
