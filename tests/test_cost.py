"""Unit test cho src/obs/cost.py — phần code của STT-15."""

import json
from pathlib import Path

import pytest
import yaml

from obs.cost import (
    BudgetGuard,
    CostConfigError,
    Price,
    budget_from_env,
    load_prices,
    spend_from_log,
)

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "models.yaml"


def _config_with_prices(tmp_path, prices):
    cfg = yaml.safe_load(CONFIG_PATH.read_text("utf-8"))
    for target, (pin, pout) in prices.items():
        cfg["targets"][target]["pricing_usd_per_mtok"] = {"input": pin, "output": pout}
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), "utf-8")
    return path


def test_real_config_refuses_while_prices_are_null():
    cfg = yaml.safe_load(CONFIG_PATH.read_text("utf-8"))
    if all(t["pricing_usd_per_mtok"]["input"] is not None for t in cfg["targets"].values()):
        pytest.skip("Đơn giá đã điền (STT-15 xong)")
    with pytest.raises(CostConfigError, match="STT-15"):
        load_prices(CONFIG_PATH)


def test_load_prices_only_for_requested_targets(tmp_path):
    path = _config_with_prices(tmp_path, {"A2": (0.5, 2.0)})
    assert load_prices(path, targets=["A2"]) == {"A2": Price(0.5, 2.0)}
    with pytest.raises(CostConfigError, match="A1"):
        load_prices(path, targets=["A1", "A2"])


def test_price_cost():
    assert Price(1.0, 4.0).cost(1_000_000, 500_000) == pytest.approx(3.0)
    assert Price(1.0, 4.0).cost(None, None) == 0.0


def test_spend_from_log_filters(tmp_path):
    log = tmp_path / "llm.jsonl"
    rows = [
        {
            "ts": "2026-10-09T01:00:00Z",
            "run_id": "r1",
            "target_id": "A2",
            "ok": True,
            "tokens_in": 1_000_000,
            "tokens_out": 0,
        },
        {
            "ts": "2026-10-09T02:00:00Z",
            "run_id": "r2",
            "target_id": "A2",
            "ok": True,
            "tokens_in": 0,
            "tokens_out": 1_000_000,
        },
        {"ts": "2026-10-09T03:00:00Z", "run_id": "r2", "target_id": "A2", "ok": False},
        {
            "ts": "2026-10-09T03:00:00Z",
            "run_id": "r2",
            "target_id": "A3",
            "ok": True,
            "tokens_in": 1_000_000,
            "tokens_out": 0,
        },
    ]
    log.write_text("\n".join(json.dumps(r) for r in rows) + "\n", "utf-8")
    prices = {"A2": Price(1.0, 4.0), "A3": Price(0.1, 0.2)}

    assert spend_from_log(log, prices) == pytest.approx({"A2": 5.0, "A3": 0.1})
    assert spend_from_log(log, prices, run_ids=["r1"]) == pytest.approx({"A2": 1.0})
    assert spend_from_log(log, prices, since_ts="2026-10-09T02:00:00Z") == pytest.approx(
        {"A2": 4.0, "A3": 0.1}
    )
    assert spend_from_log(tmp_path / "khong_co.jsonl", prices) == {}


@pytest.mark.parametrize(
    ("spent", "expected"),
    [(0.0, "ok"), (7.99, "ok"), (8.0, "alert"), (12.0, "alert"), (12.01, "stop")],
)
def test_budget_guard_thresholds(spent, expected):
    guard = BudgetGuard(batch_estimate_usd=10.0, alert_pct=80)
    assert guard.status(spent) == expected


def test_budget_guard_stops_at_total_budget():
    guard = BudgetGuard(
        batch_estimate_usd=10.0, total_budget_usd=100.0, spent_before_batch_usd=95.0
    )
    assert guard.status(5.0) == "stop"


def test_budget_guard_requires_estimate():
    with pytest.raises(CostConfigError):
        BudgetGuard(batch_estimate_usd=0)


def test_budget_from_env(monkeypatch):
    monkeypatch.delenv("COST_BUDGET_USD_TOTAL", raising=False)
    with pytest.raises(CostConfigError, match="COST_BUDGET_USD_TOTAL"):
        budget_from_env(10.0)
    monkeypatch.setenv("COST_BUDGET_USD_TOTAL", "100")
    monkeypatch.setenv("COST_BUDGET_USD_ALERT_PCT", "75")
    guard = budget_from_env(10.0)
    assert (guard.total_budget_usd, guard.alert_pct) == (100.0, 75.0)
