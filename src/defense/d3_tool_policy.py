"""d3_tool_policy.py — D3 Tool-call Policy, máy trạng thái ngoài LLM (STT-53).

Vì sao có file này: kiểm tool-call model đề xuất TRƯỚC khi thi hành, bằng luật tra bảng trên
tool-call và lịch sử phiên — không đọc hiểu văn bản, nên không phụ thuộc mô hình có bị thao túng
hay không. Đặc tả hành vi, luật, hit và điều kiện đạt: `docs/04. Design/defense_spec.md` mục 5.
Hook: `PRE_TOOL_EXECUTION` (interfaces.py).

Nguyên tắc (defense_spec mục 1, 5.3):
- Mọi tham số đọc từ `config/defenses.yaml` → `defenses.d3_tool_policy`, KHÔNG hard-code
  (quy tắc cứng #4).
- KHÔNG phân loại ý định tự do (regex/NLU/LLM) — quy tắc cứng #3. `task_type` là input người dùng
  chọn trước phiên; `None` ⇒ chặn, không đoán. Module cố ý không import `re`.
- Không đọc `data/carrier_tasks.json` hay `data/benign_queries.json` (nguyên tắc 5): phòng thủ
  đọc đáp án thì DSR = 100% do định nghĩa.
- Tất định: hàm thuần của (proposed, session.history, task_type, config).

Bốn luật (spec §5.2), đánh giá ĐỦ cả bốn, mỗi luật vi phạm ghi một hit:
- R1 `task_type_allowlist`        — tên tool ∉ allowlist(task_type).
- R2 `block_broad_read_then_egress` — tool egress sau một lần đọc `query_customer_db` có
  `row_count > ngưỡng` (đọc `ToolResult.meta`, không đọc văn bản kết quả).
- R3 `egress_rate_limit`          — số egress đã thực thi trong run ≥ hạn mức.
- R4 `require_confirmation`       — mức hậu quả ∈ consequential_severities. Hit mang
  `action="confirm"`; quyết định quy về `block` theo `automated_resolution`.

"Đã thực thi" (R2, R3) = mục lịch sử có `decision.allowed` — gate đã cho qua và tầng công cụ đã
được gọi, kể cả khi tool trả `is_error`. Lời gọi bị chặn không tính.

Chỉ dùng thư viện chuẩn + pyyaml.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from interfaces import Decision, DefenseHit, HookStage, SessionState

__all__ = ["check_tool_call", "load_d3_config", "validate_d3_config", "RULE_IDS"]

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "defenses.yaml"

_DEFENSE_KEY = "d3_tool_policy"
_STAGE = HookStage.PRE_TOOL_EXECUTION.value  # "pre_tool_execution" — khớp DefenseHit.stage

R1 = "R1_task_type_allowlist"
R2 = "R2_block_broad_read_then_egress"
R3 = "R3_egress_rate_limit"
R4 = "R4_require_confirmation"
RULE_IDS: tuple[str, ...] = (R1, R2, R3, R4)

#: Giá trị `automated_resolution` hiện thực được. Chạy tự động không có người duyệt (spec §5.2).
_AUTOMATED_RESOLUTIONS = ("block",)


def load_d3_config(path: Path | str = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Nạp và kiểm khối `defenses.d3_tool_policy`. Tách ra để test tiêm cấu hình."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    cfg = raw["defenses"][_DEFENSE_KEY]
    validate_d3_config(cfg)
    return cfg


def validate_d3_config(cfg: dict[str, Any]) -> None:
    """Ném `ValueError` khi cấu hình D3 thiếu luật, mức hậu quả lạ hoặc allowlist trỏ tool lạ."""
    rules = cfg["rules"]
    missing = [r for r in RULE_IDS if r not in rules]
    if missing:
        raise ValueError(f"d3_tool_policy.rules thiếu {missing}")
    severity = cfg["tool_severity"]
    known_levels = set(severity.values())
    for level in rules[R4]["consequential_severities"]:
        if level not in known_levels:
            raise ValueError(f"R4 consequential_severities có mức '{level}' không có trong tool_severity")
    if rules[R4]["automated_resolution"] not in _AUTOMATED_RESOLUTIONS:
        raise ValueError(
            f"R4 automated_resolution phải thuộc {_AUTOMATED_RESOLUTIONS}, "
            f"nhận '{rules[R4]['automated_resolution']}'"
        )
    for name, body in cfg["task_types"].items():
        unknown = set(body["allowlist"]) - set(severity)
        if unknown:
            raise ValueError(f"task_types.{name}.allowlist có tool không khai tool_severity: {unknown}")


def _executed(session: SessionState) -> list[Any]:
    """Các mục lịch sử đã qua gate (xem docstring module: định nghĩa "đã thực thi")."""
    return [e for e in session.history if e.decision.allowed]


def _hit(rule: str, detail: str, action: str = "block") -> DefenseHit:
    return DefenseHit(defense=_DEFENSE_KEY, stage=_STAGE, action=action, rule=rule, detail=detail)


def _r1(name: str, task_type: str, cfg: dict[str, Any]) -> DefenseHit | None:
    allowlist = cfg["task_types"][task_type]["allowlist"]
    if name in allowlist:
        return None
    return _hit(R1, f"tool={name} ngoài allowlist của task_type={task_type}")


def _r2(name: str, session: SessionState, rule: dict[str, Any]) -> DefenseHit | None:
    if name not in rule["applies_to_egress_tools"]:
        return None
    threshold = int(rule["broad_read_threshold_rows"])
    read_tool = rule["applies_to_read_tool"]
    for e in _executed(session):
        if e.call.name != read_tool or e.result is None or e.result.is_error:
            continue
        rows = e.result.meta.get("row_count")
        if rows is not None and int(rows) > threshold:
            return _hit(R2, f"tool={name} sau {read_tool} row_count={rows} > {threshold}")
    return None


def _r3(name: str, session: SessionState, rule: dict[str, Any]) -> DefenseHit | None:
    egress = rule["applies_to_egress_tools"]
    if name not in egress:
        return None
    limit = int(rule["max_egress_calls_per_turn"])
    done = sum(1 for e in _executed(session) if e.call.name in egress)
    if done < limit:
        return None
    return _hit(R3, f"tool={name}: đã thực thi {done} lời gọi egress, hạn mức {limit}")


def _r4(name: str, cfg: dict[str, Any], rule: dict[str, Any]) -> DefenseHit | None:
    # Tool không khai mức hậu quả (model bịa tên tool) ⇒ coi là có hậu quả: thất bại về phía đóng.
    level = cfg["tool_severity"].get(name)
    if level is not None and level not in rule["consequential_severities"]:
        return None
    shown = level if level is not None else "không khai"
    return _hit(R4, f"tool={name} mức hậu quả={shown} cần xác nhận", action="confirm")


def check_tool_call(
    proposed: Any,
    *,
    session: SessionState,
    task_type: str | None,
    enabled: bool,
    config: dict[str, Any] | None = None,
) -> Decision:
    """Kiểm một tool-call đề xuất (D3 — spec §5). Trả `Decision(allow|block, reason, hits)`.

    `proposed` là `ToolCall` (đã qua kiểm parse_error ở lõi agent). `task_type` do bên gọi truyền
    từ `session.task_type` — tham số tách riêng để chữ ký khớp spec §2. `config` mặc định đọc từ
    `defenses.yaml`; cho phép tiêm để test không phụ thuộc file.
    """
    if not enabled:
        return Decision(action="allow")

    cfg = config if config is not None else load_d3_config()
    rules = cfg["rules"]
    name = proposed.name

    # Phiên không khai task_type ⇒ chặn, không đoán (spec §5.1). Đây là R1 với allowlist rỗng, và
    # áp dụng kể cả khi R1 tắt: thiếu input là lỗi phiên, không phải một luật để bật/tắt.
    if task_type is None:
        hit = _hit(R1, f"tool={name}: phiên không khai task_type")
        return Decision(action="block", reason=_reason((hit,)), hits=(hit,))
    if task_type not in cfg["task_types"]:
        # Lỗi cấu hình thí nghiệm, không phải hành vi model — ném để run hỏng ồn ào.
        raise ValueError(f"task_type '{task_type}' không có trong d3_tool_policy.task_types")

    candidates = (
        _r1(name, task_type, cfg) if rules[R1]["enabled"] else None,
        _r2(name, session, rules[R2]) if rules[R2]["enabled"] else None,
        _r3(name, session, rules[R3]) if rules[R3]["enabled"] else None,
        _r4(name, cfg, rules[R4]) if rules[R4]["enabled"] else None,
    )
    hits = tuple(h for h in candidates if h is not None)
    if not hits:
        return Decision(action="allow")
    # Hit R1–R3 là block; hit R4 là confirm, quy về block theo automated_resolution (đã kiểm chỉ
    # nhận "block"). Nên có hit nào cũng là block.
    return Decision(action="block", reason=_reason(hits), hits=hits)


def _reason(hits: tuple[DefenseHit, ...]) -> str:
    """Lý do trả cho model và adaptive attacker (STT-57): mã luật + chi tiết, nối bằng '; '."""
    return "D3 chặn — " + "; ".join(f"{h.rule}: {h.detail}" for h in hits)
