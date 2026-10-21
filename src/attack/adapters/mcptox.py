"""mcptox.py — adapter MCPTox → lược đồ nhập của lab (STT-39), HƯỚNG A.

Nguồn: snapshot structural-only `data/upstream/mcptox/payload_index.csv` (xem MANIFEST.txt),
lọc từ `pure_tool.json` của `zhiqiangwang4/MCPTox-Benchmark@f85189f9` còn các cột cấu trúc
`[id, server_name, tool_name, paradigm, security_risk]`. Adapter KHÔNG import gói MCPTox, KHÔNG
gọi mạng, KHÔNG chạm MCP server nào (quy tắc cứng #7): cùng snapshot thì cùng đầu ra.

HƯỚNG A (TA chốt 2026-10-21): repo MCPTox KHÔNG có giấy phép
(evidence/mcptox/inventory.json: license_file_present=false). Vì vậy adapter CHỈ trích CẤU TRÚC;
mỗi bản ghi nhập là `original` — khung (template) và goal_text do lab tự soạn, KHÔNG chép văn bản
MCPTox. `source = {kind: original, ref: "mcptox:<id>"}`, KHÔNG có license. Khác với adapter
AgentDojo (`verbatim`, có MIT): ở đó template trích nguyên văn từ payload, ở đây template là khung
trung lập của lab tra theo kỹ thuật.

Mỗi dòng snapshot → một `ImportedRecord`:

- `technique`, `variant`, `rationale`: tra `paradigms[<paradigm>]` trong config.
- `goal`: Template-3 bị ép `G2` (TA chốt tách "sửa tham số" theo mục tiêu); paradigm khác tra
  `security_risk_to_goal[<security_risk>]`. `goal_kind = DROP` (security_risk "Other") → loại,
  đếm vào `dropped`.
- `template`: khung trung lập `templates[<technique>][<variant>]` của config (bất biến 1 và 2).
- `goal_text`: mô tả lớp hành động độc do lab soạn theo `goal_kind` — không chép MCPTox.
- `source`: `{kind: original, ref: "mcptox:<id>"}`; `semantic_coupling = False` do khung và
  goal_text là văn bản lab trung lập, không mang thực thể của MCPTox.

`to_lab_payload()` ở STT-40 viết lại `goal_binding`/`activation_check` cho tool của lab; vì khung
đã là `original` nên lúc đó `source.kind` giữ `original` (không nâng lên `adapted`).

Dùng:

    uv run python -m attack.adapters.mcptox --out data/payloads_imported/mcptox.json
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from attack.adapters.base import (
    DEFAULT_CONFIG_PATH,
    ROOT,
    AdapterError,
    ImportedRecord,
    check_keys,
    load_section,
    write_records,
)

BENCHMARK = "mcptox"
INSTRUCTION = "{INSTRUCTION}"

_SECTION_KEYS = {
    "snapshot_dir", "index_file", "commit", "benchmark_version", "channels", "lang", "vector",
    "paradigms", "force_goal", "security_risk_to_goal", "templates", "goal_text_by_kind",
    "acceptance",
}
_PARADIGM_KEYS = {"technique", "variant", "rationale"}
_INDEX_COLUMNS = {"id", "server_name", "tool_name", "paradigm", "security_risk"}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise AdapterError(f"{path}: snapshot rỗng")
    missing = _INDEX_COLUMNS - set(rows[0])
    if missing:
        raise AdapterError(f"{path}: thiếu cột {sorted(missing)}")
    return rows


def _resolve_template(cfg: dict, technique: str, variant: str) -> str:
    """Khung trung lập theo (kỹ thuật, biến thể); tự kiểm đúng một {INSTRUCTION} (bất biến 1)."""
    by_variant = cfg["templates"].get(technique)
    if not by_variant or variant not in by_variant:
        raise AdapterError(f"templates thiếu khung cho {technique}/{variant}")
    template = by_variant[variant]
    if template.count(INSTRUCTION) != 1:
        raise AdapterError(f"khung {technique}/{variant} phải chứa đúng một {INSTRUCTION}")
    return template


def import_mcptox(config_path: Path | str = DEFAULT_CONFIG_PATH) -> list[ImportedRecord]:
    """Đọc snapshot, trả bản ghi nhập (đã loại security_risk 'Other'), sắp theo id."""
    cfg = load_section(BENCHMARK, config_path)
    check_keys(cfg, _SECTION_KEYS, BENCHMARK)
    for name, spec in cfg["paradigms"].items():
        check_keys(spec, _PARADIGM_KEYS, f"{BENCHMARK}.paradigms.{name}")

    snap = ROOT / cfg["snapshot_dir"]
    rows = _read_csv(snap / cfg["index_file"])
    channels = tuple(cfg["channels"])
    lang = cfg["lang"]
    vector = cfg["vector"]

    records: list[ImportedRecord] = []
    for row in rows:
        paradigm = row["paradigm"]
        risk = row["security_risk"]
        spec = cfg["paradigms"].get(paradigm)
        if spec is None:
            raise AdapterError(f"paradigm '{paradigm}' chưa gán kỹ thuật trong config")

        # Template-3 bị ép mục tiêu; paradigm khác lấy theo security_risk.
        forced = cfg["force_goal"].get(paradigm)
        if forced is not None:
            goal, goal_kind = forced["goal"], forced["goal_kind"]
        else:
            g = cfg["security_risk_to_goal"].get(risk)
            if g is None:
                raise AdapterError(f"security_risk '{risk}' chưa gán mục tiêu trong config")
            goal, goal_kind = g["goal"], g["goal_kind"]
        if goal_kind == "DROP":
            continue  # security_risk không ánh xạ được sang mô hình đe dọa của lab

        goal_text = cfg["goal_text_by_kind"].get(goal_kind)
        if goal_text is None:
            raise AdapterError(f"goal_text_by_kind thiếu '{goal_kind}'")

        technique, variant = spec["technique"], spec["variant"]
        template = _resolve_template(cfg, technique, variant)

        records.append(ImportedRecord(
            id=f"{BENCHMARK}:{row['id']}",
            benchmark=BENCHMARK,
            suite=row["server_name"],
            injection_task=row["tool_name"],
            attack=paradigm,
            vector=vector,
            technique=technique,
            variant=variant,
            rationale=spec["rationale"],
            template=template,
            goal=goal,
            goal_text=goal_text,
            payload=template.replace(INSTRUCTION, goal_text),
            channels=channels,
            lang=lang,
            source={"kind": "original", "ref": f"mcptox:{row['id']}"},
            semantic_coupling=False,  # khung + goal_text là văn bản lab trung lập (hướng A)
            coupling_evidence=(),
            grader_unverified=False,  # nhãn MCPTox là của model họ, không phải ground truth của lab
        ))

    ids = [r.id for r in records]
    if len(set(ids)) != len(ids):
        raise AdapterError("snapshot có id trùng")

    min_k2a = cfg["acceptance"]["min_k2a_records"]
    n_k2a = sum("K2a" in r.channels for r in records)
    if n_k2a < min_k2a:
        raise AdapterError(f"chỉ {n_k2a} bản ghi K2a < ngưỡng {min_k2a} (STT-39)")

    return sorted(records, key=lambda r: (r.suite, r.injection_task, r.id))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    ap.add_argument("--out", default=str(ROOT / "data" / "payloads_imported" / "mcptox.json"))
    args = ap.parse_args(argv)

    records = import_mcptox(args.config)
    write_records(records, args.out)

    def count(attr: str) -> str:
        values = sorted({getattr(r, attr) for r in records})
        return " ".join(f"{v}={sum(getattr(r, attr) == v for r in records)}" for v in values)

    print(f"{len(records)} bản ghi → {args.out}")
    print(f"  kỹ thuật:  {count('technique')}")
    print(f"  mục tiêu:  {count('goal')}")
    print(f"  paradigm:  {count('attack')}")
    print(f"  kênh K2a:  {sum('K2a' in r.channels for r in records)}")


if __name__ == "__main__":
    main()
