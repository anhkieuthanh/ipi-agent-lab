"""MCP server STT-28 — test bằng client MCP thật trên ba đường: in-memory, stdio, HTTP.

Backend là `mcp_fake_backend.FakeTools` (năm tool, handler giả) để test không phụ thuộc handler
STT-29/30. Cấu hình server ghi ra file tạm, cổng HTTP lấy cổng trống.
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

import pytest
from mcp import StdioServerParameters
from mcp.shared.exceptions import MCPError

from agent.llm_client import ToolCall
from interfaces import ToolLayer
from mcp_fake_backend import TOOLS, FakeTools
from tools.mcp_server import (
    McpToolLayer,
    ServerConfig,
    build_server,
    load_server_config,
    serve_http_in_thread,
)

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "ipi-agent-lab/"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def cfg_file(tmp_path: Path) -> Path:
    p = tmp_path / "tools.yaml"
    p.write_text(
        "mcp_server:\n"
        "  name: test-tools\n"
        "  backend: mcp_fake_backend:make\n"
        f"  meta_prefix: '{PREFIX}'\n"
        "  http: {host: 127.0.0.1, port: " + str(_free_port()) + ", path: /mcp}\n"
        "  client_timeout_s: 20\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture
def cfg(cfg_file: Path) -> ServerConfig:
    return load_server_config(cfg_file)


def _call(name: str, cid: str = "c1", **args: str) -> ToolCall:
    return ToolCall(id=cid, name=name, arguments=args, arguments_raw="")


def _check_basic(tools: McpToolLayer, backend: FakeTools | None) -> None:
    """Danh sách đủ năm tool với nhãn rủi ro; call_tool đi khứ hồi giữ call_id và meta."""
    assert isinstance(tools, ToolLayer)
    specs = {s.name: s for s in tools.list_tools()}
    assert set(specs) == set(TOOLS)
    for name, (kind, side_effect, args) in TOOLS.items():
        assert specs[name].kind == kind
        assert specs[name].side_effect is side_effect
        assert set(specs[name].input_schema["properties"]) == set(args)

    res = tools.call_tool(_call("send_email", "call-xyz", to="a@congty-noibo.vn"))
    assert res.call_id == "call-xyz" and res.name == "send_email"
    assert not res.is_error
    assert "send_email ok" in res.content
    assert res.meta == {"echo_call_id": "call-xyz", "n_args": 1}
    if backend is not None:
        assert backend.calls[-1].id == "call-xyz"


def test_in_memory_roundtrip(cfg: ServerConfig) -> None:
    backend = FakeTools()
    with McpToolLayer(build_server(backend, cfg), cfg) as tools:
        _check_basic(tools, backend)


def test_list_tools_is_dynamic_k2a_and_rug_pull(cfg: ServerConfig) -> None:
    """Đổi mô tả ở backend giữa hai lần list_tools — client phải thấy ngay, không cache."""
    backend = FakeTools()
    with McpToolLayer(build_server(backend, cfg), cfg) as tools:
        first = {s.name: s.description for s in tools.list_tools()}
        assert first["send_email"] == "mô tả gốc send_email"
        backend.descriptions["send_email"] = "PAYLOAD K2a"
        second = {s.name: s.description for s in tools.list_tools()}
        assert second["send_email"] == "PAYLOAD K2a"
        backend.descriptions["send_email"] = "mô tả gốc send_email"  # rug-pull ngược lại
        assert {s.name: s.description for s in tools.list_tools()} == first


def test_tool_error_is_model_visible(cfg: ServerConfig) -> None:
    """Tool không tồn tại: backend trả is_error, client nhận ToolResult lỗi — không ném."""
    with McpToolLayer(build_server(FakeTools(), cfg), cfg) as tools:
        res = tools.call_tool(_call("delete_all"))
        assert res.is_error and "delete_all" in res.content


def test_harness_error_propagates(cfg: ServerConfig) -> None:
    """Backend ném ngoại lệ (lỗi harness) — client ném, không đổi thành is_error."""
    with McpToolLayer(build_server(FakeTools(), cfg), cfg) as tools:
        with pytest.raises(MCPError):
            tools.call_tool(_call("http_request", url="boom"))
        # phiên vẫn dùng được sau lỗi
        assert len(tools.list_tools()) == len(TOOLS)


def test_parse_error_call_rejected(cfg: ServerConfig) -> None:
    with McpToolLayer(build_server(FakeTools(), cfg), cfg) as tools:
        bad = ToolCall(
            id="c", name="search_kb", arguments=None, arguments_raw="{", parse_error=True
        )
        with pytest.raises(ValueError):
            tools.call_tool(bad)


def test_annotations_for_external_harness(cfg: ServerConfig) -> None:
    from tools.mcp_server import spec_to_mcp

    specs = {s.name: s for s in FakeTools().list_tools()}
    read = spec_to_mcp(specs["query_customer_db"], PREFIX).annotations
    out = spec_to_mcp(specs["http_request"], PREFIX).annotations
    assert read.read_only_hint and not read.open_world_hint
    assert not out.read_only_hint and out.open_world_hint


def test_stdio_real_subprocess(cfg: ServerConfig, cfg_file: Path) -> None:
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT / "tests")]),
    }
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "tools.mcp_server", "--transport", "stdio", "--config", str(cfg_file)],
        env=env,
        cwd=str(ROOT),
    )
    with McpToolLayer(params, cfg) as tools:
        _check_basic(tools, backend=None)


def test_http_real_server(cfg: ServerConfig) -> None:
    backend = FakeTools()
    with serve_http_in_thread(build_server(backend, cfg), cfg) as url:
        assert url == cfg.url
        with McpToolLayer(url, cfg) as tools:
            _check_basic(tools, backend)
            backend.descriptions["http_request"] = "đổi qua HTTP"
            assert {s.name: s.description for s in tools.list_tools()}[
                "http_request"
            ] == "đổi qua HTTP"
