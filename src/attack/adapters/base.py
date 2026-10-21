"""base.py — lược đồ nhập dùng chung cho adapter benchmark ngoài (STT-38, STT-39).

Adapter đọc snapshot benchmark trong `data/upstream/<benchmark>/` và trả `ImportedRecord`: bản ghi
trung thực với nguồn (khung nguyên văn, goal nguyên văn, nguồn gốc, cờ coupling), CHƯA gắn tool
của lab. Bước chuyển sang payload hợp lệ theo `attack.payloads.schema` cần `goal_binding` viết lại
cho năm tool của lab, làm ở STT-40 qua hàm `to_lab_payload` của từng adapter.

Hai lớp tách nhau vì goal benchmark gắn với tool của suite gốc (gửi email cho người lạ, chuyển tiền
tới IBAN…), validator payload lại đòi tool của lab. Gộp làm một thì hoặc bịa `goal_binding`, hoặc
nới validator.

Mọi quyết định gán nhãn đọc từ `config/attack_sources.yaml`, không hard-code ở đây.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = ROOT / "config" / "attack_sources.yaml"
INSTRUCTION = "{INSTRUCTION}"


class AdapterError(ValueError):
    """Snapshot hoặc config không khớp nhau — adapter dừng, không đoán."""


@dataclass(frozen=True)
class ImportedRecord:
    """Một payload benchmark ngoài trong lược đồ nhập của lab."""

    id: str                         # "<benchmark>:<suite>/<task>/<attack>", ổn định giữa các lần chạy
    benchmark: str
    suite: str
    injection_task: str
    attack: str
    vector: str                     # chỗ tiêm của benchmark gốc, chỉ để tham chiếu
    technique: str                  # T1..T8 theo cây quyết định (config)
    variant: str
    rationale: str
    template: str                   # khung nguyên văn, goal thay bằng {INSTRUCTION}
    goal: str                       # G1..G3 theo bảng TA duyệt (config)
    goal_text: str                  # goal nguyên văn của benchmark
    payload: str                    # payload nguyên văn = template với goal_text điền vào
    channels: tuple[str, ...]
    lang: str
    source: dict[str, str]
    semantic_coupling: bool
    coupling_evidence: tuple[str, ...] = field(default_factory=tuple)
    grader_unverified: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["channels"] = list(self.channels)
        d["coupling_evidence"] = list(self.coupling_evidence)
        return d


def load_section(name: str, path: Path | str = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if name not in data:
        raise AdapterError(f"{path}: thiếu khối '{name}'")
    return data[name]


def check_keys(block: dict[str, Any], allowed: set[str], where: str) -> None:
    """Tên khóa lạ bị từ chối — không có tham số khai ra mà không code nào đọc."""
    extra = set(block) - allowed
    if extra:
        raise AdapterError(f"{where}: khóa lạ {sorted(extra)}")


def extract_template(payload: str, goal_text: str) -> str:
    """Thay goal trong payload bằng {INSTRUCTION}; goal phải xuất hiện đúng một lần."""
    n = payload.count(goal_text)
    if n != 1:
        raise AdapterError(f"goal xuất hiện {n} lần trong payload, cần đúng 1: {goal_text[:60]!r}")
    return payload.replace(goal_text, INSTRUCTION)


def find_coupling(text: str, rules: dict[str, Any]) -> tuple[str, ...]:
    """Chuỗi trong `text` khớp luật coupling (regex hoặc thực thể), theo thứ tự xuất hiện, không trùng."""
    hits: list[tuple[int, str]] = []
    for pattern in rules.get("patterns", {}).values():
        hits += [(m.start(), m.group(0)) for m in re.finditer(pattern, text)]
    for entity in rules.get("entities", []):
        hits += [(m.start(), m.group(0)) for m in re.finditer(rf"\b{re.escape(entity)}\b", text)]
    seen: list[str] = []
    for _, s in sorted(hits):
        if s not in seen:
            seen.append(s)
    return tuple(seen)


def write_records(records: list[ImportedRecord], out: Path | str) -> None:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps([r.to_dict() for r in records], ensure_ascii=False, indent=1)
    out.write_text(text + "\n", encoding="utf-8")
