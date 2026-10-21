"""LLM judge của USR (STT-37) — prompt, parse, quy ước không gọi judge. Không gọi API thật."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from agent.prompts import load_prompt_config
from eval.judge import (
    NO_TOOL_CALLS,
    TRUNCATED,
    JudgeConfig,
    JudgeConfigError,
    JudgeError,
    build_messages,
    format_tool_calls,
    judge_run,
    parse_verdict,
)

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ROOT / "config" / "prompts.yaml"
BENIGN = json.loads((ROOT / "data" / "benign_queries.json").read_text(encoding="utf-8"))["queries"]


class FakeClient:
    model = "claude-sonnet-5-5"

    def __init__(self, text: str | None, finish_reason: str = "stop") -> None:
        self.reply = SimpleNamespace(text=text, finish_reason=finish_reason)
        self.calls: list[tuple[list, dict]] = []

    def chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return self.reply


@pytest.fixture(scope="module")
def cfg() -> JudgeConfig:
    return JudgeConfig.load()


def _steps() -> list[dict]:
    return [
        {"step_idx": 0, "kind": "llm", "tool_name": None, "tool_args": None, "tool_result": None},
        {
            "step_idx": 1,
            "kind": "tool",
            "tool_name": "query_customer_db",
            "tool_args": '{"sql_or_filter": "tax_code = \'809570154\'"}',
            "tool_result": '{"rows": [[1, "Việt Tiến", 18900000]]}',
        },
        {
            "step_idx": 2,
            "kind": "defense",
            "tool_name": "send_email",
            "tool_args": '{"to": "x@y.z"}',
            "tool_result": None,
        },
    ]


def test_cau_hinh_that_nap_duoc_va_loader_prompt_agent_van_nhan(cfg):
    assert cfg.max_tokens > 0 and "{answer}" in cfg.user_template
    load_prompt_config()  # khóa `judge` không làm hỏng loader prompt agent


def test_prompt_hash_on_dinh_va_doi_khi_doi_prompt(cfg):
    assert cfg.prompt_hash() == JudgeConfig.load().prompt_hash()
    changed = JudgeConfig(**{**cfg.__dict__, "max_tokens": cfg.max_tokens + 1})
    assert changed.prompt_hash() != cfg.prompt_hash()


@pytest.mark.parametrize(
    "mutate, expect",
    [
        (lambda j: j.pop("max_tokens"), "thiếu judge.max_tokens"),
        (lambda j: j.update(extra=1), "khóa lạ judge.extra"),
        (lambda j: j.update(max_answer_chars=0), "max_answer_chars"),
        (lambda j: j.update(user_template="{query} {rubric} {answer}"), "phải có đúng biến"),
    ],
)
def test_cau_hinh_sai_bi_tu_choi(tmp_path, mutate, expect):
    raw = yaml.safe_load(PROMPTS.read_text(encoding="utf-8"))
    mutate(raw["judge"])
    path = tmp_path / "prompts.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with pytest.raises(JudgeConfigError, match=expect):
        JudgeConfig.load(path)


def test_format_tool_calls_theo_thu_tu_va_ghi_tool_bi_chan():
    text = format_tool_calls(list(reversed(_steps())), max_result_chars=1000)
    lines = text.splitlines()
    assert lines[0].startswith("1. query_customer_db")
    assert "18900000" in lines[1]
    assert lines[2].startswith("2. send_email") and "bị chặn" in lines[3]


def test_format_tool_calls_cat_ket_qua_dai_va_khong_tool():
    steps = _steps()[:2]
    steps[1]["tool_result"] = "x" * 50
    assert format_tool_calls(steps, max_result_chars=10).endswith("x" * 10 + TRUNCATED)
    assert format_tool_calls(_steps()[:1], max_result_chars=10) == NO_TOOL_CALLS


def test_build_messages_dien_du_bien_va_cau_tra_loi_co_ngoac_nhon(cfg):
    q = BENIGN[0]
    msgs = build_messages(
        query=q["user_query_vi"],
        rubric=q["expected_answer"]["judge_rubric"],
        tool_calls="1. search_kb {}",
        answer='Kết quả {"a": 1} theo POL-003',
        cfg=cfg,
    )
    assert [m["role"] for m in msgs] == ["system", "user"]
    user = msgs[1]["content"]
    assert q["user_query_vi"] in user and q["expected_answer"]["judge_rubric"] in user
    assert '{"a": 1}' in user and "{query}" not in user


@pytest.mark.parametrize(
    "text, expected",
    [
        ('{"pass": true, "reason": "đúng"}', (True, "đúng")),
        ('  {"pass": false, "reason": "thiếu 24 tháng"}\n', (False, "thiếu 24 tháng")),
        ('```json\n{"pass": true, "reason": "ok"}\n```', (True, "ok")),
    ],
)
def test_parse_verdict_hop_le(text, expected):
    assert parse_verdict(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "Đạt.",
        'Kết luận: {"pass": true, "reason": "ok"}',
        '{"pass": "true", "reason": "ok"}',
        '{"pass": true}',
        '{"pass": true, "reason": "ok", "score": 1}',
        "[true]",
    ],
)
def test_parse_verdict_sai_dinh_dang_la_judge_error(text):
    with pytest.raises(JudgeError):
        parse_verdict(text)


def test_judge_run_goi_model_va_ghi_ten_model(cfg):
    client = FakeClient('{"pass": true, "reason": "đúng 24 tháng"}')
    verdict = judge_run(client, BENIGN[0], "Bảo hành 24 tháng (POL-003).", _steps(), cfg=cfg)
    assert verdict.judge_pass is True and verdict.called
    assert verdict.judge_model == "claude-sonnet-5-5"
    ((messages, kwargs),) = client.calls
    assert kwargs == {"max_tokens": cfg.max_tokens}
    assert "query_customer_db" in messages[1]["content"]


@pytest.mark.parametrize("answer", [None, "", "   "])
def test_khong_co_cau_tra_loi_thi_khong_goi_judge(cfg, answer):
    client = FakeClient('{"pass": true, "reason": "x"}')
    verdict = judge_run(client, BENIGN[0], answer, _steps(), cfg=cfg)
    assert verdict.judge_pass is False and verdict.judge_model is None and not verdict.called
    assert client.calls == []


def test_judge_cham_max_tokens_la_judge_error(cfg):
    client = FakeClient('{"pass": tr', finish_reason="length")
    with pytest.raises(JudgeError, match="max_tokens"):
        judge_run(client, BENIGN[0], "trả lời", _steps(), cfg=cfg)


def test_moi_cau_lanh_tinh_co_rubric():
    assert all(q["expected_answer"]["judge_rubric"].strip() for q in BENIGN)
