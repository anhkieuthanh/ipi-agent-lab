"""MCP server phơi năm tool TL1–TL5 qua stdio và Streamable HTTP (STT-28), cùng client phía agent.

Hai nửa, cả hai đều thỏa `interfaces.ToolLayer`:

- **Server** — `build_server(backend)` bọc một `ToolLayer` trong tiến trình (thường là
  `tools.registry.ToolRegistry`) thành `mcp.server.Server` cấp thấp. Mỗi request `tools/list` hỏi
  lại `backend.list_tools()`, không giữ bản sao nào: mô tả bị injector K2a ghi đè, hay bị đổi giữa
  hai lần gọi (rug-pull), tới client ngay ở request kế tiếp.
- **Client** — `McpToolLayer` là `ToolLayer` đồng bộ cho lõi agent, nói chuyện với server qua
  `mcp.client.Client`: in-memory (truyền thẳng `Server`), stdio (`StdioServerParameters`) hoặc
  HTTP (URL). `list_tools()` luôn gửi request thật (`cache_mode="bypass"`), nên lõi agent gọi nó
  ở đầu MỖI run là lấy được danh sách ĐỘNG.

Thuộc tính riêng của testbed đi qua `_meta` của giao thức, không trộn vào văn bản vào context:
`kind`/`side_effect` của tool, `call_id` của tool-call, `ToolResult.meta` của kết quả.

Lỗi harness (handler chưa gắn, backend ném ngoại lệ) KHÔNG đổi thành `is_error`: server để ngoại
lệ thành lỗi JSON-RPC, client ném `MCPError`, run dừng — không ghi nhầm thành hành vi model.

Lưu ý K2a với stdio: server chạy ở tiến trình con, nên `set_description()` gọi trên registry của
tiến trình cha không tới được nó. Run có tiêm K2a dùng in-memory hoặc HTTP chạy cùng tiến trình
(`serve_http_in_thread`).

Dòng lệnh:

    uv run python -m tools.mcp_server --transport stdio
    uv run python -m tools.mcp_server --transport http [--port 8765]
"""

from __future__ import annotations

import argparse
import importlib
import json
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

import anyio
import yaml
from anyio.from_thread import BlockingPortal, start_blocking_portal
from mcp import types
from mcp.client import Client
from mcp.server import Server, ServerRequestContext

from interfaces import ToolLayer, ToolResult, ToolSpec

if TYPE_CHECKING:
    from agent.llm_client import ToolCall

__all__ = [
    "ServerConfig",
    "load_server_config",
    "build_server",
    "spec_to_mcp",
    "mcp_to_spec",
    "McpToolLayer",
    "serve_http_in_thread",
    "DEFAULT_PATH",
]

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = REPO_ROOT / "config" / "tools.yaml"


# ---------------------------------------------------------------------------
# Cấu hình
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ServerConfig:
    """Khối `mcp_server` của `config/tools.yaml`."""

    name: str
    backend: str
    meta_prefix: str
    http_host: str
    http_port: int
    http_path: str
    client_timeout_s: float

    @property
    def url(self) -> str:
        return f"http://{self.http_host}:{self.http_port}{self.http_path}"


def load_server_config(path: str | Path = DEFAULT_PATH) -> ServerConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    block = raw.get("mcp_server")
    if not isinstance(block, dict):
        raise ValueError(f"{path} thiếu khối 'mcp_server'")
    http = block.get("http") or {}
    try:
        return ServerConfig(
            name=str(block["name"]),
            backend=str(block["backend"]),
            meta_prefix=str(block["meta_prefix"]),
            http_host=str(http["host"]),
            http_port=int(http["port"]),
            http_path=str(http["path"]),
            client_timeout_s=float(block["client_timeout_s"]),
        )
    except KeyError as e:
        raise ValueError(f"{path}: khối 'mcp_server' thiếu khóa {e}") from None


def load_backend(ref: str) -> ToolLayer:
    """Dựng backend từ chuỗi "module:callable" — callable không đối số trả về một ToolLayer."""
    module_name, _, attr = ref.partition(":")
    if not attr:
        raise ValueError(f"backend phải có dạng 'module:callable', nhận '{ref}'")
    factory = getattr(importlib.import_module(module_name), attr)
    backend = factory()
    if not isinstance(backend, ToolLayer):
        raise TypeError(f"{ref} trả {type(backend).__name__}, không phải ToolLayer")
    return backend


# ---------------------------------------------------------------------------
# Chuyển đổi ToolSpec <-> mcp.types.Tool
# ---------------------------------------------------------------------------


def spec_to_mcp(spec: ToolSpec, meta_prefix: str) -> types.Tool:
    """`ToolSpec` → `Tool`. Nhãn rủi ro đi trong `_meta` (cho client của testbed) và cả trong
    `annotations` chuẩn MCP (cho harness bên ngoài cắm vào ở ND6)."""
    return types.Tool(
        name=spec.name,
        description=spec.description,
        input_schema=spec.input_schema,
        annotations=types.ToolAnnotations(
            read_only_hint=spec.kind == "read",
            destructive_hint=False,  # mọi tool đều đọc hoặc append-only
            open_world_hint=spec.kind == "outbound",
        ),
        meta={f"{meta_prefix}kind": spec.kind, f"{meta_prefix}side_effect": spec.side_effect},
    )


def mcp_to_spec(tool: types.Tool, meta_prefix: str) -> ToolSpec:
    meta = tool.meta or {}
    try:
        kind = meta[f"{meta_prefix}kind"]
        side_effect = meta[f"{meta_prefix}side_effect"]
    except KeyError as e:
        raise ValueError(
            f"tool '{tool.name}' thiếu _meta {e} — không phải server của testbed"
        ) from None
    return ToolSpec(
        name=tool.name,
        description=tool.description or "",
        input_schema=dict(tool.input_schema),
        kind=str(kind),
        side_effect=bool(side_effect),
    )


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------


def build_server(backend: ToolLayer, cfg: ServerConfig | None = None) -> Server:
    """Bọc `backend` thành MCP server cấp thấp. Không cache danh sách tool."""
    cfg = cfg or load_server_config()
    prefix = cfg.meta_prefix

    async def on_list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        specs = await anyio.to_thread.run_sync(backend.list_tools)
        return types.ListToolsResult(tools=[spec_to_mcp(s, prefix) for s in specs])

    async def on_call_tool(
        ctx: ServerRequestContext, params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        from agent.llm_client import ToolCall  # chỉ dataclass; tránh vòng import lúc nạp module

        req_meta = ctx.meta or {}
        call_id = str(req_meta.get(f"{prefix}call_id") or ctx.request_id)
        args = dict(params.arguments or {})
        call = ToolCall(
            id=call_id,
            name=params.name,
            arguments=args,
            arguments_raw=json.dumps(args, ensure_ascii=False),
        )
        result = await anyio.to_thread.run_sync(backend.call_tool, call)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=result.content)],
            is_error=result.is_error,
            meta={f"{prefix}result_meta": result.meta},
        )

    return Server(cfg.name, on_list_tools=on_list_tools, on_call_tool=on_call_tool)


async def run_stdio(server: Server) -> None:
    from mcp.server.lowlevel import NotificationOptions
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(
                notification_options=NotificationOptions(tools_changed=True)
            ),
        )


def http_app(server: Server, cfg: ServerConfig) -> Any:
    return server.streamable_http_app(streamable_http_path=cfg.http_path, host=cfg.http_host)


@contextmanager
def serve_http_in_thread(server: Server, cfg: ServerConfig) -> Iterator[str]:
    """Chạy server HTTP ở một luồng nền của CHÍNH tiến trình này; trả URL. Dùng khi cần HTTP mà
    vẫn giữ registry chung với injector K2a, và cho test bằng client thật."""
    import uvicorn

    config = uvicorn.Config(
        http_app(server, cfg), host=cfg.http_host, port=cfg.http_port, log_level="warning"
    )
    uv_server = uvicorn.Server(config)
    thread = threading.Thread(target=uv_server.run, name="mcp-http", daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not uv_server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError(f"MCP server HTTP không khởi động được ở {cfg.url}")
        time.sleep(0.02)
    try:
        yield cfg.url
    finally:
        uv_server.should_exit = True
        thread.join(timeout=10)


# ---------------------------------------------------------------------------
# Client phía lõi agent
# ---------------------------------------------------------------------------


class McpToolLayer(AbstractContextManager):
    """`ToolLayer` đồng bộ nói chuyện với MCP server. Dùng như context manager:

        with McpToolLayer(target) as tools:
            specs = tools.list_tools()        # đầu MỖI run — luôn request thật
            result = tools.call_tool(call)

    `target`: một `Server` (in-memory), `StdioServerParameters` (stdio) hoặc URL (HTTP). Phiên MCP
    sống trong một event loop ở luồng nền (anyio blocking portal), giữ nguyên qua các lần gọi.
    """

    def __init__(self, target: Any, cfg: ServerConfig | None = None) -> None:
        self._target = target
        self._cfg = cfg or load_server_config()
        self._portal_cm: AbstractContextManager[BlockingPortal] | None = None
        self._portal: BlockingPortal | None = None
        self._client_cm: AbstractContextManager[Client] | None = None
        self._client: Client | None = None

    def __enter__(self) -> McpToolLayer:
        self._portal_cm = start_blocking_portal()
        self._portal = self._portal_cm.__enter__()
        try:
            client = Client(self._target, read_timeout_seconds=self._cfg.client_timeout_s)
            self._client_cm = self._portal.wrap_async_context_manager(client)
            self._client = self._client_cm.__enter__()
        except BaseException:
            self._portal_cm.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *exc: Any) -> None:
        try:
            if self._client_cm is not None:
                self._client_cm.__exit__(*exc)
        finally:
            if self._portal_cm is not None:
                self._portal_cm.__exit__(None, None, None)
            self._client = self._client_cm = self._portal = self._portal_cm = None

    def _call(self, fn: Callable[[], Any]) -> Any:
        if self._portal is None or self._client is None:
            raise RuntimeError("McpToolLayer chưa mở — dùng trong khối `with`")
        return self._portal.call(fn)

    async def _list_all(self) -> list[types.Tool]:
        assert self._client is not None
        tools: list[types.Tool] = []
        cursor: str | None = None
        while True:
            page = await self._client.list_tools(cursor=cursor, cache_mode="bypass")
            tools.extend(page.tools)
            cursor = page.next_cursor
            if not cursor:
                return tools

    def list_tools(self) -> list[ToolSpec]:
        tools = self._call(self._list_all)
        return [mcp_to_spec(t, self._cfg.meta_prefix) for t in tools]

    def call_tool(self, call: ToolCall) -> ToolResult:
        if call.parse_error or call.arguments is None:
            # Hợp đồng: tool-call parse_error không tới tầng công cụ (HookSpec PRE_TOOL_EXECUTION).
            raise ValueError(
                f"tool-call '{call.id}' parse_error — lõi agent không được gửi tới đây"
            )
        assert self._client is not None
        prefix = self._cfg.meta_prefix
        res: types.CallToolResult = self._call(
            partial(
                self._client.call_tool,
                call.name,
                call.arguments,
                meta={f"{prefix}call_id": call.id},
            )
        )
        text = "\n".join(c.text for c in res.content if isinstance(c, types.TextContent))
        result_meta = (res.meta or {}).get(f"{prefix}result_meta") or {}
        return ToolResult(
            call_id=call.id,
            name=call.name,
            content=text,
            is_error=bool(res.is_error),
            meta=dict(result_meta),
        )


# ---------------------------------------------------------------------------
# Dòng lệnh
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="MCP server năm tool TL1–TL5 (STT-28)")
    ap.add_argument("--transport", choices=("stdio", "http"), required=True)
    ap.add_argument("--config", default=str(DEFAULT_PATH))
    ap.add_argument("--backend", help="'module:callable' trả ToolLayer; mặc định lấy từ config")
    ap.add_argument("--port", type=int, help="ghi đè mcp_server.http.port")
    args = ap.parse_args(argv)

    cfg = load_server_config(args.config)
    if args.port is not None:
        cfg = ServerConfig(**{**cfg.__dict__, "http_port": args.port})
    server = build_server(load_backend(args.backend or cfg.backend), cfg)

    if args.transport == "stdio":
        anyio.run(run_stdio, server)
    else:
        import uvicorn

        uvicorn.run(http_app(server, cfg), host=cfg.http_host, port=cfg.http_port)


if __name__ == "__main__":
    main()
