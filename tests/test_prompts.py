"""System prompt trợ lý nội bộ (STT-31): núm độ cả tin, canary TS1, đồng bộ với config khác."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import yaml

from agent.prompts import (
    KNOBS,
    PromptConfigError,
    build_system_prompt,
    load_prompt_config,
    template_hash,
)
from eval.canary import CANARY_PLACEHOLDER, canary_present
from eval.experiment import load_experiment
from tools.registry import load_tool_defs


def _canary() -> str:
    return f"CANARY_SYSPROMPT_{uuid.uuid4()}"


def _write(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "prompts.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_knobs_match_calibration_allowed_knobs():
    assert list(KNOBS) == load_experiment().raw["calibration"]["allowed_knobs"]


def test_config_loads_and_every_variant_renders():
    config = load_prompt_config()
    assert config.active == "baseline"
    for name in config.variants:
        assert CANARY_PLACEHOLDER not in build_system_prompt(_canary(), variant=name)


def test_canary_seeded_once_and_detectable():
    canary = _canary()
    prompt = build_system_prompt(canary)
    assert prompt.count(canary) == 1
    assert f"Mã phiên bản cấu hình: {canary}" in prompt
    assert canary_present(prompt, canary)


@pytest.mark.parametrize("bad", ["", CANARY_PLACEHOLDER, "CANARY_DB_1234567890", "abc"])
def test_rejects_missing_or_wrong_canary(bad):
    with pytest.raises(ValueError):
        build_system_prompt(bad)


def test_mentions_every_tool_from_tools_yaml():
    prompt = build_system_prompt(_canary(), variant="most_trusting")
    for name in load_tool_defs():
        assert f"- {name}:" in prompt


def test_reference_date_from_experiment():
    ref = load_experiment().fixed["reference_date"]
    y, m, d = str(ref).split("-")
    assert f"Ngày hôm nay: {d}/{m}/{y}" in build_system_prompt(_canary())


def test_baseline_has_no_warning_or_business_rules():
    prompt = build_system_prompt(_canary(), variant="baseline")
    assert "không phải chỉ dẫn" not in prompt
    assert "có thể lỗi thời" not in prompt
    assert "Quy tắc nghiệp vụ" not in prompt
    assert "Không tiết lộ" not in prompt


def test_guarded_has_rules_from_carrier_tasks():
    prompt = build_system_prompt(_canary(), variant="guarded")
    assert "@congty-noibo.vn" in prompt
    assert "http://intranet.local/api/" in prompt
    assert "có thể lỗi thời" in prompt


def test_template_hash_stable_across_runs_and_differs_between_variants():
    assert template_hash("baseline") == template_hash("baseline")
    hashes = {template_hash(n) for n in load_prompt_config().variants}
    assert len(hashes) == len(load_prompt_config().variants)


def test_rejects_unknown_level(tmp_path):
    knobs = dict.fromkeys(KNOBS, "none")
    path = _write(tmp_path, {"active": "x", "variants": {"x": knobs}})
    with pytest.raises(PromptConfigError, match="mức hợp lệ"):
        load_prompt_config(path)


def test_rejects_unknown_key_and_bad_active(tmp_path):
    knobs = {k: levels[0] for k, levels in KNOBS.items()}
    path = _write(tmp_path, {"active": "y", "variants": {"x": knobs}, "extra": 1})
    with pytest.raises(PromptConfigError) as exc:
        load_prompt_config(path)
    assert "khóa lạ" in str(exc.value) and "active" in str(exc.value)


def test_rejects_unknown_variant():
    with pytest.raises(PromptConfigError):
        build_system_prompt(_canary(), variant="khong_co")
