"""agentdojo.py — adapter AgentDojo → lược đồ nhập của lab (STT-38).

Nguồn: snapshot `data/upstream/agentdojo/` (xem MANIFEST.txt), sinh bằng chạy thật AgentDojo
`ethz-spylab/agentdojo@089ed468` v1.2.2 với `GroundTruthPipeline`, không gọi LLM. Adapter không
import gói `agentdojo`, không gọi mạng: cùng snapshot thì cùng đầu ra.

Mỗi dòng `payload_samples_all.csv` là một cặp (attack, injection task) → một `ImportedRecord`:

- `template`: payload với goal thay bằng `{INSTRUCTION}`. Tự kiểm mỗi attack ra ĐÚNG MỘT template
  trên mọi injection task; lệch là snapshot hỏng hoặc attack có tham số theo task → dừng.
- `technique`, `goal`: tra `config/attack_sources.yaml`; attack hay task không có trong bảng → dừng.
- `semantic_coupling`: goal khớp luật coupling của config; chuỗi khớp ghi vào `coupling_evidence`.
- `grader_unverified`: injection task không giải được bằng ground truth trên user task nào
  (`gt_security_any_user_task = False`, FIT_GAP mục 4 phát hiện 2).
- `source`: `kind = verbatim` (khung và goal nguyên văn), `ref` trỏ tới file attack ở commit đã
  pin, `license = MIT`.

`to_lab_payload()` chuyển một bản ghi sang payload theo `attack.payloads.schema` khi đã có
`goal_binding` viết lại cho tool của lab (STT-40); lúc đó `source.kind = adapted`.

Dùng:

    uv run python -m attack.adapters.agentdojo --out data/payloads_imported/agentdojo.json
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

from attack.adapters.base import (
    DEFAULT_CONFIG_PATH,
    ROOT,
    AdapterError,
    ImportedRecord,
    check_keys,
    extract_template,
    find_coupling,
    load_section,
    write_records,
)

BENCHMARK = "agentdojo"
_SECTION_KEYS = {
    "snapshot_dir", "payload_file", "ground_truth_file", "commit", "benchmark_version",
    "license", "lang", "channels", "attacks", "goals", "coupling",
}
_ATTACK_KEYS = {"technique", "variant", "source_path", "rationale", "origin"}


def _task_no(task: str) -> int:
    return int(task.rsplit("_", 1)[-1])


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def import_agentdojo(config_path: Path | str = DEFAULT_CONFIG_PATH) -> list[ImportedRecord]:
    """Đọc snapshot, trả bản ghi sắp theo (suite, số task, attack)."""
    cfg = load_section(BENCHMARK, config_path)
    check_keys(cfg, _SECTION_KEYS, BENCHMARK)
    for name, spec in cfg["attacks"].items():
        check_keys(spec, _ATTACK_KEYS, f"{BENCHMARK}.attacks.{name}")

    snap = ROOT / cfg["snapshot_dir"]
    rows = _read_csv(snap / cfg["payload_file"])
    gt = {(r["suite"], r["injection_task"]): r for r in _read_csv(snap / cfg["ground_truth_file"])}

    records: list[ImportedRecord] = []
    templates: dict[str, str] = {}
    for row in rows:
        suite, task, attack = row["suite"], row["injection_task"], row["attack"]
        key = (suite, task)
        if key not in gt:
            raise AdapterError(f"{suite}/{task} không có trong file ground truth")
        spec = cfg["attacks"].get(attack)
        if spec is None:
            raise AdapterError(f"attack '{attack}' chưa gán kỹ thuật trong config")
        goal = cfg["goals"].get(suite, {}).get(task)
        if goal is None:
            raise AdapterError(f"{suite}/{task} chưa gán mục tiêu trong config")

        goal_text = gt[key]["goal"]
        template = extract_template(row["payload"], goal_text)
        if templates.setdefault(attack, template) != template:
            raise AdapterError(f"attack '{attack}' ra hơn một template (lệch ở {suite}/{task})")

        evidence = find_coupling(goal_text, cfg["coupling"])
        records.append(ImportedRecord(
            id=f"{BENCHMARK}:{suite}/{task}/{attack}",
            benchmark=BENCHMARK,
            suite=suite,
            injection_task=task,
            attack=attack,
            vector=row["vector"],
            technique=spec["technique"],
            variant=spec["variant"],
            rationale=spec["rationale"],
            template=template,
            goal=goal,
            goal_text=goal_text,
            payload=row["payload"],
            channels=tuple(cfg["channels"]),
            lang=cfg["lang"],
            source={
                "kind": "verbatim",
                "ref": f"agentdojo@{cfg['commit']}:{spec['source_path']} "
                       f"({cfg['benchmark_version']}, {suite}/{task})",
                "license": cfg["license"],
            },
            semantic_coupling=bool(evidence),
            coupling_evidence=evidence,
            grader_unverified=gt[key]["gt_security_any_user_task"] != "True",
        ))

    ids = [r.id for r in records]
    if len(set(ids)) != len(ids):
        raise AdapterError("snapshot có cặp (suite, task, attack) trùng")
    return sorted(records, key=lambda r: (r.suite, _task_no(r.injection_task), r.attack))


def to_lab_payload(
    rec: ImportedRecord,
    *,
    number: int,
    goal_binding: dict[str, Any],
    activation_check: dict[str, Any],
    adaptation_note: str,
) -> dict[str, Any]:
    """Payload theo `attack.payloads.schema`; `goal_binding` đã viết lại cho tool của lab.

    Giữ khung (template) nguyên văn, thay goal nguyên văn bằng chỉ thị của lab nên `kind = adapted`.
    Cờ `semantic_coupling` lấy theo bản ghi gốc: người viết lại goal_binding phải tự hạ cờ khi đã
    bỏ hết thực thể suite gốc, không để adapter đoán.
    """
    return {
        "id": f"P-{rec.technique}-{rec.goal}-EN-{number:03d}",
        "technique": {
            "code": rec.technique,
            "variant": rec.variant,
            "template": rec.template,
            "rationale": rec.rationale,
        },
        "goal": rec.goal,
        "goal_binding": goal_binding,
        "channels": list(rec.channels),
        "lang": rec.lang,
        "source": {**rec.source, "kind": "adapted", "adaptation_note": adaptation_note},
        "obfuscation": ["none"],
        "semantic_coupling": rec.semantic_coupling,
        "grader_unverified": rec.grader_unverified,
        "activation_check": activation_check,
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    ap.add_argument("--out", default=str(ROOT / "data" / "payloads_imported" / "agentdojo.json"))
    args = ap.parse_args(argv)

    records = import_agentdojo(args.config)
    write_records(records, args.out)

    def count(attr: str) -> str:
        values = sorted({getattr(r, attr) for r in records})
        return " ".join(f"{v}={sum(getattr(r, attr) == v for r in records)}" for v in values)

    print(f"{len(records)} bản ghi → {args.out}")
    print(f"  kỹ thuật: {count('technique')}")
    print(f"  mục tiêu: {count('goal')}")
    print(f"  suite:    {count('suite')}")
    print(f"  semantic_coupling: {sum(r.semantic_coupling for r in records)}")
    print(f"  grader_unverified: {sum(r.grader_unverified for r in records)}")


if __name__ == "__main__":
    main()
