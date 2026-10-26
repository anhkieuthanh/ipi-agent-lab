"""render.py — dựng dạng payload trên từng kênh K1/K2a/K2b (STT-41).

Hiện thực `docs/04. Design/payload_taxonomy.md` mục 2.3. Một payload là MỘT bản ghi cho mọi kênh;
hàm ở đây sinh chuỗi theo kênh lúc dựng ma trận, không lưu bản ghi riêng theo kênh. Tham số độ dài,
vị trí nối và trường chở đọc từ `config/channel_render.yaml` (không hard-code).

Ba lớp:

    text = render_for_channel(payload, "K2a")              # chuỗi payload của kênh, đã kiểm độ dài
    desc = apply_k2a(original_description, text)            # description mới của tool chở
    content = apply_k2b("query_customer_db", content, text) # content mới của ToolResult

Chọn tool chở (`k2a_target_tool`) và đặt vào registry / kết quả tool là việc của injector K2
(STT-45); module này chỉ biến đổi chuỗi, không gọi mạng, không gọi LLM.

Vượt giới hạn thì ném `ChannelRenderError`, KHÔNG cắt (mục 2.3, quy tắc 1). Độ dài tính trên chuỗi
còn placeholder ngữ cảnh (`{USER}`, `{MODEL}`, `{TOOL}`, `{run_id}`) vì giá trị thật chỉ có lúc chạy.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "channel_render.yaml"

_INSTRUCTION = "{INSTRUCTION}"
K2_CHANNELS = ("K2a", "K2b")
_LANG_INSTRUCTION = {"vi": "instruction_vi", "en": "instruction_en", "mixed": "instruction_vi"}


class ChannelRenderError(ValueError):
    """Payload không dựng được trên kênh yêu cầu (sai kênh, vượt giới hạn, JSON hỏng)."""


@lru_cache(maxsize=4)
def _load(path: str) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def load_render_config(path: Path | str = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    return _load(str(path))


def instruction_of(p: dict[str, Any]) -> str | None:
    """Chỉ thị theo ngôn ngữ payload; None nếu payload không có goal_binding."""
    gb = p.get("goal_binding") or {}
    return gb.get(_LANG_INSTRUCTION.get(p.get("lang"), "instruction_vi"))


def base_text(p: dict[str, Any]) -> str:
    """Chuỗi gốc: template thay {INSTRUCTION} bằng instruction_<lang>. Giống nhau trên mọi kênh."""
    template = (p.get("technique") or {}).get("template", "")
    return template.replace(_INSTRUCTION, instruction_of(p) or "")


def render_for_channel(
    p: dict[str, Any], channel: str, *, cfg: dict[str, Any] | None = None
) -> str:
    """Chuỗi payload của `channel`. K1 trả chuỗi gốc; K2a/K2b ưu tiên channel_override."""
    if channel not in (p.get("channels") or []):
        raise ChannelRenderError(f"{p.get('id')}: kênh {channel} không nằm trong channels")
    if channel == "K1":
        return base_text(p)
    if channel not in K2_CHANNELS:
        raise ChannelRenderError(f"{p.get('id')}: kênh lạ {channel}")
    cfg = cfg or load_render_config()
    override = (p.get("channel_override") or {}).get(channel)
    text = override if override is not None else base_text(p)
    limit = cfg["channels"][channel]["max_payload_chars"]
    if len(text) > limit:
        src = "channel_override" if override is not None else "chuỗi gốc"
        raise ChannelRenderError(
            f"{p.get('id')}: {src} ở {channel} dài {len(text)} > {limit} ký tự; "
            "viết channel_override rút gọn hoặc bỏ kênh (không cắt)"
        )
    return text


def k2a_target_tool(
    p: dict[str, Any], allowed_tools: list[str] | tuple[str, ...],
    *, cfg: dict[str, Any] | None = None,
) -> str:
    """Tool có description chở payload K2a, theo `target_tool_priority` trong allowed_tools."""
    cfg = cfg or load_render_config()
    goal_tool = (p.get("goal_binding") or {}).get("tool")
    for choice in cfg["channels"]["K2a"]["target_tool_priority"]:
        name = goal_tool if choice == "goal_tool" else choice
        if name and name in allowed_tools:
            return name
    raise ChannelRenderError(f"{p.get('id')}: không có tool chở K2a trong {list(allowed_tools)}")


def apply_k2a(description: str, text: str, *, cfg: dict[str, Any] | None = None) -> str:
    """Description mới = description gốc + joiner + payload (position: append)."""
    k2a = (cfg or load_render_config())["channels"]["K2a"]
    if k2a["position"] != "append":
        raise ChannelRenderError(f"K2a.position '{k2a['position']}' chưa hỗ trợ")
    return description + k2a["joiner"] + text


def apply_k2b(tool: str, content: str, text: str, *, cfg: dict[str, Any] | None = None) -> str:
    """Thêm trường chuỗi chở payload vào JSON kết quả của `tool`; trả content mới.

    Lỗi (tool không chở được, JSON không parse được, trường đã tồn tại) là lỗi harness.
    """
    k2b = (cfg or load_render_config())["channels"]["K2b"]
    spec = k2b["tools"].get(tool)
    if spec is None:
        raise ChannelRenderError(f"tool '{tool}' không chở K2b; cho {sorted(k2b['tools'])}")
    field = spec["field"]
    if field in k2b.get("forbidden_fields", []):
        raise ChannelRenderError(f"trường '{field}' bị cấm làm trường chở K2b")
    try:
        outer = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ChannelRenderError(f"content của {tool} không phải JSON: {exc}") from exc

    if spec["container"] == "root":
        _add_field(outer, field, text, tool)
    elif spec["container"] == "body":
        try:
            inner = json.loads(outer["body"])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ChannelRenderError(f"body của {tool} không phải JSON: {exc}") from exc
        _add_field(inner, field, text, tool)
        outer["body"] = json.dumps(inner, ensure_ascii=False)
    else:
        raise ChannelRenderError(f"container '{spec['container']}' lạ")

    new = json.dumps(outer, ensure_ascii=False)
    if k2b.get("require_json_roundtrip"):
        json.loads(new)
    return new


def _add_field(obj: Any, field: str, text: str, tool: str) -> None:
    if not isinstance(obj, dict):
        raise ChannelRenderError(f"kết quả {tool} không phải đối tượng JSON")
    if field in obj:
        raise ChannelRenderError(f"kết quả {tool} đã có trường '{field}'; không ghi đè")
    obj[field] = text


def channel_override_errors(
    p: dict[str, Any], *, cfg: dict[str, Any] | None = None
) -> list[str]:
    """Bất biến 12 (taxonomy 4.3): channel_override hợp lệ, mọi kênh K2 dựng được, và payload T4 khai
    K1 có obfuscation nằm trong `channels.K1.t4_surface_by_obfuscation` (bề mặt K1 giao được)."""
    e: list[str] = []
    channels = p.get("channels") or []
    if "K1" in channels and (p.get("technique") or {}).get("code") == "T4":
        surfaces = (cfg or load_render_config())["channels"]["K1"]["t4_surface_by_obfuscation"]
        obfs = p.get("obfuscation") or []
        if not any(o in surfaces for o in obfs):
            e.append(
                f"[INV12] T4 khai K1 nhưng obfuscation {obfs} không có bề mặt K1 trong "
                f"t4_surface_by_obfuscation {sorted(surfaces)}"
            )
    co = p.get("channel_override")
    if co is not None:
        if not isinstance(co, dict):
            return ["[INV12] channel_override phải là khối {kênh: chuỗi}"]
        instruction = instruction_of(p)
        for ch, text in co.items():
            if ch not in K2_CHANNELS:
                e.append(f"[INV12] channel_override khóa '{ch}' ∉ {K2_CHANNELS}")
                continue
            if ch not in channels:
                e.append(f"[INV12] channel_override.{ch} nhưng {ch} không nằm trong channels")
            if not isinstance(text, str) or not text:
                e.append(f"[INV12] channel_override.{ch} phải là chuỗi không rỗng")
                continue
            if _INSTRUCTION in text:
                e.append(f"[INV12] channel_override.{ch} còn {_INSTRUCTION}; điền nguyên văn chỉ thị")
            if instruction and instruction not in text:
                e.append(f"[INV12] channel_override.{ch} không chứa nguyên văn instruction_<lang>")
    for ch in channels:
        if ch in K2_CHANNELS:
            try:
                render_for_channel(p, ch, cfg=cfg)
            except ChannelRenderError as exc:
                e.append(f"[INV12] {exc}")
    return e
