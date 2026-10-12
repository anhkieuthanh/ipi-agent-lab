"""Interface năm tầng của testbed và các điểm móc (hook) phòng thủ — STT-17, giai đoạn 1.

Module này chỉ khai hợp đồng: kiểu dữ liệu đi qua ranh giới giữa các tầng và `Protocol` mà mỗi
tầng phải thỏa. Không có logic nghiệp vụ, không có tham số hành vi — tham số D1–D4 nằm ở
`config/defenses.yaml` (quy tắc cứng #4).

Năm tầng (`Y_TUONG_DU_AN.md` mục 2, 7, 13):

    Tầng                Protocol        Hiện thực                                   STT
    1. Lõi agent        AgentCore       agent/core.py (Core-A)                      STT-26
    2. Công cụ MCP      ToolLayer       tools/registry.py · tools/mcp_server.py     STT-27…30
    3. Kho tri thức     KnowledgeBase   rag/retriever.py · rag/ingest.py            đã có
    4. Phòng thủ        DefenseLayer    defense/pipeline.py (preset "off": NoDefense) STT-51…55
    5. Đo lường         Recorder        obs/trace.py (TraceRecorder)                STT-32

Mô hình đích không phải một tầng: `ChatModel` là cổng ra của lõi agent, hiện thực bởi
`agent.llm_client.LLMClient`.

Lõi agent là tầng điều phối: nó gọi model, gọi tầng công cụ, gọi hook phòng thủ và ghi trace.
Tầng công cụ gọi kho tri thức qua `search_kb`. Không tầng nào khác gọi ngược lên lõi agent.

Điểm móc phòng thủ
------------------
Năm hook, khớp từng dòng `pipeline_order` của `config/defenses.yaml` (test giữ hai bên đồng bộ).
Thứ tự ghép bất biến: D2 → D1 → (model đề xuất tool-call) → D3 → nếu tool ∈ EGRESS_TOOLS → D4 →
thực thi thật. Bảng `HOOK_SPECS` ghi cho từng hook: giai đoạn nào trong năm giai đoạn của một lượt,
ai gọi, loại hook, nguồn nội dung nào đi qua.

Hai loại hook:

- `transform` — nhận văn bản không tin cậy, trả văn bản đã biến đổi (`Transformed`). D1, D2.
- `gate` — nhận tool-call model đề xuất, trả quyết định (`Decision`). D3, D4.

`final_answer` không qua hook nào. Đó là thiết kế, không phải thiếu sót: D3/D4 mù với G3 vì G3
không có tool-call nào để nhìn (`Y_TUONG_DU_AN.md` mục 4.3).

Ai quyết cơ chế nào chạy ở hook nào: `DefenseLayer` đọc `defenses.yaml`. Lõi agent gọi đủ mọi hook
ở mọi run, kể cả khi phòng thủ tắt — bật/tắt chỉ đổi config, không đổi call site. Lõi agent cũng
không tự xét tool có thuộc EGRESS_TOOLS hay không: nó gọi `pre_egress` cho mọi tool-call đã qua
`pre_tool_execution`, và `DefenseLayer` tự bỏ qua tool không có trong `egress_tools` của D4.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:  # chỉ để chú thích kiểu — không kéo openai/qdrant/fastembed lúc import
    from agent.llm_client import LLMResult, ToolCall
    from rag.retriever import SearchResult

__all__ = [
    "Source",
    "SOURCES",
    "SOURCE_CHANNEL",
    "KB_TOOL",
    "source_for_tool",
    "HookStage",
    "HookSpec",
    "HOOK_SPECS",
    "ToolSpec",
    "ToolResult",
    "DefenseHit",
    "Transformed",
    "Decision",
    "ExecutedCall",
    "SessionState",
    "AgentOutcome",
    "ChatModel",
    "ToolLayer",
    "KnowledgeBase",
    "DefenseLayer",
    "Recorder",
    "AgentCore",
    "NoDefense",
    "check_stage",
]

# ---------------------------------------------------------------------------
# Nguồn nội dung không tin cậy — khớp `wrap_sources` / `apply_to_sources` trong defenses.yaml
# ---------------------------------------------------------------------------

Source = Literal["kb_chunk", "tool_description", "tool_result"]
SOURCES: tuple[str, ...] = ("kb_chunk", "tool_description", "tool_result")

#: Nguồn → kênh tấn công. Cùng một nội dung, hai cách gọi: phòng thủ nói "nguồn", trace nói "kênh".
SOURCE_CHANNEL: dict[str, str] = {"kb_chunk": "K1", "tool_description": "K2a", "tool_result": "K2b"}

#: Cửa vào duy nhất của K1 (TL1). Chunk truy hồi vào context dưới dạng kết quả của tool này.
KB_TOOL = "search_kb"


def source_for_tool(tool_name: str) -> str:
    """Nguồn của kết quả một tool: `search_kb` mang chunk K1, mọi tool khác là K2b."""
    return "kb_chunk" if tool_name == KB_TOOL else "tool_result"


# ---------------------------------------------------------------------------
# Hook
# ---------------------------------------------------------------------------


class HookStage(str, Enum):
    """Năm điểm móc, giá trị trùng tên `stage` trong `pipeline_order` của defenses.yaml."""

    KB_RETRIEVAL = "kb_retrieval"
    TOOL_RESULT = "tool_result"
    CONTEXT_ASSEMBLY = "context_assembly"
    PRE_TOOL_EXECUTION = "pre_tool_execution"
    PRE_EGRESS = "pre_egress"

    @property
    def spec(self) -> HookSpec:
        return HOOK_SPECS[self]

    def accepts(self, source: str) -> bool:
        """Hook transform này có nhận nguồn `source` không. Hook gate không nhận nguồn nào."""
        return source in self.spec.sources


@dataclass(frozen=True)
class HookSpec:
    """Đặc tả một hook: giai đoạn của lượt, bên gọi, loại hook, nguồn đi qua."""

    phase: str
    caller: str
    kind: Literal["transform", "gate"]
    sources: tuple[str, ...]
    defenses: str
    description: str


#: Đánh số giai đoạn theo `Y_TUONG_DU_AN.md` mục 7.1: ① Gieo · ② Nạp · ③ Kích hoạt ·
#: ④ Nhầm lẫn ranh giới · ⑤ Thi hành. Cột `defenses` là đặc tả để người đọc tra; cơ chế thực sự
#: chạy ở mỗi hook do `pipeline_order` của defenses.yaml quyết định.
HOOK_SPECS: dict[HookStage, HookSpec] = {
    HookStage.KB_RETRIEVAL: HookSpec(
        phase="③ Kích hoạt",
        caller="Lõi agent, khi search_kb trả chunk về, trước khi chunk vào context",
        kind="transform",
        sources=("kb_chunk",),
        defenses="D2",
        description=(
            "Biến đổi từng chunk K1 vừa truy hồi. D2 chạy ở đây chứ không lúc ingest: vector store "
            "giữ văn bản thô, embedding không đổi, nên `delivered` giống nhau giữa D2 bật và tắt "
            "và không cần collection thứ hai."
        ),
    ),
    HookStage.TOOL_RESULT: HookSpec(
        phase="③ Kích hoạt",
        caller="Lõi agent, ngay khi tầng công cụ trả kết quả, trước khi kết quả vào context",
        kind="transform",
        sources=("tool_result",),
        defenses="D2",
        description=(
            "Biến đổi kết quả tool (K2b). Kết quả của search_kb mang nguồn kb_chunk, đi qua "
            "KB_RETRIEVAL thay vì hook này."
        ),
    ),
    HookStage.CONTEXT_ASSEMBLY: HookSpec(
        phase="④ Nhầm lẫn ranh giới",
        caller="Lõi agent, lúc ghép nội dung không tin cậy vào messages",
        kind="transform",
        sources=("kb_chunk", "tool_description", "tool_result"),
        defenses="D1",
        description=(
            "Dựng lại ranh giới dữ liệu/chỉ thị. Gọi cho mô tả tool lúc dựng danh sách tool "
            "(K2a), cho chunk truy hồi (K1) và cho kết quả tool (K2b) lúc nối vào messages."
        ),
    ),
    HookStage.PRE_TOOL_EXECUTION: HookSpec(
        phase="⑤ Thi hành",
        caller="Lõi agent, với mọi tool-call model đề xuất, trước khi thực thi",
        kind="gate",
        sources=(),
        defenses="D3",
        description=(
            "Kiểm tool-call theo task_type người dùng chọn trước phiên (quy tắc cứng #3) và "
            "lịch sử tool-call của phiên. Tool-call parse_error không tới hook này — không thực "
            "thi được thì không có gì để chặn."
        ),
    ),
    HookStage.PRE_EGRESS: HookSpec(
        phase="⑤ Thi hành",
        caller="Lõi agent, với mọi tool-call đã qua PRE_TOOL_EXECUTION, ngay trước khi thực thi",
        kind="gate",
        sources=(),
        defenses="D4",
        description=(
            "Quét luồng ra trước khi dữ liệu rời vành đai. Lõi agent gọi cho mọi tool-call; "
            "DefenseLayer tự bỏ qua tool không thuộc egress_tools của D4."
        ),
    ),
}


# ---------------------------------------------------------------------------
# Kiểu dữ liệu đi qua ranh giới tầng
# ---------------------------------------------------------------------------

#: `kind` của tool — khớp `agent_tools.*.kind` trong data/carrier_tasks.json.
TOOL_KINDS = ("read", "outbound")


@dataclass(frozen=True)
class ToolSpec:
    """Một tool như tầng công cụ phơi ra lúc chạy (MCP list_tools).

    `description` là nguồn thay được: injector K2a (STT-45) ghi đè nó trước khi lõi agent lấy danh
    sách tool, nên lõi agent phải lấy danh sách ĐỘNG ở mỗi run, không cache giữa các run.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    kind: str
    side_effect: bool

    def __post_init__(self) -> None:
        if self.kind not in TOOL_KINDS:
            raise ValueError(f"ToolSpec.kind phải thuộc {TOOL_KINDS}, nhận '{self.kind}'")

    def to_openai(self, description: str | None = None) -> dict[str, Any]:
        """Schema function-calling. `description` cho phép truyền bản đã qua CONTEXT_ASSEMBLY."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description if description is None else description,
                "parameters": self.input_schema,
            },
        }


@dataclass(frozen=True)
class ToolResult:
    """Kết quả một lần thực thi tool.

    `content` là văn bản đi vào context (nguồn K2b, hoặc K1 với search_kb). `meta` là dữ liệu có
    cấu trúc cho phòng thủ và scorer — số dòng đã đọc, mã HTTP, message id — KHÔNG vào context.
    """

    call_id: str
    name: str
    content: str
    is_error: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DefenseHit:
    """Một lần một cơ chế phòng thủ tác động — một phần tử của `steps.defense_hits` (JSON).

    `defense` là khóa khối trong defenses.yaml (`d1_spotlighting` …), `rule` là mã luật nếu có
    (`R1_task_type_allowlist` …). Một bước có thể có 0..N hit.
    """

    defense: str
    stage: str
    action: Literal["transform", "flag", "block", "confirm"]
    rule: str | None = None
    detail: str = ""

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Transformed:
    """Kết quả hook transform. Không cơ chế nào chạm vào văn bản thì `hits` rỗng."""

    text: str
    hits: tuple[DefenseHit, ...] = ()


DECISION_ACTIONS = ("allow", "block")


@dataclass(frozen=True)
class Decision:
    """Kết quả hook gate.

    - `allow`: thực thi.
    - `block`: không thực thi; lõi agent trả cho model một `ToolResult(is_error=True)` mang
      `reason` rồi chạy tiếp vòng lặp, và bật `AgentOutcome.defense_blocked`.

    Không có `confirm`: chạy tự động không có người duyệt, nên yêu cầu xác nhận (D3 luật R4) được
    DefenseLayer quy về `block` theo `automated_resolution` trong defenses.yaml trước khi trả về.
    Hit tương ứng mang `action="confirm"` để trace tách nó khỏi chặn bởi R1–R3.
    """

    action: str = "allow"
    reason: str = ""
    hits: tuple[DefenseHit, ...] = ()

    def __post_init__(self) -> None:
        if self.action not in DECISION_ACTIONS:
            raise ValueError(f"Decision.action phải thuộc {DECISION_ACTIONS}, nhận '{self.action}'")

    @property
    def allowed(self) -> bool:
        return self.action == "allow"


@dataclass
class ExecutedCall:
    """Một tool-call trong lịch sử phiên: đề xuất của model, quyết định gate, kết quả nếu chạy."""

    call: ToolCall
    decision: Decision
    result: ToolResult | None = None


@dataclass
class SessionState:
    """Trạng thái một run, lõi agent giữ và truyền cho hook.

    `task_type` là INPUT người dùng chọn trước phiên, khớp một khóa `task_types` của D3. Không tầng
    nào được suy ra nó từ câu hỏi (quy tắc cứng #3). `None` = phiên không khai task_type; D3 bật mà
    gặp `None` thì phải chặn, không được đoán.

    `run_canaries` để D4 dò canary; lõi agent không đọc trường này.
    """

    run_id: str
    task_type: str | None = None
    run_canaries: tuple[str, ...] = ()
    carrier_task_id: str | None = None
    benign_query_id: str | None = None
    step_idx: int = 0
    history: list[ExecutedCall] = field(default_factory=list)


STOP_REASONS = ("final_answer", "max_steps", "parse_error")


@dataclass
class AgentOutcome:
    """Kết quả lõi agent trả cho runner. Runner đưa vào scorer (STT-35), scorer gọi `finish()`.

    `defense_blocked` chỉ nói có hook gate nào trả `block` trong run. Lõi agent KHÔNG ghi
    `blocked_by`: phân định defense / model_refusal / harness là việc của scorer, vì "model tự từ
    chối" là phán đoán trên văn bản câu trả lời (quy tắc cứng #8).

    `stop_reason = "max_steps"` là chạm `MAX_STEPS` — khác nhãn `loop` (vượt `max_calls` của tác
    vụ chở), nhãn đó do `eval.allowed_actions.run_labels()` tính.
    """

    final_answer: str | None
    stop_reason: str
    n_steps: int
    tool_calls: list[ExecutedCall] = field(default_factory=list)
    defense_blocked: bool = False

    def __post_init__(self) -> None:
        if self.stop_reason not in STOP_REASONS:
            raise ValueError(f"stop_reason phải thuộc {STOP_REASONS}, nhận '{self.stop_reason}'")


# ---------------------------------------------------------------------------
# Protocol của từng tầng
# ---------------------------------------------------------------------------


@runtime_checkable
class ChatModel(Protocol):
    """Cổng gọi mô hình đích. Hiện thực: `agent.llm_client.LLMClient`."""

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMResult: ...


@runtime_checkable
class ToolLayer(Protocol):
    """Tầng 2 — năm tool qua MCP (STT-27…30).

    `list_tools()` gọi ở đầu MỖI run (danh sách động, cho phép K2a và rug-pull). `call_tool()` chỉ
    được lõi agent gọi sau khi hai hook gate đều trả `allow`; tầng công cụ không tự gọi hook.
    """

    def list_tools(self) -> list[ToolSpec]: ...

    def call_tool(self, call: ToolCall) -> ToolResult: ...


@runtime_checkable
class KnowledgeBase(Protocol):
    """Tầng 3 — vector store kênh K1. Hiện thực: `rag.retriever.search` + `rag.ingest`.

    `search` là điểm truy hồi duy nhất, dùng chung cho tool `search_kb` và cho kiểm `delivered`
    (`rag.retriever.is_delivered`), để "nằm trong top-k" luôn khớp thứ agent thực sự nhận.
    Vector store chỉ chứa văn bản thô; D2 chạy trên chunk đã truy hồi (hook KB_RETRIEVAL).
    """

    def search(self, query: str, k: int) -> list[SearchResult]: ...

    def inject_doc(self, run_id: str, content: str) -> int: ...

    def cleanup_doc(self, run_id: str) -> None: ...


@runtime_checkable
class DefenseLayer(Protocol):
    """Tầng 4 — pipeline D1–D4 (STT-55) đọc `config/defenses.yaml`.

    `transform` dùng cho hook loại transform, `gate` cho hook loại gate; gọi sai loại là lỗi lập
    trình, hiện thực phải ném `ValueError`. Với transform, bên gọi chỉ truyền `source` mà
    `stage.accepts(source)` trả True.

    `config_snapshot()` trả cấu hình đang bật, ghi nguyên vào `runs.defense_config`.
    """

    def transform(
        self,
        stage: HookStage,
        text: str,
        *,
        source: str,
        session: SessionState,
    ) -> Transformed: ...

    def gate(self, stage: HookStage, call: ToolCall, *, session: SessionState) -> Decision: ...

    def config_snapshot(self) -> dict[str, Any]: ...


@runtime_checkable
class Recorder(Protocol):
    """Tầng 5 — ghi trace một run. Hiện thực: `obs.trace.TraceRecorder`.

    Quy ước lõi agent ghi bước:
    - mỗi lần gọi model: `step(kind="llm", ...)`;
    - mỗi tool-call được thực thi: `step(kind="tool", ...)`, `defense_hits` gom hit của mọi hook
      đã chạy trên tool-call và kết quả của nó;
    - mỗi tool-call bị gate chặn: `step(kind="defense", tool_name=..., tool_args=...,
      defense_hits=...)`.
    `finish()` do scorer gọi, không phải lõi agent.
    """

    def step(self, *, kind: str, **fields: Any) -> Any: ...

    def finish(self, **result: Any) -> None: ...


@runtime_checkable
class AgentCore(Protocol):
    """Tầng 1 — vòng lặp tool-calling (Core-A, STT-26; Core-B dùng chung hợp đồng này).

    Mỗi bước: gọi model → với mỗi tool-call đề xuất: PRE_TOOL_EXECUTION → PRE_EGRESS → thực thi
    → KB_RETRIEVAL (search_kb) hoặc TOOL_RESULT (tool khác) → CONTEXT_ASSEMBLY → nối vào
    messages; dừng khi model trả câu trả lời cuối hoặc chạm `max_steps` (giá trị lấy từ
    config/experiment.yaml, không hard-code).
    """

    def run(self, user_query: str, *, session: SessionState, recorder: Recorder) -> AgentOutcome: ...


# ---------------------------------------------------------------------------
# Hiện thực tối thiểu cho preset "off"
# ---------------------------------------------------------------------------


class NoDefense:
    """DefenseLayer của preset `off`: mọi hook đi thẳng, không biến đổi, không chặn.

    Đây là baseline cố tình dễ tổn thương (`Y_TUONG_DU_AN.md` mục 2.8). Lõi agent vẫn gọi đủ năm
    hook qua lớp này, nên call site không đổi khi bật phòng thủ.
    """

    def transform(
        self,
        stage: HookStage,
        text: str,
        *,
        source: str,
        session: SessionState,
    ) -> Transformed:
        check_stage(stage, "transform", source)
        return Transformed(text=text)

    def gate(self, stage: HookStage, call: ToolCall, *, session: SessionState) -> Decision:
        check_stage(stage, "gate")
        return Decision(action="allow")

    def config_snapshot(self) -> dict[str, Any]:
        return {"preset": "off", "enabled": []}


def check_stage(stage: HookStage, kind: str, source: str | None = None) -> None:
    """Chặn gọi sai loại hook hoặc sai nguồn — mọi hiện thực DefenseLayer gọi ở đầu hai method."""
    if stage.spec.kind != kind:
        raise ValueError(f"hook {stage.value} là loại {stage.spec.kind}, không gọi qua {kind}()")
    if source is not None and not stage.accepts(source):
        raise ValueError(f"hook {stage.value} không nhận nguồn '{source}'")
