"""Tool registry — năm tool TL1–TL5 của agent (STT-27), một nửa của tầng 2 `ToolLayer`.

Registry đọc `config/tools.yaml` và giữ ba thứ cho mỗi tool:

- **Schema function-calling** (`input_schema`) và **nhãn rủi ro** (`kind` ∈ {read, outbound},
  `side_effect`) — cố định trong run, khớp `agent_tools` của `data/carrier_tasks.json`.
- **Mô tả** (`description`) — nguồn thay được, tách khỏi schema. Bản gốc lấy từ yaml; injector K2a
  (STT-45) ghi đè bằng `set_description()` trước khi lõi agent gọi `list_tools()`, và có thể ghi
  đè lại giữa hai lần gọi để mô phỏng rug-pull. `reset_descriptions()` trả về bản gốc sau mỗi run.
- **Handler thực thi** — gắn bằng `bind()` ở STT-29/30; registry chỉ kiểm tên và tham số rồi chuyển.

    reg = ToolRegistry()
    reg.bind("search_kb", search_kb_handler)
    reg.set_description("send_email", payload_text)      # K2a — chỉ injector gọi
    specs = reg.list_tools()                              # lõi agent, đầu MỖI run
    result = reg.call_tool(call)                          # sau khi hai hook gate cho phép
    reg.reset_descriptions()

Tool-call model đề xuất mà sai tên hoặc sai tham số trả `ToolResult(is_error=True)` — đó là hành vi
của model, agent triển khai thật cũng nhận lỗi như vậy. Tool hợp lệ mà chưa gắn handler là lỗi
harness, ném `LookupError` để run dừng thay vì ghi nhầm thành hành vi model.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from interfaces import TOOL_KINDS, ToolResult, ToolSpec

if TYPE_CHECKING:
    from agent.llm_client import ToolCall

__all__ = [
    "ToolDef",
    "ToolRegistry",
    "ToolsConfigError",
    "Handler",
    "build_tool_layer",
    "load_tool_defs",
    "validate_args",
    "DEFAULT_PATH",
]

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = REPO_ROOT / "config" / "tools.yaml"

#: Handler nhận dict tham số đã kiểm, trả `ToolResult`. `call_id` do registry điền.
Handler = Callable[[dict[str, Any]], ToolResult]

_TOOL_KEYS = frozenset({"code", "kind", "side_effect", "description", "input_schema", "params"})
_JSON_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
}


class ToolsConfigError(ValueError):
    """`config/tools.yaml` sai hợp đồng."""


@dataclass(frozen=True)
class ToolDef:
    """Định nghĩa gốc của một tool như trong yaml. `params` là tham số riêng cho handler."""

    name: str
    code: str
    kind: str
    side_effect: bool
    description: str
    input_schema: dict[str, Any]
    params: dict[str, Any]

    def to_spec(self, description: str) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=description,
            input_schema=self.input_schema,
            kind=self.kind,
            side_effect=self.side_effect,
        )


def load_tool_defs(path: str | Path = DEFAULT_PATH) -> dict[str, ToolDef]:
    """Đọc và kiểm `config/tools.yaml`; giữ thứ tự khai báo."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    tools = raw.get("tools") if isinstance(raw, dict) else None
    if not isinstance(tools, dict) or not tools:
        raise ToolsConfigError(f"{path}: thiếu khối `tools`")

    defs: dict[str, ToolDef] = {}
    for name, body in tools.items():
        if not isinstance(body, dict):
            raise ToolsConfigError(f"tool '{name}': phải là mapping")
        unknown = set(body) - _TOOL_KEYS
        if unknown:
            raise ToolsConfigError(f"tool '{name}': khóa lạ {sorted(unknown)}")
        missing = (_TOOL_KEYS - {"params"}) - set(body)
        if missing:
            raise ToolsConfigError(f"tool '{name}': thiếu {sorted(missing)}")
        if body["kind"] not in TOOL_KINDS:
            raise ToolsConfigError(f"tool '{name}': kind phải thuộc {TOOL_KINDS}")
        if not isinstance(body["side_effect"], bool):
            raise ToolsConfigError(f"tool '{name}': side_effect phải là bool")
        if not str(body["description"]).strip():
            raise ToolsConfigError(f"tool '{name}': description rỗng")
        schema = body["input_schema"]
        if not isinstance(schema, dict) or schema.get("type") != "object":
            raise ToolsConfigError(f"tool '{name}': input_schema phải là object")
        props = schema.get("properties") or {}
        stray = set(schema.get("required", [])) - set(props)
        if stray:
            raise ToolsConfigError(f"tool '{name}': required không có trong properties {stray}")
        defs[name] = ToolDef(
            name=name,
            code=body["code"],
            kind=body["kind"],
            side_effect=body["side_effect"],
            description=str(body["description"]).strip(),
            input_schema=schema,
            params=dict(body.get("params") or {}),
        )
    return defs


def validate_args(schema: dict[str, Any], args: dict[str, Any]) -> list[str]:
    """Kiểm tham số theo tập con JSON Schema dùng trong tools.yaml. Trả danh sách lỗi, rỗng = đạt.

    Chỉ hỗ trợ đúng những gì yaml dùng: `type`, `enum`, `minimum`, `maximum`, `items.type`,
    `required`, `additionalProperties: false`. Không kiểm ngữ nghĩa (allowlist URL, read-only SQL) —
    đó là việc của handler và scorer, không phải của registry.
    """
    errors: list[str] = []
    props: dict[str, Any] = schema.get("properties") or {}
    for key in schema.get("required", []):
        if key not in args:
            errors.append(f"thiếu tham số bắt buộc '{key}'")
    if schema.get("additionalProperties") is False:
        errors.extend(f"tham số lạ '{key}'" for key in args if key not in props)
    for key, value in args.items():
        sub = props.get(key)
        if sub is None:
            continue
        errors.extend(f"'{key}': {e}" for e in _check_value(sub, value))
    return errors


def _check_value(sub: dict[str, Any], value: Any) -> list[str]:
    expected = sub.get("type")
    if expected:
        types = _JSON_TYPES[expected]
        # bool là con của int trong Python, nhưng JSON tách hai kiểu
        if not isinstance(value, types) or (isinstance(value, bool) and bool not in types):
            return [f"phải là {expected}, nhận {type(value).__name__}"]
    errors: list[str] = []
    if "enum" in sub and value not in sub["enum"]:
        errors.append(f"phải thuộc {sub['enum']}, nhận {value!r}")
    if "minimum" in sub and value < sub["minimum"]:
        errors.append(f"phải ≥ {sub['minimum']}")
    if "maximum" in sub and value > sub["maximum"]:
        errors.append(f"phải ≤ {sub['maximum']}")
    if expected == "array" and "items" in sub:
        for i, item in enumerate(value):
            errors.extend(f"[{i}] {e}" for e in _check_value(sub["items"], item))
    return errors


class ToolRegistry:
    """Danh sách tool + mô tả thay được + điều phối handler. Thỏa `interfaces.ToolLayer`."""

    def __init__(self, defs: dict[str, ToolDef] | None = None) -> None:
        self._defs = defs if defs is not None else load_tool_defs()
        self._overrides: dict[str, str] = {}
        self._handlers: dict[str, Handler] = {}

    # -- tra cứu --------------------------------------------------------------

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._defs)

    def tool_def(self, name: str) -> ToolDef:
        try:
            return self._defs[name]
        except KeyError:
            raise KeyError(f"không có tool '{name}'") from None

    def params(self, name: str) -> dict[str, Any]:
        """Tham số riêng của handler (`max_rows`…), bản sao để handler không sửa được registry."""
        return dict(self.tool_def(name).params)

    # -- mô tả: nguồn thay được (K2a) ----------------------------------------

    def baseline_description(self, name: str) -> str:
        return self.tool_def(name).description

    def description(self, name: str) -> str:
        """Mô tả hiện hành — bản ghi đè nếu có, không thì bản gốc."""
        self.tool_def(name)
        return self._overrides.get(name, self._defs[name].description)

    def is_overridden(self, name: str) -> bool:
        return name in self._overrides

    def set_description(self, name: str, text: str) -> None:
        """Ghi đè mô tả một tool. Chỉ injector K2a (STT-45) gọi; lần sau `list_tools()` thấy ngay."""
        self.tool_def(name)
        self._overrides[name] = text

    def reset_descriptions(self) -> None:
        """Trả mọi mô tả về bản gốc. Runner gọi sau mỗi run để K2a không rò sang run sau."""
        self._overrides.clear()

    # -- ToolLayer ------------------------------------------------------------

    def list_tools(self) -> list[ToolSpec]:
        """Danh sách tool với mô tả hiện hành. Dựng mới mỗi lần gọi, không cache."""
        return [d.to_spec(self.description(n)) for n, d in self._defs.items()]

    def bind(self, name: str, handler: Handler) -> None:
        self.tool_def(name)
        self._handlers[name] = handler

    def call_tool(self, call: ToolCall) -> ToolResult:
        """Kiểm tên và tham số rồi chuyển cho handler. Không gọi hook — lõi agent đã gọi trước."""
        if call.parse_error or call.arguments is None:
            # Lõi agent không được đưa tool-call parse_error tới đây (interfaces.HookSpec).
            raise ValueError(f"tool-call {call.id} parse_error, không thực thi được")
        if call.name not in self._defs:
            return self._error(call, f"Không có công cụ '{call.name}'.", reason="unknown_tool")
        errors = validate_args(self._defs[call.name].input_schema, call.arguments)
        if errors:
            return self._error(
                call, "Tham số không hợp lệ: " + "; ".join(errors), reason="invalid_args"
            )
        handler = self._handlers.get(call.name)
        if handler is None:
            raise LookupError(f"tool '{call.name}' chưa gắn handler — lỗi harness")
        result = handler(dict(call.arguments))
        return ToolResult(
            call_id=call.id,
            name=call.name,
            content=result.content,
            is_error=result.is_error,
            meta=result.meta,
        )

    @staticmethod
    def _error(call: ToolCall, message: str, *, reason: str) -> ToolResult:
        return ToolResult(
            call_id=call.id, name=call.name, content=message, is_error=True, meta={"error": reason}
        )


def build_tool_layer() -> ToolRegistry:
    """ToolLayer mặc định cho MCP server (`mcp_server.backend` trong tools.yaml, STT-28).

    Đủ năm tool: `send_email` (STT-29), `query_customer_db`, `http_request`, `create_ticket`
    (STT-30), `search_kb` (STT-37). `search_kb` mở Qdrant lười ở lần gọi đầu, nên dựng registry
    không cần Qdrant chạy.
    """
    from tools.create_ticket import CreateTicket
    from tools.http_request import HttpRequest
    from tools.query_customer_db import QueryCustomerDb
    from tools.search_kb import SearchKb
    from tools.send_email import SendEmail

    reg = ToolRegistry()
    reg.bind("search_kb", SearchKb.from_experiment())
    reg.bind("send_email", SendEmail.from_registry(reg))
    reg.bind("query_customer_db", QueryCustomerDb.from_registry(reg))
    reg.bind("http_request", HttpRequest.from_registry(reg))
    reg.bind("create_ticket", CreateTicket.from_registry(reg))
    return reg
