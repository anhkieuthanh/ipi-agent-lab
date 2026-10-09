"""Bộ đếm chi phí API theo lô — phần code của STT-15, giai đoạn 0 của lộ trình code.

Quy tắc vận hành (CLAUDE.md mục 4): kiểm chi phí mỗi 2 giờ trong 4 giờ đầu mọi lần chạy lô,
vượt 120% dự toán thì dừng ngay; hạn mức lấy từ `.env`.

- Đơn giá đọc từ `pricing_usd_per_mtok` của từng target trong `config/models.yaml`. Còn `null`
  thì `load_prices` từ chối — không chạy lô nào khi bảng giá còn TODO.
- Chi phí đã tiêu cộng từ `logs/llm_client.jsonl` (mỗi lời gọi thành công một dòng), lọc theo
  `run_id` của lô hoặc mốc thời gian bắt đầu lô.
- `BudgetGuard.status()` trả `ok` / `alert` / `stop`:
    * `stop` khi tiêu > `stop_ratio` × dự toán lô (mặc định 1,2) hoặc chạm hạn mức tổng;
    * `alert` khi tiêu ≥ `alert_pct`% dự toán lô.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

__all__ = [
    "CostConfigError",
    "Price",
    "load_prices",
    "spend_from_log",
    "BudgetGuard",
    "budget_from_env",
]


class CostConfigError(RuntimeError):
    """Thiếu đơn giá hoặc hạn mức — không được mở lô."""


@dataclass(frozen=True)
class Price:
    input_per_mtok: float
    output_per_mtok: float

    def cost(self, tokens_in: int | None, tokens_out: int | None) -> float:
        return (
            (tokens_in or 0) * self.input_per_mtok + (tokens_out or 0) * self.output_per_mtok
        ) / 1e6


def load_prices(
    config_path: str | Path = "config/models.yaml", targets: Iterable[str] | None = None
) -> dict[str, Price]:
    """Đọc đơn giá; `targets` = các target lô sẽ dùng (mặc định: tất cả)."""
    with Path(config_path).open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    all_targets = cfg.get("targets") or {}
    wanted = list(targets) if targets is not None else list(all_targets)

    prices: dict[str, Price] = {}
    missing: list[str] = []
    for t in wanted:
        if t not in all_targets:
            raise CostConfigError(f"target '{t}' không có trong {config_path}")
        p = all_targets[t].get("pricing_usd_per_mtok") or {}
        if p.get("input") is None or p.get("output") is None:
            missing.append(t)
            continue
        prices[t] = Price(float(p["input"]), float(p["output"]))
    if missing:
        raise CostConfigError(
            f"Chưa có đơn giá cho {missing} (pricing_usd_per_mtok trong {config_path}, STT-15). "
            "Không chạy lô nào khi bảng giá còn TODO."
        )
    return prices


def _iter_log(log_path: str | Path) -> Iterable[dict[str, Any]]:
    path = Path(log_path)
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def spend_from_log(
    log_path: str | Path,
    prices: dict[str, Price],
    *,
    run_ids: Iterable[str] | None = None,
    since_ts: str | None = None,
) -> dict[str, float]:
    """Tổng USD theo target từ log JSONL của `LLMClient`.

    `since_ts` so chuỗi ISO-8601 UTC cùng định dạng trường `ts` của log.
    """
    run_filter = set(run_ids) if run_ids is not None else None
    totals: dict[str, float] = {}
    for rec in _iter_log(log_path):
        if not rec.get("ok"):
            continue
        if run_filter is not None and rec.get("run_id") not in run_filter:
            continue
        if since_ts is not None and rec.get("ts", "") < since_ts:
            continue
        target = rec.get("target_id")
        if target not in prices:
            continue
        totals[target] = totals.get(target, 0.0) + prices[target].cost(
            rec.get("tokens_in"), rec.get("tokens_out")
        )
    return totals


@dataclass
class BudgetGuard:
    batch_estimate_usd: float
    total_budget_usd: float | None = None
    alert_pct: float = 80.0
    stop_ratio: float = 1.2
    spent_before_batch_usd: float = 0.0
    history: list[tuple[float, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.batch_estimate_usd <= 0:
            raise CostConfigError("Dự toán lô phải > 0 — chưa có dự toán thì không mở lô.")

    def status(self, spent_batch_usd: float) -> str:
        if spent_batch_usd > self.stop_ratio * self.batch_estimate_usd:
            result = "stop"
        elif (
            self.total_budget_usd is not None
            and self.spent_before_batch_usd + spent_batch_usd >= self.total_budget_usd
        ):
            result = "stop"
        elif spent_batch_usd >= self.alert_pct / 100 * self.batch_estimate_usd:
            result = "alert"
        else:
            result = "ok"
        self.history.append((spent_batch_usd, result))
        return result


def budget_from_env(batch_estimate_usd: float, spent_before_batch_usd: float = 0.0) -> BudgetGuard:
    """Dựng `BudgetGuard` từ `COST_BUDGET_USD_TOTAL` và `COST_BUDGET_USD_ALERT_PCT`."""
    total = os.getenv("COST_BUDGET_USD_TOTAL", "").strip()
    if not total:
        raise CostConfigError("COST_BUDGET_USD_TOTAL chưa được set trong .env (STT-15).")
    alert = os.getenv("COST_BUDGET_USD_ALERT_PCT", "80").strip() or "80"
    return BudgetGuard(
        batch_estimate_usd=batch_estimate_usd,
        total_budget_usd=float(total),
        alert_pct=float(alert),
        spent_before_batch_usd=spent_before_batch_usd,
    )
