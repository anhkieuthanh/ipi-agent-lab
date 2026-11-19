"""Chọn tập ô của khối chọn ô theo quy tắc — S_def cho B2 từ B1, S_adp cho B5 từ B2.

Quy tắc ghi trước ở `config/experiment.yaml` (`blocks.<id>.cells`); module này chỉ áp đúng quy tắc
đó lên trace của lô nguồn, không có tham số nào khác. Kết quả điền vào `cells.selected` một lần,
kèm lô nguồn, trước khi chạy khối.

S_def: ô (kênh × kỹ thuật × mục tiêu) có cận dưới Wilson 95% của ASR_e2e(off) ≥ `min_ci_low` ở ít
nhất một target của khối đích; xếp theo ASR_e2e gộp các target đó (`rank_by: pooled`), lấy tối đa
`max_cells` ô. Ít ô đạt ngưỡng hơn `max_cells` thì lấy `max_cells` ô ASR gộp cao nhất (ASR sàn).
Hòa ở ranh giới cắt thì báo lỗi: quy tắc không có cách phân định, phải quyết trước khi chạy.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from eval.metrics import wilson

__all__ = ["Cell", "CellSelectError", "CellStat", "select_s_def"]

Cell = tuple[str, str, str]  # (channel, technique, goal)


class CellSelectError(ValueError):
    """Không áp được quy tắc chọn ô (lô nguồn thiếu, hòa ở ranh giới)."""


@dataclass(frozen=True)
class CellStat:
    cell: Cell
    by_target: dict[str, tuple[int, int]]  # target → (thành công, run hợp lệ)

    @property
    def pooled(self) -> float:
        s = sum(x for x, _ in self.by_target.values())
        n = sum(n for _, n in self.by_target.values())
        return s / n if n else 0.0

    def passes(self, min_ci_low: float) -> bool:
        return any(n and wilson(s, n)[0] >= min_ci_low for s, n in self.by_target.values())


def cell_stats(store: Path, targets: Sequence[str]) -> list[CellStat]:
    """ASR_e2e(off) theo ô × target của một lô, đã loại `parse_error` (cùng định nghĩa `ASR_SQL`)."""
    if not store.is_file():
        raise CellSelectError(f"không có store {store}")
    marks = ",".join("?" * len(targets))
    with sqlite3.connect(store) as con:
        rows = con.execute(
            f"""SELECT channel, technique, goal, target_id,
                       SUM(CASE WHEN parse_error = 0 AND outcome = 'success' THEN 1 ELSE 0 END),
                       SUM(1 - parse_error)
                FROM runs
                WHERE run_kind = 'attack' AND target_id IN ({marks})
                GROUP BY channel, technique, goal, target_id""",
            list(targets),
        ).fetchall()
    cells: dict[Cell, dict[str, tuple[int, int]]] = {}
    for ch, t, g, tg, s, n in rows:
        cells.setdefault((ch, t, g), {})[tg] = (int(s), int(n))
    return [CellStat(c, d) for c, d in sorted(cells.items())]


def select_s_def(
    stats: Sequence[CellStat], *, min_ci_low: float, max_cells: int
) -> tuple[list[CellStat], bool]:
    """(ô chọn theo thứ tự ASR gộp giảm dần, có phải ASR sàn không)."""
    passing = [c for c in stats if c.passes(min_ci_low)]
    floor = len(passing) < max_cells
    pool = list(stats) if floor else passing
    ranked = sorted(pool, key=lambda c: (-c.pooled, c.cell))
    chosen = ranked[:max_cells]
    if len(ranked) > max_cells and ranked[max_cells].pooled == chosen[-1].pooled:
        tied = [c.cell for c in ranked if c.pooled == chosen[-1].pooled]
        raise CellSelectError(
            f"hòa ASR gộp {chosen[-1].pooled:.3f} ở ranh giới {max_cells} ô: {tied}"
        )
    return chosen, floor
