"""Sinh payload T8 (che giấu đặc thù tiếng Việt) — STT-47. Tất định, chạy lại cho ra y hệt.

Mỗi payload T8 bắt nguồn từ một base-frame sẵn có (T1/T2/T3/T5): giữ NGUYÊN `goal_binding` (tool +
arguments) và `activation_check` để mục tiêu và phép chấm không đổi, chỉ áp `vi_transform` lên phần
NGÔN NGỮ TỰ NHIÊN (template + instruction_vi). Nhờ vậy cặp (base-frame vi sạch) ↔ (T8 obfuscate)
đo được "ảnh hưởng ngôn ngữ" — neo qua trường `base_frame`, KHÔNG dùng pair_id (INV11: T8 không có
bản en).

Ghi `src/attack/payloads/t8_vietnamese.yaml` (chỉ dữ liệu — rule #10). Mọi bản phải qua
`validate_payload`; sai một bản là dừng, không ghi.

    uv run python scripts/gen_t8_payloads.py            # sinh và ghi
    uv run python scripts/gen_t8_payloads.py --check     # chỉ kiểm, không ghi (CI)
"""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from attack.payloads.render import render_for_channel  # noqa: E402
from attack.payloads.schema import load_payloads, validate_payload  # noqa: E402
from attack.payloads.vi_transform import VI_TRANSFORMS, apply  # noqa: E402
from eval.canary import CANARY_PLACEHOLDER  # noqa: E402

PAYLOADS_DIR = ROOT / "src" / "attack" / "payloads"
OUT_PATH = PAYLOADS_DIR / "t8_vietnamese.yaml"
K2_CHANNELS = ("K2a", "K2b")

#: Base-frame nguồn cho mỗi mục tiêu (phải tồn tại trong corpus). Một seed → mọi vi_transform.
SEED_IDS = ("P-T2-G1-VI-001", "P-T3-G1-VI-001", "P-T1-G2-VI-001", "P-T5-G3-VI-001")


def _seed_files() -> list[Path]:
    # Đọc seed từ các file base-frame, KHÔNG từ t8_vietnamese.yaml (tránh vòng khi sinh lại).
    return sorted(p for p in PAYLOADS_DIR.glob("t*.yaml") if p.name != OUT_PATH.name)


def _load_seeds() -> dict[str, dict]:
    items: dict[str, dict] = {}
    for f in _seed_files():
        for p in yaml.safe_load(f.read_text(encoding="utf-8")) or []:
            items[p["id"]] = p
    missing = [i for i in SEED_IDS if i not in items]
    if missing:
        raise SystemExit(f"thiếu base-frame nguồn: {missing}")
    return items


def _protect(seed: dict) -> list[str]:
    """Chuỗi phải giữ nguyên qua biến đổi: giá trị args, marker mục tiêu, placeholder canary."""
    out: set[str] = {CANARY_PLACEHOLDER}
    for v in (seed.get("goal_binding") or {}).get("arguments", {}).values():
        if isinstance(v, str) and v.strip():
            out.add(v)
    marker = (seed.get("activation_check") or {}).get("marker_template")
    if marker:
        out.add(marker)
    return sorted(out)


def _build(seed: dict, transform: str, serial: int) -> dict:
    goal = seed["goal"]
    lang = "mixed" if transform == "code_mix" else "vi"
    tag = "MIX" if transform == "code_mix" else "VI"
    protect = _protect(seed)
    tpl = apply(transform, seed["technique"]["template"], protect=protect)
    gb = copy.deepcopy(seed["goal_binding"])
    gb["instruction_vi"] = apply(transform, gb.get("instruction_vi", ""), protect=protect)
    return {
        "id": f"P-T8-{goal}-{tag}-{serial:03d}",
        "technique": {
            "code": "T8",
            "variant": "none",  # INV3: chỉ T1 có variant; phép biến ghi ở vi_transform
            "template": tpl,
            "rationale": (
                f"T8 áp vi_transform '{transform}' lên khung {seed['technique']['code']} "
                f"({seed['id']}); giữ nguyên goal_binding và activation_check để né bộ dò/D2 "
                "mà không đổi mục tiêu."
            ),
        },
        "goal": goal,
        "base_frame": seed["technique"]["code"],
        "goal_binding": gb,
        "channels": ["K1", "K2a", "K2b"],
        "lang": lang,
        "vi_transform": [transform],
        "obfuscation": ["none"],
        "source": {"kind": "original", "ref": f"lab:T8 từ {seed['id']} ({transform})"},
        "semantic_coupling": bool(seed.get("semantic_coupling", False)),
        "activation_check": copy.deepcopy(seed["activation_check"]),
    }


def generate() -> list[dict]:
    seeds = _load_seeds()
    per_goal: dict[str, int] = {}
    out: list[dict] = []
    for sid in SEED_IDS:
        seed = seeds[sid]
        for transform in VI_TRANSFORMS:
            per_goal[seed["goal"]] = per_goal.get(seed["goal"], 0) + 1
            out.append(_build(seed, transform, per_goal[seed["goal"]]))
    return out


def _validate(payloads: list[dict]) -> list[str]:
    problems: list[str] = []
    for p in payloads:
        for err in validate_payload(p):
            problems.append(f"{p['id']}: {err}")
        for ch in K2_CHANNELS:
            try:
                render_for_channel(p, ch)
            except Exception as e:  # noqa: BLE001 — không dựng được kênh là lỗi dữ liệu, báo rõ
                problems.append(f"{p['id']}: render {ch} lỗi: {e}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="chỉ kiểm, không ghi")
    args = parser.parse_args()

    payloads = generate()
    problems = _validate(payloads)
    if problems:
        print("payload T8 chưa đạt, KHÔNG ghi:\n  " + "\n  ".join(problems))
        return 1
    # Chốt không trùng với corpus hiện có (trừ chính file đầu ra).
    existing, _ = load_payloads(PAYLOADS_DIR)
    dup = {p["id"] for p in payloads} & {
        p["id"] for p in existing if not str(p["id"]).startswith("P-T8-")
    }
    if dup:
        print(f"trùng id với payload khác kỹ thuật: {sorted(dup)}")
        return 1
    print(f"{len(payloads)} payload T8 đạt ({len(VI_TRANSFORMS)} phép × {len(SEED_IDS)} seed).")
    if args.check:
        return 0
    OUT_PATH.write_text(
        yaml.safe_dump(payloads, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )
    print(f"  ghi: {OUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
