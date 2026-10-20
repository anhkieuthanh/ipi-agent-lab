"""Backend giả cho test MCP server (STT-28): năm tool TL1–TL5, handler tất định, mô tả thay được.

Tách module riêng để tiến trình con stdio nạp được qua `--backend mcp_fake_backend:make`.
"""

from __future__ import annotations

from interfaces import ToolResult, ToolSpec

TOOLS = {
    "search_kb": ("read", False, ["query", "k"]),
    "query_customer_db": ("read", False, ["sql_or_filter"]),
    "send_email": ("outbound", True, ["to", "subject", "body", "attachments"]),
    "http_request": ("outbound", True, ["method", "url", "body"]),
    "create_ticket": ("outbound", True, ["customer_id", "title", "body", "priority"]),
}


class FakeTools:
    def __init__(self) -> None:
        self.descriptions = {name: f"mô tả gốc {name}" for name in TOOLS}
        self.calls: list = []

    def list_tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name=name,
                description=self.descriptions[name],
                input_schema={
                    "type": "object",
                    "properties": {a: {"type": "string"} for a in args},
                },
                kind=kind,
                side_effect=side_effect,
            )
            for name, (kind, side_effect, args) in TOOLS.items()
        ]

    def call_tool(self, call) -> ToolResult:
        self.calls.append(call)
        if call.name not in TOOLS:
            return ToolResult(call.id, call.name, f"không có tool '{call.name}'", is_error=True)
        if call.name == "http_request" and call.arguments.get("url") == "boom":
            raise LookupError("handler chưa gắn")  # mô phỏng lỗi harness
        return ToolResult(
            call_id=call.id,
            name=call.name,
            content=f"{call.name} ok: {call.arguments}",
            meta={"echo_call_id": call.id, "n_args": len(call.arguments)},
        )


def make() -> FakeTools:
    return FakeTools()
