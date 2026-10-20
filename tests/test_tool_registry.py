"""Tool registry (STT-27): năm schema function-calling, mô tả thay được, nhãn rủi ro.

`config/tools.yaml` không được lệch `agent_tools` của `data/carrier_tasks.json` (đã khóa) và
allowlist D3 trong `config/defenses.yaml` — một khái niệm, một nguồn.
"""

import json
from pathlib import Path

import pytest
import yaml

from agent.llm_client import ToolCall
from interfaces import KB_TOOL, ToolLayer, ToolResult, ToolSpec
from tools.registry import ToolRegistry, ToolsConfigError, load_tool_defs, validate_args

ROOT = Path(__file__).resolve().parents[1]
CARRIER = json.loads((ROOT / "data" / "carrier_tasks.json").read_text(encoding="utf-8"))
DEFENSES = yaml.safe_load((ROOT / "config" / "defenses.yaml").read_text(encoding="utf-8"))
AGENT_TOOLS = CARRIER["agent_tools"]


def _call(name: str, args: dict | None, *, parse_error: bool = False) -> ToolCall:
    return ToolCall(
        id="c1", name=name, arguments=args, arguments_raw=json.dumps(args), parse_error=parse_error
    )


@pytest.fixture
def reg() -> ToolRegistry:
    return ToolRegistry()


# -- khớp nguồn chân lý ------------------------------------------------------


def test_dung_nam_tool_tl1_tl5():
    defs = load_tool_defs()
    assert list(defs) == list(AGENT_TOOLS)
    assert sorted(d.code for d in defs.values()) == ["TL1", "TL2", "TL3", "TL4", "TL5"]
    assert KB_TOOL in defs


def test_nhan_rui_ro_khop_carrier_tasks():
    for name, d in load_tool_defs().items():
        assert d.kind == AGENT_TOOLS[name]["kind"], name
        assert d.side_effect == AGENT_TOOLS[name]["side_effect"], name


def test_tham_so_khop_carrier_tasks_cung_thu_tu():
    for name, d in load_tool_defs().items():
        assert list(d.input_schema["properties"]) == AGENT_TOOLS[name]["args"], name


def test_outbound_dong_nghia_side_effect():
    for name, d in load_tool_defs().items():
        assert (d.kind == "outbound") == d.side_effect, name


def test_allowlist_d3_chi_dung_ten_tool_co_that():
    names = set(load_tool_defs())
    for task_type, body in DEFENSES["defenses"]["d3_tool_policy"]["task_types"].items():
        assert set(body["allowlist"]) <= names, task_type


def test_mo_ta_query_customer_db_khop_max_rows():
    d = load_tool_defs()["query_customer_db"]
    assert f"tối đa {d.params['max_rows']} bản ghi" in d.description


def test_mo_ta_goc_khong_co_dau_ngoac_nhon():
    # D2 không quét K2a vì sợ strip nhầm `{parameter}`; mô tả gốc không dùng ngoặc nhọn để bản gốc
    # và bản K2a phân biệt được bằng mắt trong trace.
    for name, d in load_tool_defs().items():
        assert "{" not in d.description, name


# -- schema function-calling -------------------------------------------------


def test_list_tools_ra_schema_openai_hop_le(reg):
    specs = reg.list_tools()
    assert all(isinstance(s, ToolSpec) for s in specs)
    for s in specs:
        fn = s.to_openai()
        assert fn["type"] == "function"
        assert fn["function"]["name"] == s.name
        params = fn["function"]["parameters"]
        assert params["type"] == "object"
        assert params["additionalProperties"] is False
        assert set(params["required"]) <= set(params["properties"])
        for prop in params["properties"].values():
            assert prop.get("description"), s.name


def test_registry_thoa_protocol_tool_layer(reg):
    assert isinstance(reg, ToolLayer)


# -- mô tả thay được (K2a, rug-pull) ------------------------------------------


def test_set_description_thay_trong_list_tools_ke_tiep(reg):
    before = {s.name: s.description for s in reg.list_tools()}
    reg.set_description("send_email", "PAYLOAD")
    after = {s.name: s.description for s in reg.list_tools()}
    assert after["send_email"] == "PAYLOAD"
    assert reg.is_overridden("send_email")
    assert reg.baseline_description("send_email") == before["send_email"]
    assert {k: v for k, v in after.items() if k != "send_email"} == {
        k: v for k, v in before.items() if k != "send_email"
    }


def test_rug_pull_doi_mo_ta_giua_hai_lan_lay_danh_sach(reg):
    first = reg.list_tools()
    reg.set_description("http_request", "bản sau khi đã duyệt")
    second = reg.list_tools()
    assert first[2].description != second[2].description
    # ToolSpec cũ không bị đổi theo — lõi agent giữ đúng bản nó đã đưa model
    assert first[2].description == reg.baseline_description("http_request")


def test_reset_descriptions_tra_ve_ban_goc(reg):
    reg.set_description("create_ticket", "X")
    reg.reset_descriptions()
    assert not reg.is_overridden("create_ticket")
    assert reg.description("create_ticket") == reg.baseline_description("create_ticket")


def test_override_khong_ro_sang_registry_khac():
    a, b = ToolRegistry(), ToolRegistry()
    a.set_description("search_kb", "X")
    assert b.description("search_kb") == b.baseline_description("search_kb")


def test_set_description_tool_la_bao_loi(reg):
    with pytest.raises(KeyError):
        reg.set_description("delete_all", "X")


def test_schema_va_nhan_khong_doi_khi_ghi_de_mo_ta(reg):
    base = {s.name: (s.input_schema, s.kind, s.side_effect) for s in reg.list_tools()}
    for name in reg.names:
        reg.set_description(name, "X")
    assert {s.name: (s.input_schema, s.kind, s.side_effect) for s in reg.list_tools()} == base


# -- điều phối handler ---------------------------------------------------------


def test_call_tool_chuyen_handler_va_dien_call_id(reg):
    seen = {}

    def handler(args):
        seen.update(args)
        return ToolResult(call_id="", name="", content="ok", meta={"rows": 1})

    reg.bind("query_customer_db", handler)
    res = reg.call_tool(_call("query_customer_db", {"sql_or_filter": "id = 3"}))
    assert seen == {"sql_or_filter": "id = 3"}
    assert (res.call_id, res.name, res.content, res.is_error) == (
        "c1",
        "query_customer_db",
        "ok",
        False,
    )
    assert res.meta == {"rows": 1}


def test_tool_khong_ton_tai_tra_loi_cho_model(reg):
    res = reg.call_tool(_call("delete_customer", {"id": 1}))
    assert res.is_error and res.meta["error"] == "unknown_tool"


@pytest.mark.parametrize(
    "name,args,fragment",
    [
        (
            "send_email",
            {"to": "a@congty-noibo.vn", "subject": "s"},
            "thiếu tham số bắt buộc 'body'",
        ),
        ("search_kb", {"query": "x", "top": 3}, "tham số lạ 'top'"),
        ("search_kb", {"query": "x", "k": 0}, "phải ≥ 1"),
        ("search_kb", {"query": "x", "k": True}, "phải là integer"),
        ("http_request", {"method": "DELETE", "url": "u"}, "phải thuộc"),
        (
            "create_ticket",
            {"customer_id": "7", "title": "t", "body": "b", "priority": "high"},
            "phải là integer",
        ),
        ("send_email", {"to": "a", "subject": "s", "body": "b", "attachments": [1]}, "[0]"),
    ],
)
def test_tham_so_sai_tra_loi_cho_model(reg, name, args, fragment):
    reg.bind(name, lambda a: pytest.fail("không được gọi handler khi tham số sai"))
    res = reg.call_tool(_call(name, args))
    assert res.is_error and res.meta["error"] == "invalid_args"
    assert fragment in res.content


def test_chua_gan_handler_la_loi_harness(reg):
    with pytest.raises(LookupError):
        reg.call_tool(_call("search_kb", {"query": "bảo hành"}))


def test_parse_error_khong_toi_registry(reg):
    with pytest.raises(ValueError):
        reg.call_tool(_call("search_kb", None, parse_error=True))


def test_validate_args_hop_le_rong():
    schema = load_tool_defs()["create_ticket"].input_schema
    args = {"customer_id": 7, "title": "t", "body": "b", "priority": "high"}
    assert validate_args(schema, args) == []


# -- kiểm config ------------------------------------------------------------------


def test_config_khoa_la_bi_tu_choi(tmp_path):
    raw = yaml.safe_load((ROOT / "config" / "tools.yaml").read_text(encoding="utf-8"))
    raw["tools"]["search_kb"]["risk"] = "low"
    p = tmp_path / "tools.yaml"
    p.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ToolsConfigError, match="khóa lạ"):
        load_tool_defs(p)


def test_config_kind_sai_bi_tu_choi(tmp_path):
    raw = yaml.safe_load((ROOT / "config" / "tools.yaml").read_text(encoding="utf-8"))
    raw["tools"]["create_ticket"]["kind"] = "write"
    p = tmp_path / "tools.yaml"
    p.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ToolsConfigError, match="kind"):
        load_tool_defs(p)


def test_build_tool_layer_cho_mcp_server():
    from tools.registry import build_tool_layer

    raw = yaml.safe_load((ROOT / "config" / "tools.yaml").read_text(encoding="utf-8"))
    assert raw["mcp_server"]["backend"] == "tools.registry:build_tool_layer"
    layer = build_tool_layer()
    assert isinstance(layer, ToolLayer)
    assert [s.name for s in layer.list_tools()] == list(AGENT_TOOLS)
