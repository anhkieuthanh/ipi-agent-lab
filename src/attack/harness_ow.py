"""Harness HN-OW — chạy một run qua agent runtime OpenWork (opencode) thay cho lõi core-a (STT-79).

`OpenWorkCore` thỏa `interfaces.AgentCore` nên `run_one_attack` dùng nó y như `CoreA`: cùng
`seeded_run`, cùng tiêm K1/K2, cùng scorer. Khác biệt duy nhất là vòng tool-calling do opencode
(tiến trình node riêng) chạy, gọi tool testbed qua MCP HTTP in-thread — handler dùng chung nên
state seeded (customers.db đã gieo, mailbox, http sink, canary) gắn đúng run như lõi core-a
(`eval.canary.seeded_run` mutate handler, không contextvar).

Hợp đồng với scorer (xem src/eval/scorer.py):
- mỗi tool-call opencode thực thi → một bước `kind="tool"` (`tool_name` đã bỏ tiền tố server,
  `tool_args` = input, `tool_result` = output thô);
- câu trả lời cuối → một bước `kind="llm"` KHÔNG tool-call mang `llm_text` (bước cuối của trace);
- opencode lỗi hạ tầng → `LLMClientError` (RECOVERABLE) để run ghi `parse_error`, lô chạy tiếp.

HN-OW KHÔNG đi qua `agent.llm_client.LLMClient`: model ghim bằng `model_id` trong config opencode,
không có log `llm_client.jsonl` nên không áp `find_offpin_runs` cho nhánh này (nhánh `none` của B6
vẫn qua core-a và vẫn bị kiểm off-pin).
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.llm_client import LLMClientError
from interfaces import AgentCore, AgentOutcome, ChatModel, Recorder, SessionState, ToolLayer
from tools.mcp_server import ServerConfig, build_server, load_server_config, serve_http_in_thread

__all__ = ["OpenWorkCore", "HARNESS_OW", "MCP_SERVER_NAME"]

HARNESS_OW = "HN-OW"
MCP_SERVER_NAME = "testbed"  # khóa mcp trong config opencode; tool phơi tên "<server>_<tool>"
PROVIDER_ID = "llmgate"  # provider openai-compatible trỏ gateway testbed

#: Tool builtin của opencode phải tắt để môi trường HN-OW chỉ có 5 tool testbed như core-a.
_OPENCODE_BUILTIN_OFF = {
    k: False
    for k in (
        "bash", "edit", "write", "read", "grep", "glob", "list", "patch",
        "webfetch", "todowrite", "todoread", "task",
    )
}


@dataclass
class OpenWorkCore(AgentCore):
    """Lõi agent chạy qua opencode. Khởi tạo giống `CoreA` (model, tools, system_prompt, max_*)."""

    model: ChatModel
    tools: ToolLayer
    system_prompt: str
    max_steps: int
    max_tokens: int
    # Phụ thuộc runtime — mặc định lấy từ config/env, test ghi đè.
    server_config: ServerConfig | None = None
    base_url_env: str = "GATEWAY_BASE_URL"
    api_key_env: str = "GATEWAY_API_KEY"
    opencode_bin: str = "opencode"
    timeout_s: int = 300
    # Không dùng `defense` (B6 chỉ chạy preset off) nhưng nhận để khớp chữ ký CoreA.
    defense: Any = None
    _extra: dict[str, Any] = field(default_factory=dict)

    def run(self, user_query: str, *, session: SessionState, recorder: Recorder) -> AgentOutcome:
        cfg = self.server_config or load_server_config()
        server = build_server(self.tools)
        with serve_http_in_thread(server, cfg) as url:
            with tempfile.TemporaryDirectory(prefix="hnow-") as tmp:
                workdir = Path(tmp)
                self._write_config(workdir, url)
                stdout = self._run_opencode(workdir, user_query)
        return self._record(stdout, recorder)

    # -- cấu hình opencode ---------------------------------------------------

    def _model_id(self) -> str:
        return self.model.model

    def _write_config(self, workdir: Path, mcp_url: str) -> None:
        base_url = os.environ.get(self.base_url_env)
        if not base_url:
            raise LLMClientError(f"{self.base_url_env} chưa set — không cấu hình được opencode HN-OW")
        (workdir / "system_prompt.md").write_text(self.system_prompt, "utf-8")
        cfg = {
            "$schema": "https://opencode.ai/config.json",
            "provider": {
                PROVIDER_ID: {
                    "npm": "@ai-sdk/openai-compatible",
                    "name": "Testbed gateway",
                    "options": {"baseURL": base_url, "apiKey": f"{{env:{self.api_key_env}}}"},
                    "models": {self._model_id(): {"name": self._model_id()}},
                }
            },
            "mcp": {MCP_SERVER_NAME: {"type": "remote", "url": mcp_url, "enabled": True}},
            "agent": {
                "testbed": {
                    "mode": "primary",
                    "prompt": "{file:./system_prompt.md}",
                    "tools": dict(_OPENCODE_BUILTIN_OFF),
                }
            },
        }
        (workdir / "opencode.json").write_text(json.dumps(cfg, indent=2), "utf-8")

    def _run_opencode(self, workdir: Path, user_query: str) -> str:
        env = os.environ.copy()
        env["OPENCODE_CONFIG"] = str(workdir / "opencode.json")
        cmd = [
            self.opencode_bin, "run", "--format", "json", "--log-level", "ERROR",
            "--agent", "testbed", "-m", f"{PROVIDER_ID}/{self._model_id()}", user_query,
        ]
        try:
            proc = subprocess.run(
                cmd, cwd=workdir, capture_output=True, text=True, timeout=self.timeout_s, env=env
            )
        except subprocess.TimeoutExpired as e:
            raise LLMClientError(f"opencode HN-OW quá {self.timeout_s}s") from e
        if proc.returncode != 0:
            raise LLMClientError(f"opencode HN-OW thoát {proc.returncode}: {proc.stderr[-300:]}")
        return proc.stdout

    # -- dựng trace từ sự kiện JSON opencode ---------------------------------

    def _record(self, stdout: str, recorder: Recorder) -> AgentOutcome:
        final_answer: str | None = None
        tokens_in = tokens_out = 0
        n_tool = 0
        saw_error: str | None = None
        for line in stdout.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            etype = ev.get("type")
            part = ev.get("part") or {}
            if etype == "error":
                saw_error = str((ev.get("error") or {}).get("name") or "UnknownError")
            elif etype == "tool_use" and part.get("type") == "tool":
                state = part.get("state") or {}
                if state.get("status") != "completed":
                    continue
                recorder.step(
                    kind="tool",
                    tool_name=self._strip_prefix(part.get("tool", "")),
                    tool_args=state.get("input"),
                    tool_result=state.get("output"),
                )
                n_tool += 1
            elif etype == "step_finish":
                tok = part.get("tokens") or {}
                tokens_in += int(tok.get("input") or 0)
                tokens_out += int(tok.get("output") or 0)
            elif etype == "text":
                text = part.get("text")
                if text:
                    final_answer = text
        if saw_error and final_answer is None:
            raise LLMClientError(f"opencode HN-OW sự kiện lỗi: {saw_error}")
        # Bước cuối BẮT BUỘC là llm không-tool mang câu trả lời (hợp đồng scorer `_final_answer`).
        recorder.step(
            kind="llm",
            llm_text=final_answer,
            finish_reason="stop",
            tool_args=None,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            response_model=self._model_id(),
        )
        return AgentOutcome(
            final_answer=final_answer,
            stop_reason="final_answer",
            n_steps=n_tool + 1,
            tool_calls=[],
            defense_blocked=False,
        )

    @staticmethod
    def _strip_prefix(tool: str) -> str:
        prefix = f"{MCP_SERVER_NAME}_"
        return tool[len(prefix):] if tool.startswith(prefix) else tool
