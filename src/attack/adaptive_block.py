"""Kế hoạch khối tấn công thích ứng B5 (RQ5) trên ô S_adp — bộ chạy ở `scripts/run_adaptive.py`.

Một chuỗi = (target, ô, preset, đơn vị lấy mẫu). Đơn vị lấy mẫu của ô bốc bằng `cell_units` với
cùng seed như B1/B2: `chains_per_cell` chuỗi của một ô dùng các cặp (payload, tác vụ chở) khác nhau
trước, lặp sau — nên chuỗi thích ứng xuất phát từ đúng payload mà nhánh blind đã đo.

`chain_id` tất định theo danh tính chuỗi: chạy tiếp lô bị ngắt thì chuỗi đã xong (có trong
`chains.jsonl`) được bỏ qua, chuỗi dở dang bị xóa vòng đã ghi rồi chạy lại từ vòng một — một chuỗi
không bao giờ trộn hai phiên.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from attack.payloads.schema import DEFAULT_TASKS_PATH
from attack.runner import AttackRunnerError, _cell_pairs, cell_units, select_payloads
from eval.experiment import Experiment

__all__ = ["ChainPlan", "plan_adaptive"]

_NS = uuid.UUID("6f1d3c2a-5b8e-4f7a-9c0d-b5b5b5b5b5b5")


@dataclass(frozen=True, order=True)
class ChainPlan:
    target_id: str
    channel: str
    technique: str
    goal: str
    preset: str
    payload_id: str
    carrier_task_id: str
    repeat_idx: int

    @property
    def chain_id(self) -> str:
        key = "|".join(str(v) for v in (self.target_id, self.channel, self.technique, self.goal,
                                        self.preset, self.payload_id, self.carrier_task_id,
                                        self.repeat_idx))
        return uuid.uuid5(_NS, key).hex


def plan_adaptive(
    exp: Experiment,
    block_id: str,
    *,
    corpus: Sequence[dict[str, Any]],
    carriers: Sequence[dict[str, Any]],
    seed: int,
    presets: Sequence[str] | None = None,
    chains_per_cell: int | None = None,
    tasks_path: Path | str = DEFAULT_TASKS_PATH,
) -> list[ChainPlan]:
    """Mọi chuỗi của khối thích ứng, thứ tự chạy (xáo trộn có seed). Lọc chỉ cho chạy thử."""
    block = exp.unit(block_id)
    if block.attacker_mode != "adaptive":
        raise AttackRunnerError(f"khối {block_id} không phải khối tấn công thích ứng")
    selected = (block.cells or {}).get("selected")
    if not selected:
        raise AttackRunnerError(f"khối {block_id}: cells.selected (S_adp) chưa điền")
    n = chains_per_cell if chains_per_cell is not None else block.chains_per_cell
    if not n:
        raise AttackRunnerError(f"khối {block_id} thiếu chains_per_cell")
    presets = list(presets or block.presets)

    plans: list[ChainPlan] = []
    for channel, technique, goal in selected:
        payloads = select_payloads(corpus, channel, technique, goal, selection=exp.corpus_selection)
        pairs = _cell_pairs(payloads, channel, carriers, tasks_path=tasks_path)
        if not pairs:
            raise AttackRunnerError(f"ô {channel}·{technique}·{goal} không có payload/tác vụ chở")
        units = cell_units(pairs, n, seed=f"{seed}:{channel}:{technique}:{goal}")
        for target in block.targets:
            for preset in presets:
                for pid, cid, rep in units:
                    plans.append(
                        ChainPlan(target, channel, technique, goal, preset, pid, cid, rep)
                    )
    random.Random(f"{seed}:{block_id}").shuffle(plans)
    return plans
