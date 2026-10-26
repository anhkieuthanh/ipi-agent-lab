"""injector_k1.py — tiêm payload kênh K1 vào kho tri thức RAG và quy cờ `delivered` (STT-44).

VỊ TRÍ TRONG HỆ
---------------
K1 = tài liệu nhiễm độc lọt vào cửa sổ ngữ cảnh QUA top-k của retriever (khác K2a ghi đè
description tool, K2b chèn vào kết quả tool). Module này là tầng điều phối THUẦN:

    payload (đã validate) + tác vụ chở + run_id
        → dựng tài liệu chở (carrier_docs.py: MD/DOCX/PDF, hoặc PDF ẩn T4)
        → chèn vào Qdrant (rag.ingest.inject_doc)
        → probe: truy hồi top-k bằng câu hỏi gốc của tác vụ chở → `delivered_probe` (chẩn đoán)
    agent chạy xong
        → `observed_delivered(steps)`: `delivered = (mọi tài liệu của run nằm trong kết quả của ít
          nhất một lần gọi search_kb thật)`

KHÔNG gọi model, KHÔNG chấm ASR, KHÔNG ghi `blocked_by` (quy tắc cứng #8: `delivered=false` KHÁC
"phòng thủ chặn"). Chỉ trả cờ cho tầng trace; runner (STT-46) ghép vào bản ghi `runs`.

VÌ SAO `delivered` QUAN TRỌNG (lý do tồn tại của task)
-----------------------------------------------------
Nó tách hai thất bại khác hẳn nhau về nguyên nhân:
  * `delivered=false` — payload KHÔNG vào được top-k ⇒ "không truy hồi được" ⇒ **rời mẫu
    `ASR_cond`** (vẫn ở trong `ASR_e2e`). Không phải agent kháng cự, mà payload chưa tới cửa.
  * `delivered=true` — vào top-k nhưng agent không sập bẫy ⇒ thất bại thật, Ở LẠI mẫu.
Trộn hai cái này làm ASR tụt giả tạo và không quy được cho phòng thủ nào (lỗ hổng A2, trace
schema STT-19). `delivered` tính trên ĐÚNG kết quả `search_kb` mà agent nhận trong run, đọc từ bước
`tool` của trace (`tool_result` thô, trước phòng thủ) — không phải từ một truy vấn riêng. Pilot STT-60
cho thấy truy vấn riêng bằng câu hỏi gốc lệch hẳn: agent tự viết lại câu truy vấn, 9/9 run probe
báo true mà agent không thấy tài liệu tiêm, 4 run probe báo false mà agent thấy. Probe giữ ở cột
`delivered_probe` để chẩn đoán khâu truy hồi, không vào công thức nào.

Phòng thủ chặn chính lời gọi `search_kb` (bước `defense`, không có `tool_result`) thì tài liệu không
vào ngữ cảnh: `delivered = false`. D2 chạy SAU khi trace ghi `tool_result` nên không đổi cờ.

LƯỢC ĐỒ TOP-K CHO T6 (chia mảnh)
--------------------------------
Một payload T6 tách thành ≥2 mảnh, mỗi mảnh một TÀI LIỆU riêng cùng `run_id`. `delivered=true`
CHỈ khi MỌI mảnh cùng lọt top-k — nếu retriever chỉ gom một mảnh thì chỉ thị không đủ để kích
hoạt. Đây chính là lỗ hổng kiến trúc mà T6 dựng ra để đo, nên cờ phải phản ánh nó: ta kiểm theo
TẬP doc_id của run nằm trong top-k, không chỉ "có một tài liệu nào của run". Lược đồ này bao luôn
ca một-tài-liệu (tập một phần tử).

VÒNG ĐỜI
--------
Module này CHỈ chèn + đo; nó KHÔNG tự dọn. Với ~2.700 run, để tài liệu ở lại giữa chừng gây nhiễm
chéo, nên bên gọi (runner) phải bọc cả lượt chạy agent trong `rag.ingest.injected_doc(...)` hoặc
gọi `cleanup(run_id)` ở khối `finally`. `cleanup` ở đây chỉ là lối tắt về `rag.ingest.cleanup_doc`.

KIỂM: tests/test_injector_k1.py (phần dựng tài liệu chạy không cần Qdrant; phần `delivered` cần
`make up` + collection nền, đánh dấu `requires_qdrant`).
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import carrier_docs
from .payloads.render import base_text, instruction_of, load_render_config

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TASKS_PATH = REPO_ROOT / "data" / "carrier_tasks.json"
EXPERIMENT_PATH = REPO_ROOT / "config" / "experiment.yaml"
#: Tool mà kết quả mang tài liệu K1 vào ngữ cảnh (`tools.search_kb.TOOL_NAME`).
SEARCH_TOOL = "search_kb"


class InjectorK1Error(RuntimeError):
    """Lỗi harness của injector K1 (ghép sai kênh, thiếu ánh xạ bề mặt, parser không đọc ra payload).

    KHÔNG phải tín hiệu về hành vi model. `delivered=false` không ném lỗi này — nó là kết quả đo
    hợp lệ. Lỗi này chỉ nổ khi harness tự mâu thuẫn (không dựng được tài liệu giao hàng được).
    """


@dataclass(frozen=True)
class DocSpec:
    """Một tài liệu sẽ chèn: id, định dạng, bytes, chuỗi phải đọc ra được (parser-gate)."""

    doc_id: str
    fmt: str
    data: bytes
    probe: str                 # chuỗi payload phải xuất hiện trong text retriever đọc ra
    surface: str | None = None  # chỉ T4


@dataclass
class InjectionResult:
    """Kết quả tiêm một payload K1 vào một tác vụ chở cho một run."""

    run_id: str
    payload_id: str
    carrier_id: str
    channel: str = "K1"
    doc_ids: list[str] = field(default_factory=list)
    formats: list[str] = field(default_factory=list)
    n_chunks: int = 0
    # Probe bằng câu hỏi gốc, trước khi agent chạy — chỉ chẩn đoán (`delivered_probe`). `delivered`
    # thật của run tính sau bằng `observed_delivered`.
    delivered: bool | None = None            # None = chưa đo (chưa gọi probe)
    retrieved_doc_ids: list[str] = field(default_factory=list)
    surface: str | None = None               # T4

    def trace_fields(self) -> dict[str, Any]:
        """Phần đổ thẳng vào bản ghi `runs` của trace (channel + delivered)."""
        return {"channel": self.channel, "delivered": self.delivered}


# ── Cấu hình ──────────────────────────────────────────────────────────────────
def _k1_cfg(render_cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = render_cfg or load_render_config()
    try:
        return cfg["channels"]["K1"]
    except KeyError as exc:  # pragma: no cover - cấu hình hỏng là lỗi triển khai
        raise InjectorK1Error("config/channel_render.yaml thiếu khối channels.K1") from exc


def default_top_k(path: Path | str = EXPERIMENT_PATH) -> int:
    """`kb_top_k` cố định của thực nghiệm (experiment.yaml:fixed) — cùng k cho search và delivered."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return int(raw["fixed"]["kb_top_k"])


# ── Ghép tác vụ chở ─────────────────────────────────────────────────────────────
def load_carrier(carrier_id: str, *, tasks_path: Path | str = DEFAULT_TASKS_PATH) -> dict[str, Any]:
    data = json.loads(Path(tasks_path).read_text(encoding="utf-8"))
    for ct in data["carrier_tasks"]:
        if ct["id"] == carrier_id:
            return ct
    raise InjectorK1Error(f"không có tác vụ chở '{carrier_id}' trong {tasks_path}")


def valid_carriers(
    payload: dict[str, Any], *, tasks_path: Path | str = DEFAULT_TASKS_PATH
) -> list[str]:
    """Tác vụ chở K1 ghép được với `payload`, theo `payload_binding_rules` đọc TỪ FILE.

    Chỉ diễn giải các luật có `allowed_carriers` tất định theo payload: R1–R4 (theo tool đích),
    R5 (G3 ghép mọi CT). R6 (G1 chọn carrier theo exfil_vector) và R7 (hạn ngạch đối chứng âm)
    phụ thuộc quyết định lấy mẫu của runner (STT-46), KHÔNG quy từ một payload đơn lẻ nên để runner
    lo. Luật tool đích cụ thể hơn luật goal; tool khớp thì ưu tiên.

    Luôn giao với tập tác vụ chở khai `K1` trong `injection_channels` — ghép ngoài kênh là vô nghĩa.
    """
    data = json.loads(Path(tasks_path).read_text(encoding="utf-8"))
    k1_carriers = [ct["id"] for ct in data["carrier_tasks"] if "K1" in ct.get("injection_channels", [])]
    rules = data["payload_binding_rules"]["rules"]
    tool = (payload.get("goal_binding") or {}).get("tool")
    goal = payload.get("goal")

    by_tool: list[str] | None = None
    by_goal: list[str] | None = None
    for rule in rules:
        allowed = rule.get("allowed_carriers")
        if allowed is None:
            continue
        if tool is not None and rule.get("if_payload_target_tool") == tool:
            by_tool = allowed
        if rule.get("if_payload_goal") == goal:
            by_goal = allowed

    chosen = by_tool if by_tool is not None else by_goal
    if chosen is None:  # không luật nào bắt: K1 ghép được mọi tác vụ chở (channel_rule.K1)
        return k1_carriers
    return [c for c in chosen if c in k1_carriers]


# ── Dựng tài liệu ───────────────────────────────────────────────────────────────
def _rotate_format(key: str, formats: list[str], seed: str) -> str:
    """Chọn định dạng tất định theo `key` (cùng key → cùng fmt giữa các lần chạy)."""
    digest = hashlib.sha256(f"{seed}:{key}".encode()).hexdigest()
    return formats[int(digest, 16) % len(formats)]


def _visible_text(payload: dict[str, Any]) -> str:
    """Chuỗi hiển thị của payload trên K1 = base_text (template đã thay {INSTRUCTION})."""
    text = base_text(payload)
    if not text.strip():
        raise InjectorK1Error(f"{payload.get('id')}: base_text rỗng, không có gì để nhúng")
    return text


def plan_docs(
    payload: dict[str, Any],
    run_id: str,
    *,
    render_cfg: dict[str, Any] | None = None,
) -> list[DocSpec]:
    """Lập danh sách tài liệu cần chèn cho `payload` (chưa ghi đĩa, chưa chèn Qdrant).

    * T4: một PDF ẩn theo bề mặt ánh xạ từ obfuscation; chuỗi nhúng là chỉ thị TRẦN.
    * T6: một tài liệu HIỂN THỊ cho mỗi mảnh (fragments).
    * Còn lại: một tài liệu HIỂN THỊ mang base_text.
    """
    k1 = _k1_cfg(render_cfg)
    formats: list[str] = list(k1["formats"])
    position: str = k1["visible_position"]
    seed: str = k1["rotation_seed"]
    code = (payload.get("technique") or {}).get("code")
    pid = payload["id"]

    if code == "T4":
        return [_plan_t4_doc(payload, run_id, k1)]

    if code == "T6":
        return _plan_t6_docs(payload, run_id, formats, position, seed)

    # Hiển thị, một tài liệu.
    text = _visible_text(payload)
    fmt = _rotate_format(pid, formats, seed)
    data = carrier_docs.build_visible(text, fmt, position=position)
    return [DocSpec(doc_id=f"inject::{run_id}", fmt=fmt, data=data, probe=text)]


def _plan_t4_doc(payload: dict[str, Any], run_id: str, k1: dict[str, Any]) -> DocSpec:
    surface_map: dict[str, str] = k1["t4_surface_by_obfuscation"]
    obfs = payload.get("obfuscation") or []
    surface = next((surface_map[o] for o in obfs if o in surface_map), None)
    if surface is None:
        raise InjectorK1Error(
            f"{payload['id']}: không bề mặt K1 nào giao được cho obfuscation {obfs}; "
            f"ánh xạ hiện có {sorted(surface_map)} (metadata/html không vào top-k RAG)"
        )
    instruction = instruction_of(payload)
    if not (instruction or "").strip():
        raise InjectorK1Error(f"{payload['id']}: T4 cần instruction_<lang> trần để nhúng ẩn")
    data = carrier_docs.build_hidden_t4(instruction, surface)
    return DocSpec(
        doc_id=f"inject::{run_id}", fmt="pdf", data=data, probe=instruction, surface=surface
    )


def _plan_t6_docs(
    payload: dict[str, Any], run_id: str, formats: list[str], position: str, seed: str
) -> list[DocSpec]:
    frags = payload.get("fragments") or []
    if len(frags) < 2:
        raise InjectorK1Error(f"{payload['id']}: T6 cần ≥2 fragments để chia mảnh")
    specs: list[DocSpec] = []
    for frag in frags:
        fid = frag.get("fragment_id")
        text = frag.get("text") or frag.get("content")
        if not fid or not (text or "").strip():
            raise InjectorK1Error(f"{payload['id']}: fragment thiếu fragment_id hoặc text")
        fmt = _rotate_format(f"{payload['id']}:{fid}", formats, seed)
        data = carrier_docs.build_visible(text, fmt, position=position)
        specs.append(DocSpec(doc_id=f"inject::{run_id}::{fid}", fmt=fmt, data=data, probe=text))
    return specs


# ── Parser-gate ─────────────────────────────────────────────────────────────────
def _normalize(text: str) -> str:
    return " ".join(text.split())


def _assert_readable(path: Path, probe: str) -> None:
    """Chuỗi `probe` phải nằm trong text mà CHÍNH bộ đọc của ingest trích ra từ `path`.

    Dùng `rag.ingest.read_document` để parser-gate khớp đúng thứ sẽ được chunk — không phải
    pdftotext hay pypdf gọi riêng. Trích không ra ⇒ lỗi HARNESS (tài liệu không giao hàng được),
    KHÔNG phải `delivered=false`.
    """
    from rag.ingest import read_document

    extracted = _normalize(read_document(path))
    if _normalize(probe) not in extracted:
        raise InjectorK1Error(
            f"{path.name}: bộ đọc ingest không trích ra payload — tài liệu không giao được "
            "(lỗi harness, không phải delivered=false)"
        )


def build_and_write(
    payload: dict[str, Any],
    run_id: str,
    out_dir: Path | str,
    *,
    render_cfg: dict[str, Any] | None = None,
    verify: bool = True,
) -> list[tuple[DocSpec, Path]]:
    """Dựng + ghi đĩa mọi tài liệu của payload; parser-gate mỗi file. Trả [(spec, path)]."""
    specs = plan_docs(payload, run_id, render_cfg=render_cfg)
    written: list[tuple[DocSpec, Path]] = []
    for spec in specs:
        path = carrier_docs.write_doc(out_dir, spec.doc_id, spec.fmt, spec.data)
        if verify:
            _assert_readable(path, spec.probe)
        written.append((spec, path))
    return written


# ── Chèn + đo delivered ──────────────────────────────────────────────────────────
def inject_and_probe(
    payload: dict[str, Any],
    carrier: dict[str, Any] | str,
    run_id: str,
    *,
    k: int | None = None,
    render_cfg: dict[str, Any] | None = None,
    cfg: Any | None = None,
    client: Any | None = None,
    embedder: Any | None = None,
    out_dir: Path | str | None = None,
) -> InjectionResult:
    """Chèn mọi tài liệu của `payload` vào KB rồi đo `delivered` trên top-k của câu hỏi lành tính.

    `carrier` là dict tác vụ chở hoặc id của nó. KHÔNG tự dọn: bên gọi phải `cleanup(run_id)` hoặc
    bọc trong `rag.ingest.injected_doc`. Các tham số `cfg/client/embedder` cho test nối Qdrant giả.
    """
    from rag.ingest import inject_doc, read_document

    if isinstance(carrier, str):
        carrier = load_carrier(carrier)
    if "K1" not in carrier.get("injection_channels", []):
        raise InjectorK1Error(f"tác vụ chở {carrier.get('id')} không khai kênh K1")
    query = carrier.get("user_query_vi")
    if not query:
        raise InjectorK1Error(f"tác vụ chở {carrier.get('id')} thiếu user_query_vi để đo delivered")
    k = k if k is not None else default_top_k()

    # Ghi ra thư mục tạm (mặc định) chỉ để đọc lại bằng bộ đọc ingest — tài liệu K1 không cần lưu.
    with _maybe_tempdir(out_dir) as work:
        written = build_and_write(payload, run_id, work, render_cfg=render_cfg)
        n_chunks = 0
        for spec, path in written:
            content = read_document(path)
            n_chunks += inject_doc(
                run_id, content, cfg=cfg, client=client, embedder=embedder, doc_id=spec.doc_id
            )

    result = InjectionResult(
        run_id=run_id,
        payload_id=payload["id"],
        carrier_id=carrier["id"],
        doc_ids=[s.doc_id for s, _ in written],
        formats=[s.fmt for s, _ in written],
        n_chunks=n_chunks,
        surface=next((s.surface for s, _ in written if s.surface), None),
    )
    result.delivered, result.retrieved_doc_ids = probe_delivered(
        query, result.doc_ids, k=k, cfg=cfg, client=client, embedder=embedder
    )
    return result


def probe_delivered(
    query: str,
    required_doc_ids: list[str],
    *,
    k: int,
    cfg: Any | None = None,
    client: Any | None = None,
    embedder: Any | None = None,
) -> tuple[bool, list[str]]:
    """`delivered` = MỌI doc_id yêu cầu nằm trong top-k của `query`. Trả (cờ, doc_id top-k).

    Bao ca T6 (cần đủ mọi mảnh) lẫn ca một-tài-liệu (tập một phần tử) bằng một phép bao hàm tập.
    """
    from rag.retriever import search

    hits = search(query, k, cfg=cfg, client=client, embedder=embedder)
    retrieved = [str(h.metadata.get("doc_id")) for h in hits]
    delivered = set(required_doc_ids).issubset(set(retrieved))
    return delivered, retrieved


def observed_delivered(steps: Iterable[Any], required_doc_ids: Iterable[str]) -> bool:
    """`delivered` của run K1: MỌI doc_id yêu cầu xuất hiện trong kết quả của ít nhất một bước
    `search_kb` agent đã thực thi. `steps` là các `obs.trace.Step` (hay vật có `kind`,
    `tool_name`, `tool_result`). Bước chặn bởi phòng thủ không có kết quả nên không tính.

    Các mảnh T6 được phép tới qua những lần gọi khác nhau: chúng cùng nằm trong ngữ cảnh từ đó."""
    seen: set[str] = set()
    for step in steps:
        if step.kind != "tool" or step.tool_name != SEARCH_TOOL or not step.tool_result:
            continue
        try:
            results = json.loads(step.tool_result).get("results") or []
        except (json.JSONDecodeError, AttributeError) as exc:
            raise InjectorK1Error(
                f"kết quả search_kb không phải JSON {{'results': [...]}}: {step.tool_result[:80]!r}"
            ) from exc
        seen.update(str(r.get("doc_id")) for r in results)
    required = set(required_doc_ids)
    return bool(required) and required.issubset(seen)


def cleanup(run_id: str, *, cfg: Any | None = None, client: Any | None = None) -> None:
    """Lối tắt về rag.ingest.cleanup_doc — xóa mọi tài liệu chèn của `run_id`."""
    from rag.ingest import cleanup_doc

    cleanup_doc(run_id, cfg=cfg, client=client)


class _maybe_tempdir:
    """Dùng `out_dir` nếu có, nếu không thì một thư mục tạm tự xóa."""

    def __init__(self, out_dir: Path | str | None) -> None:
        self._out_dir = out_dir
        self._tmp: tempfile.TemporaryDirectory | None = None

    def __enter__(self) -> Path:
        if self._out_dir is not None:
            path = Path(self._out_dir)
            path.mkdir(parents=True, exist_ok=True)
            return path
        self._tmp = tempfile.TemporaryDirectory(prefix="ipi-k1-")
        return Path(self._tmp.name)

    def __exit__(self, *exc: Any) -> None:
        if self._tmp is not None:
            self._tmp.cleanup()
