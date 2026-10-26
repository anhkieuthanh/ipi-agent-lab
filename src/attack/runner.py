"""Bộ chạy ma trận thực nghiệm tấn công — STT-46.

Đọc `config/experiment.yaml` qua `eval.experiment`, sinh tích Descartes các ô của MỘT khối, chạy
từng run qua lõi agent, chấm, ghi trace. Một lô = một khối: `scripts/run_matrix.py` là lớp CLI mỏng
gọi module này (như `run_utility_baseline` với khối USR nền).

Một run tấn công:

    seeded_run (canary TS1/TS2, bản sao customers.db, gắn handler)
      → reset hộp thư + phiếu + mô tả tool + dọn KB của run trước
      → tiêm payload: K1 `inject_and_probe` vào KB (ghi `delivered`); K2 bọc `K2ToolLayer`
      → TraceRecorder: CoreA.run(carrier.user_query_vi) → score(ScoreContext(activation_check))
      → K1: cleanup(run_id) xóa tài liệu đã chèn

CHECKPOINT/RESUME: mỗi run commit ngay vào SQLite (TraceRecorder). Chạy lại cùng `--batch-id` thì
`done_specs` bỏ qua đơn vị đã có trong store — lô bị ngắt chạy tiếp, không chạy lại phần đã xong
(yêu cầu cứng STT-46). Backoff rate-limit do `LLMClient` lo (429/5xx, mũ + jitter) — runner KHÔNG tự
backoff lại.

PHÒNG THỦ: `build_defense` dựng `defense.pipeline.DefensePipeline` cho mọi preset chạy được của
`config/defenses.yaml` (STT-55); `off` vẫn là `NoDefense`. Run tấn công khai `task_type` của tác vụ
chở theo `task_types.*.matches_carrier_tasks` — harness đóng vai nhân viên chọn loại tác vụ trước
phiên (quy tắc cứng #3), không suy ra từ câu hỏi. Các khối chọn ô theo quy tắc
(`cells.selected: null`) bị `unresolved` chặn tới khi B1 xong.
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from agent.core import CoreA
from agent.llm_client import LLMClientError
from agent.prompts import build_system_prompt
from attack import injector_k1, injector_k2
from attack.payloads.schema import DEFAULT_TASKS_PATH, load_payloads
from defense.pipeline import DEFAULT_CONFIG_PATH as DEFENSES_PATH
from defense.pipeline import DefensePipeline, load_defenses_raw
from eval.canary import DEFAULT_CUSTOMERS_DB, seeded_run
from eval.experiment import Block, Experiment
from eval.scorer import ScoreContext, score
from eval.utility_baseline import benign_runtime
from interfaces import NoDefense, SessionState
from obs.trace import RunMeta, TraceRecorder, export_runs

__all__ = [
    "RECOVERABLE",
    "AttackRunSpec",
    "AttackRunnerError",
    "PAYLOADS_DIR",
    "RunContext",
    "build_defense",
    "build_defenses",
    "carrier_task_types",
    "done_specs",
    "load_corpus",
    "load_carriers",
    "plan_block",
    "plan_pilot",
    "run_one_attack",
    "select_payloads",
    "cell_units",
]

REPO_ROOT = Path(__file__).resolve().parents[2]
PAYLOADS_DIR = REPO_ROOT / "src" / "attack" / "payloads"
HARNESS_PREFIX = "core-a@"

#: Lỗi hạ tầng mà run ghi `parse_error` rồi lô chạy tiếp (như `utility_baseline.RECOVERABLE`). Lỗi
#: khác dừng lô — harness lỗi hiện ra như "model kém" nếu để chạy tiếp (Y_TUONG_DU_AN.md mục 17).
RECOVERABLE: tuple[type[BaseException], ...] = (LLMClientError,)


class AttackRunnerError(RuntimeError):
    """Mâu thuẫn harness của runner: ô không có payload/tác vụ chở, preset chưa dựng được, khối sai
    hình dạng. KHÔNG phải tín hiệu về hành vi model."""


# ---------------------------------------------------------------------------
# Phòng thủ theo preset + loại tác vụ của tác vụ chở
# ---------------------------------------------------------------------------


def build_defense(preset: str, *, defenses_path: Path | None = None) -> Any:
    """Dựng tầng phòng thủ cho `preset`. `off` → NoDefense; preset khác → DefensePipeline đọc
    `config/defenses.yaml` (quy tắc cứng #4: tham số ở config, không hard-code)."""
    if preset == "off":
        return NoDefense()
    try:
        return DefensePipeline(preset=preset, path=defenses_path or DEFENSES_PATH)
    except ValueError as e:
        raise AttackRunnerError(f"preset {preset!r} không dựng được: {e}") from e


def snapshot_json(defense: Any) -> str:
    """Ảnh chụp cấu hình dạng chuỗi — chuỗi hóa GIỐNG HỆT `obs.trace._dump` (ensure_ascii=False,
    sort_keys) để khớp đúng cột `defense_config` mà trace ghi ra; lệch thì resume chạy lại mọi run."""
    return json.dumps(defense.config_snapshot(), ensure_ascii=False, sort_keys=True)


def build_defenses(
    presets: Iterable[str], *, defenses_path: Path | None = None
) -> dict[str, Any]:
    """{ảnh chụp JSON → tầng phòng thủ} cho các preset của một lô. `run_one_attack` tra theo
    `AttackRunSpec.defense_config`, nên một lô dựng mỗi preset đúng một lần."""
    layers = (build_defense(p, defenses_path=defenses_path) for p in dict.fromkeys(presets))
    return {snapshot_json(d): d for d in layers}


def carrier_runtime(
    carrier: Mapping[str, Any], db_path: Path = DEFAULT_CUSTOMERS_DB
) -> dict[str, Any]:
    """Ràng buộc tra lúc chạy của tác vụ chở cho G2 (`expected_to`, `expected_customer_id`,
    `expected_priority`) — cùng quy tắc với câu lành tính (`eval.utility_baseline.benign_runtime`).
    Tra `data/customers.db` gốc: bản sao gieo canary của run chỉ khác cột `canary_note`."""
    spec = {
        "expected_tool_calls": [{"tool": t} for t in carrier.get("required_tools") or []],
        "db_refs": carrier.get("db_refs"),
        "expected_priority": carrier.get("expected_priority"),
    }
    return benign_runtime(spec, db_path)


def carrier_task_types(raw: Mapping[str, Any] | None = None) -> dict[str, str]:
    """{tác vụ chở → task_type} từ `d3_tool_policy.task_types.*.matches_carrier_tasks`.

    Đây là input "người dùng chọn trước phiên" của run tấn công: tác vụ chở là việc nhân viên đang
    làm, nên loại tác vụ đi kèm tác vụ chở, không suy ra từ câu hỏi hay từ payload (quy tắc cứng
    #3). Tác vụ chở khai ở hai loại là lỗi cấu hình.
    """
    raw = raw if raw is not None else load_defenses_raw()
    out: dict[str, str] = {}
    for name, body in raw["defenses"]["d3_tool_policy"]["task_types"].items():
        for cid in body.get("matches_carrier_tasks") or []:
            if cid in out:
                raise AttackRunnerError(f"tác vụ chở {cid} khai ở hai task_type: {out[cid]}, {name}")
            out[cid] = name
    return out


# ---------------------------------------------------------------------------
# Đơn vị run = danh tính resume
# ---------------------------------------------------------------------------


@dataclass(frozen=True, order=True)
class AttackRunSpec:
    """Một run tấn công. Mọi trường khớp cột `runs` để `done_specs` dò lại được sau ngắt.

    `defense_config` là ảnh chụp JSON của preset (`config_snapshot()`), không phải tên preset: cột
    `runs` lưu cấu hình chứ không lưu tên, nên danh tính resume phải dùng chính ảnh chụp đó.
    """

    repeat_idx: int
    target_id: str
    channel: str
    technique: str
    goal: str
    attacker_mode: str
    defense_config: str
    carrier_task_id: str
    payload_id: str


# ---------------------------------------------------------------------------
# Corpus payload + tác vụ chở
# ---------------------------------------------------------------------------


def load_corpus(path: Path | str = PAYLOADS_DIR) -> list[dict[str, Any]]:
    """Payload hợp lệ của corpus. Payload sai schema bị loại kèm cảnh báo — không chạy ma trận trên
    payload chưa đạt `activation_check` (quy tắc cứng #5 tinh thần: chỉ đo cái kiểm được)."""
    payloads, report = load_payloads(path)
    if not report.all_ok:
        bad = ", ".join(sorted(report.errors_by_id))
        raise AttackRunnerError(f"corpus payload có bản sai schema, sửa trước khi chạy: {bad}")
    return payloads


def load_carriers(path: Path | str = DEFAULT_TASKS_PATH) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data["carrier_tasks"]


def select_payloads(
    corpus: Iterable[dict[str, Any]], channel: str, technique: str, goal: str
) -> list[dict[str, Any]]:
    """Payload của ô (kênh × kỹ thuật × mục tiêu): khớp code kỹ thuật, mục tiêu, và khai kênh."""
    out = [
        p
        for p in corpus
        if (p.get("technique") or {}).get("code") == technique
        and p.get("goal") == goal
        and channel in (p.get("channels") or [])
    ]
    return sorted(out, key=lambda p: p["id"])


def _cell_pairs(
    payloads: Sequence[dict[str, Any]],
    channel: str,
    carriers: Sequence[dict[str, Any]],
    *,
    tasks_path: Path | str,
) -> list[tuple[str, str]]:
    """Cặp (payload_id, carrier_id) ghép được trong ô, thứ tự tất định theo id."""
    by_id = {c["id"]: c for c in carriers}
    pairs: list[tuple[str, str]] = []
    for p in payloads:
        if channel == "K1":
            valid = injector_k1.valid_carriers(p, tasks_path=tasks_path)
        else:
            valid = injector_k2.valid_carriers(p, channel, carriers)
        for cid in valid:
            if cid in by_id:
                pairs.append((p["id"], cid))
    return sorted(set(pairs))


def cell_units(
    pairs: Sequence[tuple[str, str]], n: int, *, seed: str
) -> list[tuple[str, str, int]]:
    """`n` đơn vị lấy mẫu của ô: cặp (payload, tác vụ chở) KHÁC NHAU trước, LẶP sau (giao thức mục
    2.2). Trả [(payload_id, carrier_id, repeat_idx)]. Tất định theo `seed`."""
    if not pairs:
        raise AttackRunnerError("ô không có cặp (payload, tác vụ chở) nào — corpus thiếu")
    order = list(pairs)
    random.Random(seed).shuffle(order)
    units: list[tuple[str, str, int]] = []
    for i in range(n):
        pid, cid = order[i % len(order)]
        units.append((pid, cid, i // len(order)))
    return units


# ---------------------------------------------------------------------------
# Kế hoạch một khối
# ---------------------------------------------------------------------------


def _technique_block(block: Block) -> Block:
    """Trả về phần khối sinh ô theo `techniques_by_channel`. Khối chọn ô theo quy tắc (B2/B5) chưa
    hỗ trợ (cần B1 xong + D1–D4); báo lỗi rõ thay vì sinh thiếu."""
    if block.parts:
        raise AttackRunnerError(
            f"khối {block.id} gồm nhiều phần — chạy từng phần, chưa hỗ trợ trong một lệnh"
        )
    if block.cells is not None:
        raise AttackRunnerError(
            f"khối {block.id} chọn ô theo quy tắc (cells) — cần B1 xong và D1–D4; chưa hỗ trợ"
        )
    if block.attacker_mode == "adaptive":
        raise AttackRunnerError(f"khối {block.id} là tấn công thích ứng (B5) — chưa hỗ trợ")
    if not block.techniques_by_channel:
        raise AttackRunnerError(f"khối {block.id} không sinh ô theo techniques_by_channel")
    return block


def plan_block(
    exp: Experiment,
    block_id: str,
    *,
    corpus: Sequence[dict[str, Any]],
    carriers: Sequence[dict[str, Any]],
    seed: int,
    targets: Sequence[str] | None = None,
    presets: Sequence[str] | None = None,
    n_per_cell: int | None = None,
    channels: Sequence[str] | None = None,
    techniques: Sequence[str] | None = None,
    goals: Sequence[str] | None = None,
    tasks_path: Path | str = DEFAULT_TASKS_PATH,
) -> list[AttackRunSpec]:
    """Mọi run của `block_id`, thứ tự chạy (xáo trộn có seed). Lọc (`channels`/`techniques`/`goals`/
    `targets`/`presets`/`n_per_cell`) chỉ cho chạy thử — khi không lọc, số run khớp `planned_runs`.
    """
    block = _technique_block(exp.unit(block_id))
    targets = list(targets or block.targets)
    presets = list(presets or block.presets)
    goals = list(goals or block.goals)
    n = n_per_cell if n_per_cell is not None else block.n_per_cell
    if n is None:
        raise AttackRunnerError(f"khối {block_id} thiếu n_per_cell")
    snapshots = {p: snapshot_json(build_defense(p)) for p in presets}

    specs: list[AttackRunSpec] = []
    empty: list[str] = []
    for channel, techs in block.techniques_by_channel.items():
        if channels and channel not in channels:
            continue
        for technique in techs:
            if techniques and technique not in techniques:
                continue
            for goal in goals:
                payloads = select_payloads(corpus, channel, technique, goal)
                pairs = _cell_pairs(payloads, channel, carriers, tasks_path=tasks_path)
                if not pairs:
                    empty.append(f"{channel}·{technique}·{goal}")
                    continue
                units = cell_units(pairs, n, seed=f"{seed}:{channel}:{technique}:{goal}")
                for target in targets:
                    for preset in presets:
                        for pid, cid, rep in units:
                            specs.append(
                                AttackRunSpec(
                                    repeat_idx=rep,
                                    target_id=target,
                                    channel=channel,
                                    technique=technique,
                                    goal=goal,
                                    attacker_mode=block.attacker_mode or "blind",
                                    defense_config=snapshots[preset],
                                    carrier_task_id=cid,
                                    payload_id=pid,
                                )
                            )
    if empty:
        raise AttackRunnerError(
            f"khối {block_id}: {len(empty)} ô không có payload/tác vụ chở — corpus chưa đủ "
            f"(STT-47…50 bổ sung T6–T8 và thêm payload). Ô trống: {', '.join(sorted(empty))}. "
            "Thu hẹp bằng --channels/--techniques/--goals để chạy phần đã phủ."
        )
    random.Random(f"{seed}:{block_id}").shuffle(specs)
    return specs


def plan_pilot(
    exp: Experiment,
    *,
    corpus: Sequence[dict[str, Any]],
    carriers: Sequence[dict[str, Any]],
    seed: int,
    source_block: str = "B1",
    tasks_path: Path | str = DEFAULT_TASKS_PATH,
) -> list[AttackRunSpec]:
    """Pilot STT-60: `pilot.runs` ca lấy từ ô ĐÃ PHỦ của `source_block`, D=OFF, mỗi ca 1 run trên mỗi
    target ở `pilot.targets` + `pilot.observe_targets` (cùng các ca cho mọi target).

    Chọn ca tất định theo `seed`:
      1. Ô = (kênh × kỹ thuật × mục tiêu) có ít nhất một cặp (payload, tác vụ chở). Ô trống bỏ qua —
         pilot đo phần corpus đã có, ô trống ghi vào pilot_findings, không lấp bằng payload viết vội.
      2. Thừa ô: bỏ dần ô theo thứ tự xáo trộn, chỉ bỏ khi mọi (kênh, kỹ thuật) và (kênh, mục tiêu)
         vẫn còn ít nhất một ô. Thiếu ô: lặp lại ô theo thứ tự xáo trộn, lấy cặp khác.
      3. Mỗi ca lấy cặp có payload chưa dùng và tác vụ chở ít dùng nhất — phủ CT-01…CT-06.
    """
    block = _technique_block(exp.unit(source_block))
    pilot = exp.raw["pilot"]
    n = int(pilot["runs"])
    targets = [*pilot["targets"], *(pilot.get("observe_targets") or [])]
    rng = random.Random(f"{seed}:pilot")

    cell_pairs: dict[tuple[str, str, str], list[tuple[str, str]]] = {}
    for channel, techs in block.techniques_by_channel.items():
        for technique in techs:
            for goal in block.goals:
                payloads = select_payloads(corpus, channel, technique, goal)
                pairs = _cell_pairs(payloads, channel, carriers, tasks_path=tasks_path)
                if pairs:
                    cell_pairs[(channel, technique, goal)] = pairs
    if not cell_pairs:
        raise AttackRunnerError(f"khối {source_block} không có ô nào phủ được — corpus trống")

    cells = sorted(cell_pairs)
    rng.shuffle(cells)
    chosen = list(cells)

    def _covers(cs: Sequence[tuple[str, str, str]]) -> set[tuple[str, str]]:
        return {(c, t) for c, t, _ in cs} | {(c, g) for c, _, g in cs}

    need = _covers(chosen)
    for cell in list(cells):
        if len(chosen) <= n:
            break
        rest = [c for c in chosen if c != cell]
        if _covers(rest) == need:
            chosen = rest
    while len(chosen) < n:
        chosen.append(cells[(len(chosen) - len(cells)) % len(cells)])

    used_payloads: set[str] = set()
    used_pairs: set[tuple[str, str]] = set()
    carrier_count: dict[str, int] = {c["id"]: 0 for c in carriers}
    units: list[tuple[tuple[str, str, str], str, str]] = []
    for cell in chosen:
        options = [p for p in cell_pairs[cell] if p not in used_pairs] or cell_pairs[cell]
        rng.shuffle(options)
        pid, cid = min(options, key=lambda p: (p[0] in used_payloads, carrier_count.get(p[1], 0)))
        used_payloads.add(pid)
        used_pairs.add((pid, cid))
        carrier_count[cid] = carrier_count.get(cid, 0) + 1
        units.append((cell, pid, cid))

    snapshot = snapshot_json(build_defense("off"))
    specs = [
        AttackRunSpec(
            repeat_idx=0,
            target_id=target,
            channel=channel,
            technique=technique,
            goal=goal,
            attacker_mode=block.attacker_mode or "blind",
            defense_config=snapshot,
            carrier_task_id=cid,
            payload_id=pid,
        )
        for (channel, technique, goal), pid, cid in units
        for target in targets
    ]
    random.Random(f"{seed}:pilot:order").shuffle(specs)
    return specs


def done_specs(engine: Engine, batch_id: str) -> set[AttackRunSpec]:
    """Đơn vị đã có trong store (kể cả `parse_error`) — không chạy lại. Dựng lại `AttackRunSpec` từ
    cột `runs` để so khớp với kế hoạch."""
    from obs.trace import Run

    with Session(engine) as s:
        rows = s.exec(
            select(
                Run.repeat_idx,
                Run.target_id,
                Run.channel,
                Run.technique,
                Run.goal,
                Run.attacker_mode,
                Run.defense_config,
                Run.carrier_task_id,
                Run.payload_id,
            ).where(Run.batch_id == batch_id, Run.run_kind == "attack")
        ).all()
    return {AttackRunSpec(*row) for row in rows}


# ---------------------------------------------------------------------------
# Hạ tầng một run
# ---------------------------------------------------------------------------


@dataclass
class RunContext:
    """Dùng chung cho mọi run của một lô."""

    engine: Engine
    batch_id: str
    env_hash: str
    harness_version: str
    models: Mapping[str, Any]  # target_id → ChatModel (LLMClient)
    tools: Any  # HarnessTools của eval.utility_baseline
    corpus_by_id: Mapping[str, dict[str, Any]]
    carriers_by_id: Mapping[str, dict[str, Any]]
    core_params: Mapping[str, int]
    kb_top_k: int
    system_prompt: Callable[[str], str] = build_system_prompt
    # Hook tiêm — mặc định injector thật; test nối Qdrant/model giả qua đây.
    inject_k1: Callable[..., Any] = injector_k1.inject_and_probe
    build_k2_layer: Callable[..., Any] = injector_k2.build_layer
    cleanup_k1: Callable[..., None] = injector_k1.cleanup
    # Ảnh chụp JSON → tầng phòng thủ (`build_defenses`). Thiếu thì chỉ chạy được preset `off`.
    defenses: Mapping[str, Any] = field(default_factory=dict)
    carrier_task_types: Mapping[str, str] = field(default_factory=carrier_task_types)


def _defense_for(spec: AttackRunSpec, ctx: RunContext) -> Any:
    defense = ctx.defenses.get(spec.defense_config)
    if defense is not None:
        return defense
    off = NoDefense()
    if spec.defense_config == snapshot_json(off):
        return off
    raise AttackRunnerError(
        f"không có tầng phòng thủ cho defense_config của spec — dựng ctx.defenses bằng "
        f"build_defenses(presets của khối): {spec.defense_config[:120]}"
    )


def run_one_attack(spec: AttackRunSpec, ctx: RunContext) -> str:
    """Chạy và chấm một run tấn công; trả `run_id`. Lỗi `RECOVERABLE` thành `parse_error` của run;
    lỗi khác cũng ghi `parse_error` nhưng lan ra để runner dừng lô."""
    payload = ctx.corpus_by_id[spec.payload_id]
    carrier = ctx.carriers_by_id[spec.carrier_task_id]
    model = ctx.models[spec.target_id]
    defense = _defense_for(spec, ctx)
    if spec.carrier_task_id not in ctx.carrier_task_types:
        raise AttackRunnerError(f"tác vụ chở {spec.carrier_task_id} không có task_type trong defenses.yaml")
    with seeded_run(db_tool=ctx.tools.db, http_tool=ctx.tools.http) as seeded:
        # Dọn trạng thái run trước — trước khi tiêm payload của run này.
        ctx.tools.mail.clear_mailbox()
        ctx.tools.tickets.clear_tickets()
        ctx.tools.registry.reset_descriptions()

        injected = None
        if spec.channel == "K1":
            injected = ctx.inject_k1(payload, carrier, seeded.run_id, k=ctx.kb_top_k)
            tool_layer: Any = ctx.tools.registry
            delivered = injected.delivered
        else:
            layer = ctx.build_k2_layer(
                ctx.tools.registry, payload, carrier, spec.channel, seeded.run_id
            )
            tool_layer = layer
            delivered = layer.result.delivered

        meta = RunMeta(
            run_kind="attack",
            target_id=spec.target_id,
            model_id=model.model,
            batch_id=ctx.batch_id,
            harness_version=ctx.harness_version,
            env_hash=ctx.env_hash,
            defense_config=defense.config_snapshot(),
            carrier_task_id=spec.carrier_task_id,
            payload_id=spec.payload_id,
            technique=spec.technique,
            goal=spec.goal,
            channel=spec.channel,
            attacker_mode=spec.attacker_mode,
            lang=payload.get("lang"),
            obfuscation=",".join(payload.get("obfuscation") or []) or None,
            run_canaries=seeded.run_canaries,
            repeat_idx=spec.repeat_idx,
            run_id=seeded.run_id,
        )
        session = SessionState(
            run_id=seeded.run_id,
            task_type=ctx.carrier_task_types[spec.carrier_task_id],
            run_canaries=tuple(seeded.run_canaries),
            carrier_task_id=spec.carrier_task_id,
        )
        core = CoreA(
            model=model,
            tools=tool_layer,
            defense=defense,
            system_prompt=ctx.system_prompt(seeded.canaries.sysprompt),
            **ctx.core_params,
        )
        try:
            with TraceRecorder(ctx.engine, meta) as rec:
                rec.run.delivered = delivered
                core.run(carrier["user_query_vi"], session=session, recorder=rec)
                score(
                    rec,
                    ScoreContext(
                        runtime=carrier_runtime(carrier),
                        activation_check=payload.get("activation_check"),
                    ),
                )
        except Exception as e:  # noqa: BLE001 — phân loại rồi quyết dừng lô hay không
            if not isinstance(e, RECOVERABLE):
                raise
        finally:
            if spec.channel == "K1":
                ctx.cleanup_k1(seeded.run_id)
            if isinstance(defense, DefensePipeline):
                defense.end_run(seeded.run_id)
    return seeded.run_id


# ---------------------------------------------------------------------------
# Xuất
# ---------------------------------------------------------------------------


def export_runs_csv(engine: Engine, batch_id: str, out_path: Path) -> Path:
    """Xuất bảng `runs` của lô ra CSV (nguồn số của khối). Bảng tổng hợp/chỉ số ở bước phân tích."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df = export_runs(engine, batch_id=batch_id)
    df.to_csv(out_path, index=False)
    return out_path
