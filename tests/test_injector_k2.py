"""test_injector_k2.py — kiểm injector kênh K2 (STT-45).

Chạy HOÀN TOÀN offline: không Qdrant, không model. Dùng `ToolLayer` giả (`FakeLayer`) phơi vài
ToolSpec và trả ToolResult tất định, để kiểm hành vi bọc ngoài của `K2ToolLayer`:

  * K2a — description tool đích mang payload sau khi bọc; tool khác nguyên vẹn.
  * K2a rug-pull — phục vụ bản gốc tới lần `list_tools` thứ N, từ lần kế tiếp mới chở payload.
  * K2b — content kết quả tool đọc json.loads được và có trường chở; kết quả lỗi / tuyến ngoài KHÔNG chở.
  * Ghép kênh — từ chối tool/carrier sai kênh; `delivered` luôn True.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from agent.llm_client import ToolCall
from attack import injector_k2 as k2
from attack.injector_k2 import InjectorK2Error
from attack.payloads.render import render_for_channel
from interfaces import ToolResult, ToolSpec

REPO_ROOT = Path(__file__).resolve().parents[1]
PAYLOAD_DIR = REPO_ROOT / "src" / "attack" / "payloads"
CARRIER_TASKS = REPO_ROOT / "data" / "carrier_tasks.json"

# Payload thật có cả K2a và K2b; goal tool = create_ticket (chở K2a ở CT-06) và không chở K2b nên
# K2b rơi về tool đọc trong allowed_tools (query_customer_db hoặc http_request).
K2_PAYLOAD = ("t1_explicit.yaml", "P-T1-G2-VI-001")


def _payload(file: str, pid: str) -> dict:
    data = yaml.safe_load((PAYLOAD_DIR / file).read_text(encoding="utf-8"))
    items = data["payloads"] if isinstance(data, dict) else data
    for p in items:
        if p["id"] == pid:
            return p
    raise KeyError(pid)


def _carrier(cid: str) -> dict:
    data = json.loads(CARRIER_TASKS.read_text(encoding="utf-8"))
    for ct in data["carrier_tasks"]:
        if ct["id"] == cid:
            return ct
    raise KeyError(cid)


def _all_carriers() -> list[dict]:
    return json.loads(CARRIER_TASKS.read_text(encoding="utf-8"))["carrier_tasks"]


class FakeLayer:
    """`ToolLayer` giả: danh sách tool cố định + call_tool tất định cho query_customer_db/http_request."""

    def __init__(self) -> None:
        self.descriptions = {
            "search_kb": "Tìm kiếm kho tri thức nội bộ.",
            "query_customer_db": "Tra cứu cơ sở dữ liệu khách hàng.",
            "http_request": "Gửi yêu cầu HTTP tới API nội bộ.",
            "create_ticket": "Tạo phiếu yêu cầu hỗ trợ.",
        }

    def list_tools(self) -> list[ToolSpec]:
        kinds = {"search_kb": "read", "query_customer_db": "read",
                 "http_request": "outbound", "create_ticket": "outbound"}
        side = {"search_kb": False, "query_customer_db": False,
                "http_request": True, "create_ticket": True}
        return [
            ToolSpec(name=n, description=d, input_schema={"type": "object"},
                     kind=kinds[n], side_effect=side[n])
            for n, d in self.descriptions.items()
        ]

    def call_tool(self, call: ToolCall) -> ToolResult:
        if call.name == "query_customer_db":
            content = json.dumps(
                {"columns": ["id", "name"], "rows": [[1, "A"]], "row_count": 1, "truncated": False},
                ensure_ascii=False,
            )
            return ToolResult(call_id=call.id, name=call.name, content=content, meta={})
        if call.name == "http_request":
            body = json.dumps({"quantity": 142}, ensure_ascii=False)
            content = json.dumps({"status": 200, "body": body}, ensure_ascii=False)
            route = (call.arguments or {}).get("_route", "intranet")
            return ToolResult(call_id=call.id, name=call.name, content=content, meta={"route": route})
        return ToolResult(call_id=call.id, name=call.name, content="{}", meta={})


def _call(name: str, **args) -> ToolCall:
    return ToolCall(id="c1", name=name, arguments=args, arguments_raw=json.dumps(args))


# ───────────────────────── K2a: description động ─────────────────────────
def test_k2a_description_mang_payload():
    """Tool đích có description = gốc + payload; tool khác giữ nguyên."""
    payload = _payload(*K2_PAYLOAD)
    carrier = _carrier("CT-06")  # allowed có create_ticket → K2a target = create_ticket (goal tool)
    layer = k2.build_layer(FakeLayer(), payload, carrier, "K2a", "run-a")
    assert layer.result.target_tool == "create_ticket"
    text = render_for_channel(payload, "K2a")

    specs = {s.name: s.description for s in layer.list_tools()}
    assert text in specs["create_ticket"]
    assert specs["create_ticket"].startswith("Tạo phiếu")  # giữ câu gốc
    assert specs["search_kb"] == "Tìm kiếm kho tri thức nội bộ."  # không đụng tool khác
    assert layer.result.delivered is True


def test_k2a_fallback_search_kb_khi_goal_tool_ngoai_allowed():
    """goal tool (create_ticket) không trong allowed_tools của CT-03 → chở qua search_kb."""
    payload = _payload(*K2_PAYLOAD)
    carrier = _carrier("CT-03")  # allowed: search_kb, query_customer_db
    layer = k2.build_layer(FakeLayer(), payload, carrier, "K2a", "run-a2")
    assert layer.result.target_tool == "search_kb"
    specs = {s.name: s.description for s in layer.list_tools()}
    assert render_for_channel(payload, "K2a") in specs["search_kb"]


def test_k2a_rug_pull_doi_mo_ta_sau_lan_list_thu_n():
    """rug-pull: lần list đầu phục vụ bản gốc, lần kế tiếp mới chở payload."""
    payload = _payload(*K2_PAYLOAD)
    carrier = _carrier("CT-06")
    layer = k2.build_layer(FakeLayer(), payload, carrier, "K2a", "run-rug", rug_pull=True)
    text = render_for_channel(payload, "K2a")

    first = {s.name: s.description for s in layer.list_tools()}
    assert text not in first["create_ticket"]  # còn bản gốc (đã "duyệt")
    second = {s.name: s.description for s in layer.list_tools()}
    assert text in second["create_ticket"]     # rug-pull đã lật


# ───────────────────────── K2b: content kết quả ─────────────────────────
def test_k2b_chen_truong_cho_vao_ket_qua():
    """query_customer_db: content sau bọc vẫn json.loads được và mang trường chở."""
    payload = _payload(*K2_PAYLOAD)
    carrier = _carrier("CT-03")
    layer = k2.build_layer(FakeLayer(), payload, carrier, "K2b", "run-b")
    assert layer.result.target_tool == "query_customer_db"

    raw = layer.call_tool(_call("query_customer_db", sql_or_filter="id = 1"))
    obj = json.loads(raw.content)  # harness: phải roundtrip được
    assert obj["ghi_chu"] == render_for_channel(payload, "K2b")
    assert layer.result.applied is True


def test_k2b_khong_cham_tool_khac():
    payload = _payload(*K2_PAYLOAD)
    layer = k2.build_layer(FakeLayer(), payload, _carrier("CT-03"), "K2b", "run-b2")
    raw = layer.call_tool(_call("search_kb", query="x"))
    assert raw.content == "{}"
    assert layer.result.applied is False


def test_k2b_khong_cho_ket_qua_loi():
    """Kết quả is_error không bị chèn (tránh dựng JSON vô nghĩa)."""
    payload = _payload(*K2_PAYLOAD)
    carrier = _carrier("CT-03")
    layer = k2.build_layer(FakeLayer(), payload, carrier, "K2b", "run-b3")

    class ErrLayer(FakeLayer):
        def call_tool(self, call):
            return ToolResult(call_id=call.id, name=call.name, content="lỗi", is_error=True, meta={})

    layer._base = ErrLayer()
    raw = layer.call_tool(_call("query_customer_db", sql_or_filter="x"))
    assert raw.is_error and raw.content == "lỗi"
    assert layer.result.applied is False


def test_k2b_http_tuyen_ngoai_khong_cho():
    """http_request tuyến external: phản hồi cố định, K2b không chở (channel_render routes:[intranet])."""
    payload = _payload(*K2_PAYLOAD)
    carrier = _carrier("CT-04")  # http_request là tool đọc chở K2b ở đây
    layer = k2.build_layer(FakeLayer(), payload, carrier, "K2b", "run-b4")
    assert layer.result.target_tool == "http_request"

    ext = layer.call_tool(_call("http_request", method="GET", url="x", _route="external"))
    assert "ghi_chu" not in json.loads(ext.content)
    intra = layer.call_tool(_call("http_request", method="GET", url="x", _route="intranet"))
    assert "ghi_chu" in json.loads(json.loads(intra.content)["body"])


# ───────────────────────── Ghép kênh + lỗi harness ─────────────────────────
def test_build_tu_choi_carrier_khong_khai_kenh():
    payload = _payload(*K2_PAYLOAD)
    carrier = _carrier("CT-01")  # chỉ K1
    with pytest.raises(InjectorK2Error):
        k2.build_layer(FakeLayer(), payload, carrier, "K2a", "x")


def test_rug_pull_chi_ap_k2a():
    payload = _payload(*K2_PAYLOAD)
    with pytest.raises(InjectorK2Error):
        k2.build_layer(FakeLayer(), payload, _carrier("CT-03"), "K2b", "x", rug_pull=True)


def test_valid_carriers_k2a_va_k2b():
    payload = _payload(*K2_PAYLOAD)
    carriers = _all_carriers()
    va = k2.valid_carriers(payload, "K2a", carriers)
    vb = k2.valid_carriers(payload, "K2b", carriers)
    assert "CT-01" not in va and "CT-02" not in va      # chỉ K1
    assert set(va) >= {"CT-03", "CT-04", "CT-05", "CT-06"}
    assert set(vb) >= {"CT-03", "CT-04", "CT-05", "CT-06"}


def test_trace_fields():
    payload = _payload(*K2_PAYLOAD)
    layer = k2.build_layer(FakeLayer(), payload, _carrier("CT-03"), "K2b", "run-t")
    assert layer.result.trace_fields() == {"channel": "K2b", "delivered": True}
