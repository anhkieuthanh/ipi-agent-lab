"""pipeline.py — tầng phòng thủ D1–D4 cắm vào năm hook của lõi agent (STT-55).

Vì sao có file này: hiện thực `interfaces.DefenseLayer` bằng cách đọc `config/defenses.yaml` — cơ
chế nào bật, chạy ở hook nào, theo thứ tự nào, với tham số nào. Lõi agent gọi đủ năm hook ở mọi run;
file này quyết cơ chế nào chạy (defense_spec mục 1 nguyên tắc 2, mục 2).

Nguyên tắc:
- Không tham số hành vi nào ở đây (quy tắc cứng #4). Hook → cơ chế lấy từ `pipeline_order`; hàm của
  cơ chế lấy từ `module` + `entrypoint` của khối; tham số truyền nguyên khối `defenses.<khóa>` đã áp
  `preset_overrides`. Hằng trong file chỉ là cách gọi từng chữ ký cố định ở defense_spec mục 2.
- Ba cách chọn cơ chế bật, loại trừ nhau:
  `preset` (tên preset dạng danh sách trong `presets`, áp cả `preset_overrides` của nó) — đường của
  ma trận; `enabled` (tập khóa tùy chọn, không override) — mọi tổ hợp bật/tắt; không truyền gì —
  đọc cờ `enabled` của từng khối.
- Hook transform chạy MỌI cơ chế được xếp vào hook, nối tiếp. Hook gate chạy lần lượt, dừng ở cơ
  chế đầu tiên trả `block`; hit của cơ chế đã chạy trước được giữ.
- `config_snapshot()` là cấu hình hiệu lực, ghi vào `runs.defense_config` và là danh tính resume
  của runner. Preset `off` trả đúng ảnh chụp của `NoDefense` để store cũ resume được.
- Tất định ngoài phần D1 cố ý ngẫu nhiên (delimiter theo run). `end_run(run_id)` dọn cache D1.

Chỉ dùng thư viện chuẩn + pyyaml.
"""

from __future__ import annotations

import copy
import hashlib
import importlib
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import yaml

from defense import d1_spotlighting
from defense.d3_tool_policy import validate_d3_config
from defense.d4_egress_filter import EgressAllowlist, build_egress_allowlist, validate_d4_config
from eval.canary import DEFAULT_CUSTOMERS_DB
from interfaces import Decision, DefenseHit, HookStage, SessionState, Transformed, check_stage

__all__ = ["DefensePipeline", "DEFAULT_CONFIG_PATH", "load_defenses_raw", "runnable_presets"]

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "defenses.yaml"

D1 = "d1_spotlighting"
D2 = "d2_input_sanitizer"
D3 = "d3_tool_policy"
D4 = "d4_egress_filter"

#: Kiểm cấu hình của cơ chế có hàm kiểm riêng; chạy lúc dựng pipeline, sau khi áp override.
_VALIDATORS: dict[str, Callable[[dict[str, Any]], None]] = {
    D3: validate_d3_config,
    D4: validate_d4_config,
}


def load_defenses_raw(path: Path | str = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Nạp nguyên `defenses.yaml`."""
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def runnable_presets(raw: dict[str, Any]) -> list[str]:
    """Preset chạy được: giá trị là danh sách cơ chế. Nhóm preset (`reduced_3`) không phải một."""
    return [name for name, value in raw["presets"].items() if isinstance(value, list)]


def _stage_map(raw: dict[str, Any]) -> dict[HookStage, tuple[str, ...]]:
    """`pipeline_order` → {hook: cơ chế theo thứ tự}. Tên stage là từ đầu của trường `stage`."""
    known = set(raw["defenses"])
    out: dict[HookStage, tuple[str, ...]] = {}
    for row in raw["pipeline_order"]:
        name = row["stage"].split()[0]
        try:
            stage = HookStage(name)
        except ValueError:
            raise ValueError(f"pipeline_order: stage '{name}' không phải HookStage") from None
        if stage in out:
            raise ValueError(f"pipeline_order: stage '{name}' khai hai lần")
        unknown = [k for k in row["apply"] if k not in known]
        if unknown:
            raise ValueError(f"pipeline_order.{name}: cơ chế lạ {unknown}")
        out[stage] = tuple(row["apply"])
    return out


def _apply_override(blocks: dict[str, Any], dotted: str, value: Any) -> None:
    """Gán `value` vào `blocks` theo đường chấm; đường không tồn tại là lỗi cấu hình."""
    *parents, leaf = dotted.split(".")
    node: Any = blocks
    for key in parents:
        if not isinstance(node, dict) or key not in node:
            raise ValueError(f"preset_overrides: không có khóa '{dotted}' trong defenses")
        node = node[key]
    if not isinstance(node, dict) or leaf not in node:
        raise ValueError(f"preset_overrides: không có khóa '{dotted}' trong defenses")
    node[leaf] = value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DefensePipeline:
    """`DefenseLayer` đọc `defenses.yaml`. Một instance dùng cho mọi run của một lô."""

    def __init__(
        self,
        *,
        preset: str | None = None,
        enabled: Iterable[str] | None = None,
        path: Path | str = DEFAULT_CONFIG_PATH,
        customers_db: Path | str = DEFAULT_CUSTOMERS_DB,
        raw: dict[str, Any] | None = None,
    ) -> None:
        if preset is not None and enabled is not None:
            raise ValueError("chọn một trong preset hoặc enabled, không cả hai")
        raw = raw if raw is not None else load_defenses_raw(path)
        blocks = copy.deepcopy(raw["defenses"])
        overrides: dict[str, Any] = {}

        if preset is not None:
            if preset not in runnable_presets(raw):
                raise ValueError(
                    f"preset '{preset}' không chạy được; hợp lệ: {runnable_presets(raw)}"
                )
            chosen = list(raw["presets"][preset])
            overrides = dict((raw.get("preset_overrides") or {}).get(preset) or {})
        elif enabled is not None:
            chosen = list(enabled)
        else:
            chosen = [k for k, b in blocks.items() if b.get("enabled", False)]

        unknown = [k for k in chosen if k not in blocks]
        if unknown:
            raise ValueError(f"cơ chế lạ {unknown}; hợp lệ: {list(blocks)}")
        for dotted, value in overrides.items():
            head = dotted.split(".", 1)[0]
            if head not in chosen:
                raise ValueError(f"preset_overrides.{preset}: '{head}' không bật trong preset")
            _apply_override(blocks, dotted, value)

        stages = _stage_map(raw)
        placed = {k for keys in stages.values() for k in keys}
        orphan = [k for k in chosen if k not in placed]
        if orphan:
            raise ValueError(f"{orphan} bật nhưng không nằm ở stage nào của pipeline_order")

        # Thứ tự khai trong `defenses` — ảnh chụp không phụ thuộc thứ tự người gọi liệt kê.
        self.enabled: tuple[str, ...] = tuple(k for k in blocks if k in chosen)
        self.preset = preset if preset is not None else "custom"
        self.overrides = overrides
        self.blocks = {k: blocks[k] for k in self.enabled}
        for key in self.enabled:
            if key in _VALIDATORS:
                _VALIDATORS[key](self.blocks[key])
            self.blocks[key]["enabled"] = True
        self._stages = {
            stage: tuple(k for k in keys if k in self.enabled) for stage, keys in stages.items()
        }
        self._fns = {key: self._entrypoint(self.blocks[key]) for key in self.enabled}
        # Allowlist D4 dựng một lần cho cả lô (defense_spec §6.1), không mỗi tool-call.
        self._allowlist: EgressAllowlist | None = (
            build_egress_allowlist(self.blocks[D4], customers_db) if D4 in self.enabled else None
        )
        self._snapshot = self._build_snapshot()

    # ----------------------------------------------------------- dựng

    @staticmethod
    def _entrypoint(block: dict[str, Any]) -> Callable[..., Any]:
        module = importlib.import_module(block["module"])
        fn = getattr(module, block["entrypoint"], None)
        if not callable(fn):
            raise ValueError(f"{block['module']} không có hàm '{block['entrypoint']}'")
        return fn

    def _build_snapshot(self) -> dict[str, Any]:
        if not self.enabled:
            # Trùng `NoDefense.config_snapshot()` khi là preset off — danh tính resume giữ nguyên.
            return {"preset": self.preset, "enabled": []}
        files: dict[str, str] = {}
        if D2 in self.enabled:
            rel = self.blocks[D2]["params"]["imperative_patterns_file"]
            full = Path(rel) if Path(rel).is_absolute() else REPO_ROOT / rel
            files[rel] = _sha256(full)
        snap: dict[str, Any] = {
            "preset": self.preset,
            "enabled": list(self.enabled),
            "overrides": self.overrides,
            "defenses": self.blocks,
        }
        if files:
            snap["files_sha256"] = files
        return snap

    # ------------------------------------------------------ DefenseLayer

    def transform(
        self,
        stage: HookStage,
        text: str,
        *,
        source: str,
        session: SessionState,
    ) -> Transformed:
        check_stage(stage, "transform", source)
        hits: list[DefenseHit] = []
        for key in self._stages.get(stage, ()):
            t = self._call_transform(key, text, source, session)
            hits.extend(t.hits)
            text = t.text
        return Transformed(text=text, hits=tuple(hits))

    def gate(self, stage: HookStage, call: Any, *, session: SessionState) -> Decision:
        check_stage(stage, "gate")
        hits: list[DefenseHit] = []
        for key in self._stages.get(stage, ()):
            d = self._call_gate(key, call, session)
            hits.extend(d.hits)
            if not d.allowed:
                return Decision(action="block", reason=d.reason, hits=tuple(hits))
        return Decision(action="allow", hits=tuple(hits))

    def config_snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self._snapshot)

    def end_run(self, run_id: str) -> None:
        """Dọn trạng thái theo run (delimiter D1). Runner gọi sau mỗi run."""
        if D1 in self.enabled:
            d1_spotlighting.clear_run(run_id)

    # ------------------------------------------------- chữ ký từng cơ chế

    def _call_transform(
        self, key: str, text: str, source: str, session: SessionState
    ) -> Transformed:
        fn, cfg = self._fns[key], self.blocks[key]
        if key == D1:
            return fn(text, source=source, run_id=session.run_id, enabled=True, config=cfg)
        if key == D2:
            return fn(text, source=source, enabled=True, config=cfg)
        raise ValueError(f"'{key}' không phải cơ chế transform")

    def _call_gate(self, key: str, call: Any, session: SessionState) -> Decision:
        fn, cfg = self._fns[key], self.blocks[key]
        if key == D3:
            return fn(
                call, session=session, task_type=session.task_type, enabled=True, config=cfg
            )
        if key == D4:
            return fn(
                call,
                run_canaries=tuple(session.run_canaries),
                egress_allowlist=self._allowlist,
                enabled=True,
                config=cfg,
            )
        raise ValueError(f"'{key}' không phải cơ chế gate")

