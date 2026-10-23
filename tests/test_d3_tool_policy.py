"""D3 Tool-call Policy (STT-53) — điều kiện đạt ở defense_spec.md §5.5.

R1–R4 đủ test hai chiều (ca chặn + ca cho qua) · task_type=None bị chặn · hit R4 mang
action="confirm" · D3 không import carrier_tasks (kiểm đồ thị import). Thêm: enabled=false cho
qua, mọi luật vi phạm đều ghi hit, tất định, lời gọi bị chặn không tính vào R2/R3.
"""

import ast
import copy
from pathlib import Path

import pytest

from agent.llm_client import ToolCall
from defense import d3_tool_policy as d3
from interfaces import Decision, ExecutedCall, SessionState, ToolResult

MODULE_PATH = Path(d3.__file__)
BASE = d3.load_d3_config()


def _cfg(**rules_enabled):
    """Cấu hình thật, chỉ bật các luật được nêu (mặc định tắt hết) để test cô lập từng luật."""
    cfg = copy.deepcopy(BASE)
    for rid in d3.RULE_IDS:
        cfg["rules"][rid]["enabled"] = rules_enabled.get(rid[:2], False)
    return cfg


def _call(name, args=None, cid="c1"):
    return ToolCall(id=cid, name=name, arguments=args or {}, arguments_raw="{}")


def _done(name, *, meta=None, allowed=True, is_error=False):
    """Một mục lịch sử: tool-call đã qua gate (allowed) hoặc bị chặn."""
    decision = Decision() if allowed else Decision(action="block", reason="x")
    result = ToolResult(call_id="h", name=name, content="", is_error=is_error, meta=meta or {})
    return ExecutedCall(call=_call(name, cid="h"), decision=decision, result=result)


def _check(name, *, task_type="LOOKUP", history=(), cfg=None, enabled=True):
    session = SessionState(run_id="r1", task_type=task_type, history=list(history))
    return d3.check_tool_call(
        _call(name), session=session, task_type=task_type, enabled=enabled, config=cfg
    )


def _rules(decision):
    return [h.rule for h in decision.hits]


# --------------------------------------------------------------------- chung


def test_tat_thi_cho_qua_khong_hit():
    out = _check("send_email", task_type=None, enabled=False)
    assert out.allowed and out.hits == ()


def test_task_type_none_bi_chan_ke_ca_khi_R1_tat():
    out = _check("search_kb", task_type=None, cfg=_cfg())
    assert not out.allowed
    assert _rules(out) == [d3.R1]
    assert "task_type" in out.hits[0].detail


def test_task_type_la_loi_cau_hinh():
    with pytest.raises(ValueError, match="task_type"):
        _check("search_kb", task_type="SUY_RA_TU_CAU_HOI", cfg=_cfg())


def test_hit_dung_khoa_va_stage():
    out = _check("send_email", cfg=_cfg(R1=True))
    h = out.hits[0]
    assert (h.defense, h.stage, h.action) == ("d3_tool_policy", "pre_tool_execution", "block")
    assert out.reason.startswith("D3 chặn") and d3.R1 in out.reason


# --------------------------------------------------------------------- R1


@pytest.mark.parametrize(
    "task_type,tool",
    [("LOOKUP", "send_email"), ("LOOKUP", "http_request"), ("SEND_MAIL", "create_ticket")],
)
def test_R1_chan_tool_ngoai_allowlist(task_type, tool):
    out = _check(tool, task_type=task_type, cfg=_cfg(R1=True))
    assert not out.allowed and _rules(out) == [d3.R1]


@pytest.mark.parametrize(
    "task_type,tool",
    [("LOOKUP", "search_kb"), ("REPORT", "http_request"), ("SEND_MAIL", "send_email")],
)
def test_R1_cho_qua_tool_trong_allowlist(task_type, tool):
    assert _check(tool, task_type=task_type, cfg=_cfg(R1=True)).allowed


def test_R1_chan_tool_bia():
    assert _rules(_check("delete_all", cfg=_cfg(R1=True))) == [d3.R1]


# --------------------------------------------------------------------- R2


def test_R2_chan_egress_sau_doc_rong():
    hist = [_done("query_customer_db", meta={"row_count": 20})]
    out = _check("send_email", task_type="SEND_MAIL", history=hist, cfg=_cfg(R2=True))
    assert not out.allowed and _rules(out) == [d3.R2]
    assert "row_count=20" in out.hits[0].detail


def test_R2_cho_qua_egress_sau_doc_hep():
    hist = [_done("query_customer_db", meta={"row_count": 1})]
    assert _check("send_email", task_type="SEND_MAIL", history=hist, cfg=_cfg(R2=True)).allowed


def test_R2_cho_qua_tool_doc_sau_doc_rong():
    hist = [_done("query_customer_db", meta={"row_count": 50})]
    assert _check("search_kb", history=hist, cfg=_cfg(R2=True)).allowed


def test_R2_bo_qua_lan_doc_bi_chan_hoac_loi():
    hist = [
        _done("query_customer_db", meta={"row_count": 50}, allowed=False),
        _done("query_customer_db", meta={"row_count": 50}, is_error=True),
    ]
    assert _check("send_email", task_type="SEND_MAIL", history=hist, cfg=_cfg(R2=True)).allowed


# --------------------------------------------------------------------- R3


def test_R3_chan_egress_thu_hai():
    hist = [_done("http_request")]
    out = _check("send_email", task_type="SEND_MAIL", history=hist, cfg=_cfg(R3=True))
    assert not out.allowed and _rules(out) == [d3.R3]


def test_R3_cho_qua_egress_dau_tien():
    hist = [_done("search_kb"), _done("query_customer_db", meta={"row_count": 1})]
    assert _check("send_email", task_type="SEND_MAIL", history=hist, cfg=_cfg(R3=True)).allowed


def test_R3_khong_tinh_lan_egress_bi_chan():
    hist = [_done("send_email", allowed=False)]
    assert _check("send_email", task_type="SEND_MAIL", history=hist, cfg=_cfg(R3=True)).allowed


def test_R3_doc_han_muc_tu_config():
    cfg = _cfg(R3=True)
    cfg["rules"][d3.R3]["max_egress_calls_per_turn"] = 2
    hist = [_done("send_email")]
    assert _check("send_email", task_type="SEND_MAIL", history=hist, cfg=cfg).allowed


# --------------------------------------------------------------------- R4


@pytest.mark.parametrize("tool", ["send_email", "http_request", "create_ticket"])
def test_R4_chan_va_hit_mang_confirm(tool):
    out = _check(tool, task_type="REPORT", cfg=_cfg(R4=True))
    assert not out.allowed
    assert _rules(out) == [d3.R4]
    assert out.hits[0].action == "confirm"


@pytest.mark.parametrize("tool", ["search_kb", "query_customer_db"])
def test_R4_cho_qua_tool_doc(tool):
    assert _check(tool, cfg=_cfg(R4=True)).allowed


def test_R4_tool_khong_khai_muc_hau_qua_that_bai_ve_phia_dong():
    out = _check("delete_all", cfg=_cfg(R4=True))
    assert _rules(out) == [d3.R4] and "không khai" in out.hits[0].detail


def test_preset_d3_no_confirm_cho_qua_gui_thu_hop_le():
    # R4 tắt (preset_overrides): SEND_MAIL gửi một thư sau khi đọc một dòng — R1–R3 đều cho qua.
    cfg = _cfg(R1=True, R2=True, R3=True)
    hist = [_done("query_customer_db", meta={"row_count": 1})]
    assert _check("send_email", task_type="SEND_MAIL", history=hist, cfg=cfg).allowed


# --------------------------------------------------------------------- ghép luật


def test_moi_luat_vi_pham_deu_ghi_hit():
    hist = [_done("query_customer_db", meta={"row_count": 30}), _done("http_request")]
    out = _check("send_email", task_type="LOOKUP", history=hist, cfg=BASE)
    assert _rules(out) == list(d3.RULE_IDS)
    assert [h.action for h in out.hits] == ["block", "block", "block", "confirm"]


def test_tat_dinh():
    hist = [_done("query_customer_db", meta={"row_count": 30})]
    outs = {_check("send_email", task_type="SEND_MAIL", history=hist, cfg=BASE) for _ in range(100)}
    assert len(outs) == 1


def test_cau_hinh_that_hop_le():
    d3.validate_d3_config(BASE)


def test_cau_hinh_muc_hau_qua_la_bi_tu_choi():
    cfg = copy.deepcopy(BASE)
    cfg["rules"][d3.R4]["consequential_severities"] = ["nguy_hiem"]
    with pytest.raises(ValueError, match="nguy_hiem"):
        d3.validate_d3_config(cfg)


def test_cau_hinh_automated_resolution_la_bi_tu_choi():
    cfg = copy.deepcopy(BASE)
    cfg["rules"][d3.R4]["automated_resolution"] = "allow"
    with pytest.raises(ValueError, match="automated_resolution"):
        d3.validate_d3_config(cfg)


# --------------------------------------------------------------------- bất biến mã nguồn


def _imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_khong_doc_dap_an_cua_bo_cham():
    # Nguyên tắc 5 + điều kiện đạt §5.5: D3 không import, không nhắc tới file đáp án.
    imported = _imports(MODULE_PATH)
    assert imported <= {"__future__", "pathlib", "typing", "yaml", "interfaces"}, imported
    # Mã thực thi (bỏ docstring module và comment — chỗ được phép nhắc tên file để giải thích).
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    tree.body = tree.body[1:]
    code = ast.unparse(tree)
    for forbidden in ("carrier_tasks", "benign_queries", "eval."):
        assert forbidden not in code


def test_khong_phan_loai_y_dinh_tu_do():
    # Quy tắc cứng #3: không regex/NLU/LLM trong D3.
    imported = _imports(MODULE_PATH)
    for banned in ("re", "regex", "openai", "agent.llm_client", "fastembed"):
        assert banned not in imported
