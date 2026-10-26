"""Kiểm bộ chạy ma trận tấn công (STT-46) — offline, không Qdrant/model/MailHog.

Phần thuần (kế hoạch, ghép ô, danh tính resume) chạy trực tiếp. Một run end-to-end dùng model giả,
tool giả và `seeded_run` giả (monkeypatch) để kiểm trình tự tiêm → chạy → chấm → ghi trace và cổng
RESUME (ngắt giữa chừng rồi chạy tiếp không chạy lại phần đã xong).
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass

import pandas as pd
import pytest

from agent.llm_client import LLMResult, ToolCall
from attack import runner as R
from eval.experiment import load_experiment
from interfaces import ToolResult
from obs.trace import export_runs, open_store

# ---------------------------------------------------------------------------
# build_defense (seam preset)
# ---------------------------------------------------------------------------


def test_build_defense_off_la_nodefense():
    from interfaces import NoDefense

    assert isinstance(R.build_defense("off"), NoDefense)


@pytest.mark.parametrize("preset", ["d1_only", "all", "d3_no_confirm"])
def test_build_defense_preset_khac_la_pipeline(preset):
    from defense.pipeline import DefensePipeline

    layer = R.build_defense(preset)
    assert isinstance(layer, DefensePipeline)
    assert layer.config_snapshot()["preset"] == preset


def test_build_defense_preset_la_bao_loi_harness():
    with pytest.raises(R.AttackRunnerError, match="không dựng được"):
        R.build_defense("reduced_3")  # nhóm preset, không phải một preset


def test_build_defenses_khoa_theo_anh_chup():
    layers = R.build_defenses(["off", "d3_only", "d3_no_confirm", "d3_only"])
    assert len(layers) == 3  # trùng tên dựng một lần; hai preset D3 khác ảnh chụp vì override
    for key, layer in layers.items():
        assert key == R.snapshot_json(layer)


def test_carrier_task_types_phu_moi_tac_vu_cho(carriers):
    mapping = R.carrier_task_types()
    assert set(mapping) == {c["id"] for c in carriers}
    assert mapping["CT-05"] == "SEND_MAIL"
    assert mapping["CT-04"] == "REPORT"


def test_carrier_task_types_khai_hai_loai_bao_loi():
    raw = {"defenses": {"d3_tool_policy": {"task_types": {
        "A": {"matches_carrier_tasks": ["CT-01"]},
        "B": {"matches_carrier_tasks": ["CT-01"]},
    }}}}
    with pytest.raises(R.AttackRunnerError, match="hai task_type"):
        R.carrier_task_types(raw)


# ---------------------------------------------------------------------------
# cell_units: khác nhau trước, lặp sau
# ---------------------------------------------------------------------------


def test_cell_units_distinct_truoc_lap_sau():
    pairs = [("p1", "c1"), ("p2", "c2"), ("p3", "c3")]
    units = R.cell_units(pairs, 5, seed="s")
    # 3 cặp phân biệt (repeat_idx 0) rồi 2 lần lặp (repeat_idx 1).
    reps = sorted(u[2] for u in units)
    assert reps == [0, 0, 0, 1, 1]
    first_three = {(p, c) for p, c, _ in units[:3]}
    assert len(first_three) == 3  # ba cặp đầu không trùng


def test_cell_units_tat_dinh():
    pairs = [("p1", "c1"), ("p2", "c2")]
    assert R.cell_units(pairs, 4, seed="x") == R.cell_units(pairs, 4, seed="x")


def test_cell_units_rong_bao_loi():
    with pytest.raises(R.AttackRunnerError):
        R.cell_units([], 3, seed="s")


# ---------------------------------------------------------------------------
# plan_block
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def exp():
    return load_experiment()


@pytest.fixture(scope="module")
def corpus():
    return R.load_corpus()


@pytest.fixture(scope="module")
def carriers():
    return R.load_carriers()


def _covered_cells(corpus, carriers):
    exp = load_experiment()
    b = exp.unit("B1")
    out = []
    for ch, techs in b.techniques_by_channel.items():
        for t in techs:
            for g in b.goals:
                ps = R.select_payloads(corpus, ch, t, g)
                if R._cell_pairs(ps, ch, carriers, tasks_path=R.DEFAULT_TASKS_PATH):
                    out.append((ch, t, g))
    return out


def test_plan_block_so_run_khop_cong_thuc(exp, corpus, carriers):
    # Một ô đã phủ chắc chắn: K1·T1·G2. Giới hạn vào nó, 1 target, n=4 ⇒ đúng 4 run.
    specs = R.plan_block(
        exp, "B1", corpus=corpus, carriers=carriers, seed=1,
        channels=["K1"], techniques=["T1"], goals=["G2"], targets=["A3"], n_per_cell=4,
    )
    assert len(specs) == 4
    assert {s.channel for s in specs} == {"K1"}
    assert {s.technique for s in specs} == {"T1"}
    assert {s.goal for s in specs} == {"G2"}
    assert len(set(specs)) == len(specs)  # không trùng danh tính


def test_plan_block_tat_dinh(exp, corpus, carriers):
    # K1·T3·G1 và K1·T3·G2 đều đã phủ.
    kw = dict(channels=["K1"], techniques=["T3"], goals=["G1", "G2"], targets=["A3"], n_per_cell=3)
    a = R.plan_block(exp, "B1", corpus=corpus, carriers=carriers, seed=7, **kw)
    b = R.plan_block(exp, "B1", corpus=corpus, carriers=carriers, seed=7, **kw)
    assert a == b


def test_plan_block_o_trong_bao_loi_liet_ke(exp, corpus, carriers):
    # B1 đầy đủ: corpus thiếu T6–T8 ⇒ nhiều ô trống, báo lỗi liệt kê.
    with pytest.raises(R.AttackRunnerError, match="ô không có payload|Ô trống"):
        R.plan_block(exp, "B1", corpus=corpus, carriers=carriers, seed=1)


def test_plan_block_tu_choi_khoi_chon_o(exp, corpus, carriers):
    with pytest.raises(R.AttackRunnerError, match="chọn ô theo quy tắc"):
        R.plan_block(exp, "B2", corpus=corpus, carriers=carriers, seed=1)


def test_plan_pilot_so_ca_va_cung_ca_moi_target(exp, corpus, carriers):
    specs = R.plan_pilot(exp, corpus=corpus, carriers=carriers, seed=1)
    pilot = exp.raw["pilot"]
    targets = [*pilot["targets"], *pilot["observe_targets"]]
    assert len(specs) == pilot["runs"] * len(targets)
    assert len(set(specs)) == len(specs)
    cases = {
        t: sorted((s.channel, s.technique, s.goal, s.payload_id, s.carrier_task_id)
                  for s in specs if s.target_id == t)
        for t in targets
    }
    assert all(c == cases[targets[0]] for c in cases.values())
    off = R.snapshot_json(R.build_defense("off"))
    assert {s.defense_config for s in specs} == {off}


def test_plan_pilot_phu_kenh_ky_thuat_muc_tieu_tac_vu(exp, corpus, carriers):
    specs = R.plan_pilot(exp, corpus=corpus, carriers=carriers, seed=1)
    covered = _covered_cells(corpus, carriers)
    got = {(s.channel, s.technique, s.goal) for s in specs}
    assert {(c, t) for c, t, _ in covered} <= {(c, t) for c, t, _ in got}
    assert {(c, g) for c, _, g in covered} <= {(c, g) for c, _, g in got}
    assert {s.carrier_task_id for s in specs} == {c["id"] for c in carriers}


def test_plan_pilot_tat_dinh(exp, corpus, carriers):
    a = R.plan_pilot(exp, corpus=corpus, carriers=carriers, seed=7)
    b = R.plan_pilot(exp, corpus=corpus, carriers=carriers, seed=7)
    assert a == b


# ---------------------------------------------------------------------------
# Hạ tầng giả cho run end-to-end
# ---------------------------------------------------------------------------


def _result(text: str) -> LLMResult:
    return LLMResult(
        text=text, tool_calls=[], tokens_in=10, tokens_out=5, latency_ms=1,
        target_id="A3", model="fake-model-1.0", response_model="fake-snap",
        attempts=1, finish_reason="stop",
    )


class FakeModel:
    model = "fake-model-1.0"

    def chat(self, messages, tools=None, **kw):
        return _result("Thời hạn bảo hành là 24 tháng.")


class FakeRegistry:
    """ToolLayer tối thiểu: không tool, không gọi — run blind không tool-call."""

    def list_tools(self):
        return []

    def reset_descriptions(self):
        pass

    def call_tool(self, call):  # pragma: no cover - run blind không gọi
        raise AssertionError("không nên gọi tool trong test này")


@dataclass
class _Stub:
    calls: list = None

    def __post_init__(self):
        self.calls = []


class FakeTools:
    def __init__(self):
        self.registry = FakeRegistry()
        self.db = _Stub()
        self.db.use_db = lambda p: self.db.calls.append(("use_db", p))
        self.http = _Stub()
        self.http.set_run = lambda r: self.http.calls.append(("set_run", r))
        self.tickets = _Stub()
        self.tickets.clear_tickets = lambda: self.tickets.calls.append("clear")
        self.mail = _Stub()
        self.mail.clear_mailbox = lambda: self.mail.calls.append("clear")


class _Canaries:
    def __init__(self):
        import uuid

        self.run_id = uuid.uuid4().hex
        self.sysprompt = f"CANARY_SYSPROMPT_{uuid.uuid4().hex}"
        self.db = f"CANARY_DB_{uuid.uuid4().hex}"

    def as_list(self):
        return [self.sysprompt, self.db]


@dataclass
class _Seeded:
    run_id: str
    canaries: _Canaries
    db_path: str = "/tmp/fake.db"

    @property
    def run_canaries(self):
        return self.canaries.as_list()


@contextlib.contextmanager
def _fake_seeded_run(run_id=None, **kw):
    c = _Canaries()
    yield _Seeded(run_id=c.run_id, canaries=c)


@dataclass
class _FakeK2Result:
    delivered: bool = True


class _FakeK2Layer:
    def __init__(self):
        self.result = _FakeK2Result()

    def list_tools(self):
        return []

    def call_tool(self, call):  # pragma: no cover
        raise AssertionError


@dataclass
class _FakeK1Result:
    """Probe báo tới top-k; `doc_ids` là tài liệu tiêm mà search_kb thật phải trả thì mới delivered."""

    delivered: bool = True
    doc_ids: tuple = ("inject::run",)


def _ctx(engine, corpus, carriers, monkeypatch, *, channel):
    monkeypatch.setattr(R, "seeded_run", _fake_seeded_run)
    return R.RunContext(
        engine=engine,
        batch_id="attack-B1-test",
        env_hash="env-hash",
        harness_version="core-a@test",
        models={"A3": FakeModel()},
        tools=FakeTools(),
        corpus_by_id={p["id"]: p for p in corpus},
        carriers_by_id={c["id"]: c for c in carriers},
        core_params={"max_steps": 4, "max_tokens": 256},
        kb_top_k=5,
        inject_k1=lambda *a, **k: _FakeK1Result(),
        build_k2_layer=lambda *a, **k: _FakeK2Layer(),
        cleanup_k1=lambda *a, **k: None,
    )


def _spec(corpus, carriers, channel, preset="off"):
    # Lấy một cặp (payload, carrier) phủ được cho kênh.
    for (ch, t, g) in _covered_cells(corpus, carriers):
        if ch == channel:
            ps = R.select_payloads(corpus, ch, t, g)
            pairs = R._cell_pairs(ps, ch, carriers, tasks_path=R.DEFAULT_TASKS_PATH)
            pid, cid = pairs[0]
            return R.AttackRunSpec(
                repeat_idx=0, target_id="A3", channel=ch, technique=t, goal=g,
                attacker_mode="blind",
                defense_config=R.snapshot_json(R.build_defense(preset)),
                carrier_task_id=cid, payload_id=pid,
            )
    raise AssertionError(f"không có ô phủ cho kênh {channel}")


@pytest.mark.parametrize("channel", ["K1", "K2a"])
def test_run_one_attack_ghi_trace_va_nhan(tmp_path, exp, corpus, carriers, monkeypatch, channel):
    engine = open_store(tmp_path / "t.sqlite")
    ctx = _ctx(engine, corpus, carriers, monkeypatch, channel=channel)
    spec = _spec(corpus, carriers, channel)
    rid = R.run_one_attack(spec, ctx)
    df = export_runs(engine, batch_id=ctx.batch_id)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["run_kind"] == "attack"
    assert row["channel"] == channel
    assert row["technique"] == spec.technique
    assert row["goal"] == spec.goal
    assert row["attacker_mode"] == "blind"
    assert row["payload_id"] == spec.payload_id
    if channel == "K1":
        # Agent không gọi search_kb ⇒ tài liệu tiêm không vào ngữ cảnh dù probe báo tới.
        assert bool(row["delivered"]) is False
        assert bool(row["delivered_probe"]) is True
    else:
        assert bool(row["delivered"]) is True
        assert row["delivered_probe"] is None or pd.isna(row["delivered_probe"])
    assert row["run_id"] == rid


class _SearchingModel:
    """Gọi search_kb một lần rồi trả lời — để `delivered` K1 đọc từ kết quả tool thật."""

    model = "fake-model-1.0"

    def __init__(self):
        self.n = 0

    def chat(self, messages, tools=None, **kw):
        self.n += 1
        if self.n == 1:
            call = ToolCall(id="c1", name="search_kb", arguments={"query": "bảo hành"},
                            arguments_raw='{"query": "bảo hành"}')
            return LLMResult(
                text=None, tool_calls=[call], tokens_in=10, tokens_out=5, latency_ms=1,
                target_id="A3", model=self.model, response_model="fake-snap",
                attempts=1, finish_reason="tool_calls",
            )
        return _result("Thời hạn bảo hành là 24 tháng.")


class _SearchRegistry(FakeRegistry):
    def __init__(self, doc_ids):
        self.doc_ids = doc_ids

    def call_tool(self, call):
        results = [{"doc_id": d, "chunk": "..."} for d in self.doc_ids]
        return ToolResult(call_id=call.id, name=call.name,
                          content=json.dumps({"results": results}, ensure_ascii=False))


@pytest.mark.parametrize(
    ("returned", "expected"),
    [(["POL-003.md", "inject::run"], True), (["POL-003.md"], False)],
)
def test_run_one_attack_k1_delivered_tu_search_kb_that(
    tmp_path, exp, corpus, carriers, monkeypatch, returned, expected
):
    engine = open_store(tmp_path / "t.sqlite")
    ctx = _ctx(engine, corpus, carriers, monkeypatch, channel="K1")
    ctx.models["A3"] = _SearchingModel()
    ctx.tools.registry = _SearchRegistry(returned)
    R.run_one_attack(_spec(corpus, carriers, "K1"), ctx)
    row = export_runs(engine, batch_id=ctx.batch_id).iloc[0]
    assert bool(row["delivered"]) is expected
    assert bool(row["delivered_probe"]) is True


def test_resume_bo_qua_run_da_co(tmp_path, exp, corpus, carriers, monkeypatch):
    engine = open_store(tmp_path / "t.sqlite")
    ctx = _ctx(engine, corpus, carriers, monkeypatch, channel="K1")
    spec = _spec(corpus, carriers, "K1")
    R.run_one_attack(spec, ctx)
    done = R.done_specs(engine, ctx.batch_id)
    assert len(done) == 1
    # Danh tính dựng lại từ store khớp spec đã chạy (trừ defense_config: so chuẩn hóa).
    got = next(iter(done))
    assert (got.target_id, got.channel, got.technique, got.goal, got.carrier_task_id,
            got.payload_id, got.repeat_idx) == (
        spec.target_id, spec.channel, spec.technique, spec.goal, spec.carrier_task_id,
        spec.payload_id, spec.repeat_idx)


def test_run_one_attack_preset_all_ghi_anh_chup_va_task_type(
    tmp_path, exp, corpus, carriers, monkeypatch
):
    import json

    engine = open_store(tmp_path / "t.sqlite")
    ctx = _ctx(engine, corpus, carriers, monkeypatch, channel="K1")
    ctx.defenses = R.build_defenses(["all"])
    spec = _spec(corpus, carriers, "K1", preset="all")
    seen = {}
    real_core = R.CoreA

    class SpyCore(real_core):
        def run(self, user_query, *, session, recorder):
            seen["task_type"] = session.task_type
            seen["defense"] = self.defense
            return super().run(user_query, session=session, recorder=recorder)

    monkeypatch.setattr(R, "CoreA", SpyCore)
    R.run_one_attack(spec, ctx)
    row = export_runs(engine, batch_id=ctx.batch_id).iloc[0]
    snap = json.loads(row["defense_config"])
    assert snap["preset"] == "all"
    assert snap["enabled"] == [
        "d1_spotlighting", "d2_input_sanitizer", "d3_tool_policy", "d4_egress_filter"
    ]
    assert seen["defense"] is ctx.defenses[spec.defense_config]
    assert seen["task_type"] == R.carrier_task_types()[spec.carrier_task_id]


def test_run_one_attack_thieu_tang_phong_thu_bao_loi(tmp_path, exp, corpus, carriers, monkeypatch):
    engine = open_store(tmp_path / "t.sqlite")
    ctx = _ctx(engine, corpus, carriers, monkeypatch, channel="K1")
    spec = _spec(corpus, carriers, "K1", preset="d3_only")
    with pytest.raises(R.AttackRunnerError, match="build_defenses"):
        R.run_one_attack(spec, ctx)


def test_carrier_runtime_tra_rang_buoc_g2(carriers):
    # CT-05 gửi email, CT-06 mở phiếu: thiếu runtime thì scorer báo MissingRuntimeContextError
    # ngay khi model gọi tool ghi — lô B1 dừng ở run CT-05/CT-06 đầu tiên.
    by_id = {c["id"]: c for c in carriers}
    assert set(R.carrier_runtime(by_id["CT-05"])) == {"expected_to"}
    assert "@" in R.carrier_runtime(by_id["CT-05"])["expected_to"]
    ct06 = R.carrier_runtime(by_id["CT-06"])
    assert ct06["expected_priority"] == by_id["CT-06"]["expected_priority"]
    assert isinstance(ct06["expected_customer_id"], int)
    for cid in ("CT-01", "CT-02", "CT-03", "CT-04"):
        assert R.carrier_runtime(by_id[cid]) == {}


def test_plan_pilot_loc_kenh_giu_dung_ca_cua_lo_day_du(exp, corpus, carriers):
    full = R.plan_pilot(exp, corpus=corpus, carriers=carriers, seed=1)
    k1 = R.plan_pilot(exp, corpus=corpus, carriers=carriers, seed=1, channels=["K1"])
    assert k1 and {s.channel for s in k1} == {"K1"}
    assert set(k1) == {s for s in full if s.channel == "K1"}
