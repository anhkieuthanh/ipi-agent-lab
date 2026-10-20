"""Đọc và kiểm `config/experiment.yaml` — STT-24, giai đoạn 1 của lộ trình code.

Runner ma trận (STT-46) chỉ đọc giao thức thực nghiệm qua module này:

    exp = load_experiment()
    assert not validate(exp)
    if unresolved(exp, "B1"):          # còn trường null ⇒ không mở khối
        raise SystemExit(...)
    block = exp.blocks["B1"]
    n = exp.planned_runs("B1")

Ba lớp bảo vệ, mỗi lớp chặn một kiểu lỗi đã gặp ở hai giai đoạn đầu (`Y_TUONG_DU_AN.md` mục 17):

- `load_experiment` từ chối khóa lạ — tham số khai ra mà không code nào đọc là lỗ hổng, không
  phải lỗi nhỏ.
- `validate` đối chiếu mọi tên (target, preset, kỹ thuật, kênh, biến) với nguồn của nó
  (`models.yaml`, `defenses.yaml`, `obs.trace`) — một khái niệm, một nguồn.
- `unresolved` liệt kê trường còn `null` — không chạy lô nào khi còn TODO.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from math import prod
from pathlib import Path
from typing import Any

import yaml

from obs.trace import ATTACKER_MODES, CHANNELS, GOALS, HARNESSES, RUN_KINDS, TECHNIQUES, Run

__all__ = [
    "Block",
    "Experiment",
    "ExperimentConfigError",
    "load_experiment",
    "validate",
    "unresolved",
]

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = REPO_ROOT / "config" / "experiment.yaml"

RQS = tuple(f"RQ{i}" for i in range(1, 7))

_TOP_KEYS = frozenset(
    {
        "schema_version",
        "contracts",
        "variables",
        "fixed",
        "pilot",
        "calibration",
        "run_order",
        "stopping",
        "refusal",
        "metrics",
        "cut_order",
        "never_cut",
        "reduced_presets",
        "benign_task_types",
        "blocks",
    }
)


class ExperimentConfigError(ValueError):
    """experiment.yaml sai cấu trúc — không mở được lô nào."""


@dataclass(frozen=True)
class Block:
    """Một khối thực nghiệm B1–B6 (checklist mục 5). Trường không dùng để trống."""

    id: str
    purpose: tuple[str, ...]
    run_kind: str | None = None
    attacker_mode: str | None = None
    targets: tuple[str | None, ...] = ()
    presets: tuple[str, ...] = ()
    goals: tuple[str, ...] = ()
    techniques_by_channel: dict[str, tuple[str, ...]] = field(default_factory=dict)
    n_per_cell: int | None = None
    cells: dict[str, Any] | None = None
    queries: str | None = None
    repeats: int | None = None
    subset: Any = None
    chains_per_cell: int | None = None
    max_rounds: int | None = None
    attacker_model: str | None = None
    harnesses: tuple[str, ...] = ()
    conditional_harness_targets: dict[str, tuple[str, ...]] = field(default_factory=dict)
    samples: int | None = None
    # RQ3: cách chọn "cơ chế đơn lẻ tốt nhất" (giao thức mục 8, N3).
    best_single: dict[str, Any] | None = None
    # Thêm một preset = cơ chế đơn lẻ tốt nhất mà khối nêu tên đã chọn (B4 phần RQ3).
    add_best_single_from: str | None = None
    # Khối gồm nhiều phần khác kiểu run (B4). Mỗi phần là một Block; số run là tổng các phần.
    parts: dict[str, Block] = field(default_factory=dict)


_BLOCK_KEYS = frozenset(Block.__dataclass_fields__) - {"id"}
_PART_KEYS = _BLOCK_KEYS - {"parts", "purpose"}
BEST_SINGLE_SELECT_ON = ("full_block",)
BEST_SINGLE_PER = ("goal",)
_TUPLE_FIELDS = ("purpose", "targets", "presets", "goals", "harnesses")


@dataclass(frozen=True)
class Experiment:
    path: Path
    raw: dict[str, Any]
    blocks: dict[str, Block]

    @property
    def fixed(self) -> dict[str, Any]:
        return self.raw["fixed"]

    def contract_path(self, name: str) -> Path:
        return REPO_ROOT / self.raw["contracts"][name]

    def planned_runs(self, block_id: str) -> int | None:
        """Số run theo công thức của khối; `None` khi còn thừa số chưa chốt.

        Khối chọn ô theo quy tắc (B2, B5) cho cận trên — `cells.max_cells` ô. B6 tính cả nhánh có
        điều kiện, cũng là cận trên.
        """
        return self._planned(self.blocks[block_id])

    def _planned(self, b: Block) -> int | None:
        if b.parts:
            counts = [self._planned(part) for part in b.parts.values()]
            return None if any(c is None for c in counts) else sum(counts)
        n_targets = len(b.targets)
        n_presets = len(b.presets) + (1 if b.add_best_single_from else 0)
        max_cells = (b.cells or {}).get("max_cells")

        if b.harnesses:
            factors = [b.samples, n_targets, len(b.harnesses)]
        elif b.attacker_mode == "adaptive":
            factors = [max_cells, n_presets, b.chains_per_cell, b.max_rounds, n_targets]
        elif b.cells is not None:
            factors = [max_cells, n_presets, n_targets, b.n_per_cell]
        elif b.techniques_by_channel:
            n_tech = sum(len(t) for t in b.techniques_by_channel.values())
            factors = [n_tech, len(b.goals), n_targets, n_presets, b.n_per_cell]
        elif b.run_kind == "benign" and b.queries == "all":
            factors = [self._n_benign_queries(), b.repeats, n_presets, n_targets]
        else:
            return None
        if any(f is None for f in factors):
            return None
        return prod(factors)

    def _n_benign_queries(self) -> int:
        data = json.loads(self.contract_path("benign_queries").read_text(encoding="utf-8"))
        return len(data["queries"])


def _as_block(block_id: str, raw: dict[str, Any], *, part: bool = False) -> Block:
    unknown = sorted(set(raw) - (_PART_KEYS if part else _BLOCK_KEYS))
    if unknown:
        raise ExperimentConfigError(f"blocks.{block_id}: khóa lạ {unknown}")
    if ("run_kind" not in raw and "parts" not in raw) or (not part and "purpose" not in raw):
        raise ExperimentConfigError(f"blocks.{block_id}: thiếu purpose hoặc run_kind")
    data = dict(raw)
    if part:
        data["purpose"] = ()  # phần kế thừa purpose của khối cha
    if "parts" in data:
        data["parts"] = {
            name: _as_block(f"{block_id}.parts.{name}", p or {}, part=True)
            for name, p in (data["parts"] or {}).items()
        }
    for name in _TUPLE_FIELDS:
        if name in data:
            data[name] = tuple(data[name] or ())
    if "techniques_by_channel" in data:
        data["techniques_by_channel"] = {
            ch: tuple(ts) for ch, ts in (data["techniques_by_channel"] or {}).items()
        }
    if "conditional_harness_targets" in data:
        data["conditional_harness_targets"] = {
            h: tuple(ts) for h, ts in (data["conditional_harness_targets"] or {}).items()
        }
    return Block(id=block_id, **data)


def load_experiment(path: str | Path = DEFAULT_PATH) -> Experiment:
    """Nạp file, từ chối khóa lạ ở cấp gốc và cấp khối."""
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    unknown = sorted(set(raw) - _TOP_KEYS)
    if unknown:
        raise ExperimentConfigError(f"{path.name}: khóa lạ ở cấp gốc {unknown}")
    missing = sorted({"contracts", "fixed", "blocks"} - set(raw))
    if missing:
        raise ExperimentConfigError(f"{path.name}: thiếu {missing}")
    blocks = {bid: _as_block(bid, b or {}) for bid, b in raw["blocks"].items()}
    return Experiment(path=path, raw=raw, blocks=blocks)


def _yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _outside(values: Any, allowed: Any) -> list[Any]:
    return [v for v in values if v not in allowed]


def validate(exp: Experiment) -> list[str]:
    """Danh sách lỗi đối chiếu; rỗng là hợp lệ. Giá trị `null` không phải lỗi — xem `unresolved`."""
    problems: list[str] = []
    raw = exp.raw

    for name, rel in raw["contracts"].items():
        if not (REPO_ROOT / rel).exists():
            problems.append(f"contracts.{name}: không có file {rel}")
    if problems:
        return problems

    targets = set(_yaml(exp.contract_path("models"))["targets"])
    defenses_cfg = _yaml(exp.contract_path("defenses"))
    presets_cfg = defenses_cfg["presets"]
    # Preset chạy được là preset dạng danh sách cơ chế; `reduced_3` là nhóm preset, không phải một.
    runnable = {name for name, value in presets_cfg.items() if isinstance(value, list)}
    columns = set(Run.model_fields)

    for group, names in (raw.get("variables") or {}).items():
        bad = _outside(names, columns)
        if bad:
            problems.append(f"variables.{group}: {bad} không phải cột của bảng runs")

    fixed = raw["fixed"]
    for key in ("max_steps", "kb_top_k", "max_tokens"):
        value = fixed.get(key)
        if value is not None and (not isinstance(value, int) or value <= 0):
            problems.append(f"fixed.{key} phải là số nguyên dương")
    if fixed.get("reference_date") is not None:
        try:
            date.fromisoformat(str(fixed["reference_date"]))
        except ValueError:
            problems.append("fixed.reference_date không đúng dạng YYYY-MM-DD")

    pilot = raw.get("pilot") or {}
    gate = pilot.get("asr_gate")
    if gate is not None and not (len(gate) == 2 and 0 <= gate[0] < gate[1] <= 1):
        problems.append(f"pilot.asr_gate phải là [thấp, cao] trong [0, 1], nhận {gate}")
    for key in ("targets", "observe_targets"):
        for t in _outside(pilot.get(key) or [], targets):
            problems.append(f"pilot.{key}: '{t}' không có trong models.yaml")
    overlap = set(pilot.get("targets") or []) & set(pilot.get("observe_targets") or [])
    if overlap:
        problems.append(f"pilot: {sorted(overlap)} vừa tính cổng vừa chỉ đo")
    p_same = (pilot.get("variance_probe") or {}).get("p_same_threshold")
    if p_same is not None and not (isinstance(p_same, (int, float)) and 0 < p_same <= 1):
        problems.append("pilot.variance_probe.p_same_threshold phải trong (0, 1]")

    refusal = raw.get("refusal") or {}
    for key in ("finish_reasons", "phrases"):
        values = refusal.get(key)
        if values is not None and (
            not isinstance(values, list)
            or not values
            or not all(isinstance(v, str) and v.strip() for v in values)
        ):
            problems.append(f"refusal.{key} phải là danh sách khác rỗng gồm chuỗi khác rỗng")

    tcp_ci = (raw.get("metrics") or {}).get("tcp_ci") or {}
    if tcp_ci.get("method") not in (None, "bootstrap_percentile"):
        problems.append(
            f"metrics.tcp_ci.method: '{tcp_ci['method']}' ngoài ('bootstrap_percentile',)"
        )
    for key in ("resamples", "seed"):
        value = tcp_ci.get(key)
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value < 1
        ):
            problems.append(f"metrics.tcp_ci.{key} phải là số nguyên dương")
    level = tcp_ci.get("level")
    if level is not None and not (isinstance(level, float) and 0 < level < 1):
        problems.append(f"metrics.tcp_ci.level phải trong (0, 1), nhận {level}")

    reduced = raw.get("reduced_presets")
    if reduced is not None and not isinstance(presets_cfg.get(reduced), dict):
        problems.append(f"reduced_presets: '{reduced}' không phải nhóm preset trong defenses.yaml")

    problems += _check_preset_overrides(defenses_cfg, runnable)

    seen: list[str] = []
    for bid, b in exp.blocks.items():
        where = f"blocks.{bid}"
        problems += [f"{where}.purpose: '{x}' không phải RQ1–RQ6" for x in _outside(b.purpose, RQS)]
        if b.parts and (b.run_kind is not None or b.targets):
            problems.append(f"{where}: khối có parts thì run_kind và targets khai ở từng phần")
        raw_block = raw["blocks"][bid]
        units = [(where, b, raw_block)] + [
            (f"{where}.parts.{name}", part, raw_block["parts"][name])
            for name, part in b.parts.items()
        ]
        for unit_where, unit, unit_raw in units:
            problems += _check_unit(unit_where, unit, unit_raw, exp.blocks, seen, targets, runnable)
        seen.append(bid)
    return problems


def _check_unit(
    where: str,
    b: Block,
    raw_block: dict[str, Any],
    blocks: dict[str, Block],
    seen: list[str],
    targets: set[str],
    runnable: set[str],
) -> list[str]:
    """Kiểm một khối hoặc một phần của khối."""
    problems: list[str] = []
    if b.run_kind is not None and b.run_kind not in RUN_KINDS:
        problems.append(f"{where}.run_kind: '{b.run_kind}' ngoài {RUN_KINDS}")
    if b.attacker_mode is not None and b.attacker_mode not in ATTACKER_MODES:
        problems.append(f"{where}.attacker_mode: '{b.attacker_mode}' ngoài {ATTACKER_MODES}")
    if b.run_kind == "attack" and "attacker_mode" not in raw_block:
        # CHECK ck_attack_labels của trace bắt buộc attacker_mode ở mọi run tấn công.
        problems.append(f"{where}: khối tấn công phải khai attacker_mode")
    for t in _outside([t for t in b.targets if t is not None], targets):
        problems.append(f"{where}.targets: '{t}' không có trong models.yaml")
    for p in _outside(b.presets, runnable):
        problems.append(f"{where}.presets: '{p}' không phải preset chạy được của defenses.yaml")
    problems += [f"{where}.goals: '{g}' ngoài {GOALS}" for g in _outside(b.goals, GOALS)]
    for ch, techs in b.techniques_by_channel.items():
        if ch not in CHANNELS:
            problems.append(f"{where}.techniques_by_channel: kênh '{ch}' ngoài {CHANNELS}")
        for t in _outside(techs, TECHNIQUES):
            problems.append(f"{where}.techniques_by_channel.{ch}: '{t}' ngoài T1–T8")
    for h in _outside(b.harnesses, HARNESSES):
        problems.append(f"{where}.harnesses: '{h}' ngoài {HARNESSES}")
    for h, ts in b.conditional_harness_targets.items():
        if h not in b.harnesses:
            problems.append(f"{where}.conditional_harness_targets: '{h}' không có trong harnesses")
        for t in _outside(ts, b.targets):
            problems.append(f"{where}.conditional_harness_targets.{h}: '{t}' ngoài targets")
    if b.cells is not None and b.cells.get("from_block") not in seen:
        problems.append(f"{where}.cells.from_block phải là một khối khai trước")
    if b.best_single is not None:
        if b.best_single.get("select_on") not in BEST_SINGLE_SELECT_ON:
            problems.append(f"{where}.best_single.select_on ngoài {BEST_SINGLE_SELECT_ON}")
        if b.best_single.get("per") not in BEST_SINGLE_PER:
            problems.append(f"{where}.best_single.per ngoài {BEST_SINGLE_PER}")
        # So "all" với cơ chế đơn lẻ tốt nhất cần cả hai có mặt trong khối.
        singles = [p for p in b.presets if p.endswith("_only")]
        if "all" not in b.presets or not singles:
            problems.append(f"{where}.best_single cần preset 'all' và ít nhất một '*_only'")
    src = b.add_best_single_from
    if src is not None and (src not in seen or blocks[src].best_single is None):
        problems.append(
            f"{where}.add_best_single_from: '{src}' phải là khối khai trước có best_single"
        )
    return problems


def _null_paths(node: Any, prefix: str) -> list[str]:
    if node is None:
        return [prefix]
    if isinstance(node, dict):
        return [p for k, v in node.items() for p in _null_paths(v, f"{prefix}.{k}")]
    if isinstance(node, list):
        return [p for i, v in enumerate(node) for p in _null_paths(v, f"{prefix}[{i}]")]
    return []


def unresolved(exp: Experiment, block_id: str | None = None) -> list[str]:
    """Đường dẫn các trường còn `null`.

    Không truyền `block_id`: mọi trường null của file. Truyền `block_id`: chỉ những trường chặn
    khối đó — null của chính khối, `run_order.seed`, `refusal` (scorer cần ở mọi khối), và
    `benign_task_types` nếu khối lành tính.
    Runner từ chối mở khối khi danh sách này khác rỗng.
    """
    raw = exp.raw
    if block_id is None:
        return [p for key, value in raw.items() for p in _null_paths(value, key)]
    if block_id not in exp.blocks:
        raise KeyError(block_id)
    paths = _null_paths(raw["blocks"][block_id], f"blocks.{block_id}")
    paths += _null_paths((raw.get("run_order") or {}).get("seed"), "run_order.seed")
    paths += _null_paths(raw.get("refusal"), "refusal")
    if exp.blocks[block_id].run_kind == "benign":
        paths += _null_paths(raw.get("benign_task_types"), "benign_task_types")
    return paths


def _check_preset_overrides(defenses_cfg: dict[str, Any], runnable: set[str]) -> list[str]:
    """Mỗi ghi đè trỏ tới preset chạy được, cơ chế bật trong preset đó, và khóa có thật.

    Ghi đè trỏ sai khóa sẽ bị pipeline bỏ qua trong im lặng — đúng lớp lỗi "khai mà không ai đọc".
    """
    problems: list[str] = []
    for name, overrides in (defenses_cfg.get("preset_overrides") or {}).items():
        where = f"defenses.preset_overrides.{name}"
        if name not in runnable:
            problems.append(f"{where}: không phải preset chạy được")
            continue
        for dotted in overrides or {}:
            head, *rest = dotted.split(".")
            if head not in defenses_cfg["presets"][name]:
                problems.append(f"{where}: '{head}' không bật trong preset này")
                continue
            node: Any = defenses_cfg["defenses"].get(head)
            for key in rest:
                node = node.get(key) if isinstance(node, dict) else None
            if node is None or not rest:
                problems.append(f"{where}: không có khóa '{dotted}' trong defenses")
    return problems
