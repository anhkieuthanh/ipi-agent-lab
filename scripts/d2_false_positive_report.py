"""Báo cáo dương tính giả của D2 trên nhóm U5 — STT-52 (defense_spec.md §4.6).

PHÉP ĐO TĨNH. Chạy D2 (`sanitize_input`, source=kb_chunk, enabled=True) trực tiếp lên các tài liệu
corpus mà nhóm U5 truy hồi, rồi với mỗi câu U5 xét: từ khóa bắt buộc (`expected_answer.
must_include_keywords`) còn sống sót trong văn bản đã làm sạch không. Một từ khóa bị bước 5 (khối
mã hóa) hoặc bước 6 (mệnh lệnh) lược đi là dấu hiệu D2 sẽ làm câu đó đổi từ ĐÚNG sang SAI.

ĐÂY LÀ PROXY TĨNH, KHÔNG phải số flip end-to-end. Số flip thật (chạy agent với D2 bật vs tắt rồi
chấm bằng judge) cần pipeline STT-55 + model đích + bộ chấm, đo ở cổng ma trận (STT-71/72). Báo cáo
này ghi rõ ràng buộc đó để người đọc không nhầm proxy với phép đo end-to-end.

Không gọi mạng, không gọi LLM. Ghi Markdown vào đường dẫn ở `defenses.yaml` khóa
`defenses.d2_input_sanitizer.false_positive_report`.

    uv run python scripts/d2_false_positive_report.py
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from defense import d2_input_sanitizer as d2  # noqa: E402

CORPUS_DIR = ROOT / "src" / "rag" / "corpus"
BENIGN = ROOT / "data" / "benign_queries.json"


def _u5_queries() -> list[dict]:
    doc = json.loads(BENIGN.read_text(encoding="utf-8"))
    return [q for q in doc["queries"] if q.get("group") == "U5"]


def _step_counts(hits) -> dict[str, int]:
    out: dict[str, int] = {}
    for h in hits:
        out[h.rule] = out.get(h.rule, 0) + 1
    return out


def main() -> int:
    cfg = d2.load_d2_config()
    report_rel = cfg["false_positive_report"]
    report_path = ROOT / report_rel

    queries = _u5_queries()

    # D2 chạy một lần cho mỗi tài liệu U5 (nhiều câu chia nhau một tài liệu).
    docs = sorted({d for q in queries for d in q["kb_docs"]})
    raw_text: dict[str, str] = {}
    sanitized: dict[str, str] = {}
    doc_hits: dict[str, dict[str, int]] = {}
    for name in docs:
        raw = (CORPUS_DIR / name).read_text(encoding="utf-8")
        res = d2.sanitize_input(raw, source="kb_chunk", enabled=True, config=cfg)
        raw_text[name] = raw
        sanitized[name] = res.text
        doc_hits[name] = _step_counts(res.hits)

    rows = []
    flips = 0
    for q in queries:
        before = "\n".join(raw_text[d] for d in q["kb_docs"])
        after = "\n".join(sanitized[d] for d in q["kb_docs"])
        # Chỉ tính từ khóa CÓ trong bản gốc mà D2 lược mất — đó mới là dương tính giả do D2.
        # Từ khóa vốn không có trong tài liệu (khác cách diễn đạt) không phải lỗi của D2.
        removed = [kw for kw in q["expected_answer"]["must_include_keywords"] if kw in before and kw not in after]
        at_risk = bool(removed)
        flips += at_risk
        rows.append((q["id"], q["kb_docs"], removed, at_risk))

    lines: list[str] = []
    lines.append("# D2 Input Sanitizer — báo cáo dương tính giả trên U5 (STT-52)")
    lines.append("")
    lines.append(
        "> Tài liệu do AI (Claude) sinh tự động từ `scripts/d2_false_positive_report.py`. "
        "Chạy lại để cập nhật; không sửa tay."
    )
    lines.append("")
    lines.append(f"Sinh ngày: {date.today().isoformat()}")
    lines.append("")
    lines.append("## Phương pháp (đọc trước khi dùng số)")
    lines.append("")
    lines.append(
        "Phép đo **tĩnh**: chạy D2 (`sanitize_input`, nguồn `kb_chunk`, bật) lên từng tài liệu "
        "corpus mà U5 truy hồi, rồi xét mỗi từ khóa bắt buộc của câu còn sống sót trong văn bản đã "
        "làm sạch không. Từ khóa bị lược ⇒ câu **có nguy cơ** đổi đúng→sai."
    )
    lines.append("")
    lines.append(
        "**Không phải số flip end-to-end.** Số flip thật (agent chạy D2 bật vs tắt, chấm bằng judge) "
        "cần pipeline STT-55 + model đích + bộ chấm; đo ở cổng ma trận STT-71/72. Dùng báo cáo này để "
        "thấy *cơ chế* dương tính giả và *tài liệu* nào rủi ro, không thay cho phép đo end-to-end."
    )
    lines.append("")
    lines.append("## Tác động của D2 lên từng tài liệu U5 (số hit theo bước)")
    lines.append("")
    lines.append("| Tài liệu | S1 NFKC | S2 ẩn | S3 cmt | S4 CSS | S5 mã hóa | S6 mệnh lệnh |")
    lines.append("|---|:--:|:--:|:--:|:--:|:--:|:--:|")
    for name in docs:
        c = doc_hits[name]
        lines.append(
            f"| `{name}` | {c.get('S1',0)} | {c.get('S2',0)} | {c.get('S3',0)} | "
            f"{c.get('S4',0)} | {c.get('S5',0)} | {c.get('S6',0)} |"
        )
    lines.append("")
    lines.append("## Nguy cơ đổi đúng→sai theo câu U5")
    lines.append("")
    lines.append("| Câu | Tài liệu | Từ khóa bị lược | Nguy cơ |")
    lines.append("|---|---|---|:--:|")
    for qid, kbdocs, missing, at_risk in rows:
        kb = ", ".join(f"`{d}`" for d in kbdocs)
        miss = ", ".join(f"`{m}`" for m in missing) if missing else "—"
        lines.append(f"| {qid} | {kb} | {miss} | {'⚠️ CÓ' if at_risk else 'không'} |")
    lines.append("")
    lines.append("## Tổng hợp")
    lines.append("")
    lines.append(f"- Số câu U5: **{len(queries)}**")
    lines.append(f"- Số câu có từ khóa bắt buộc bị D2 lược (nguy cơ flip): **{flips}**")
    lines.append(
        f"- Bước gây lược nhiều nhất: "
        f"S5={sum(c.get('S5',0) for c in doc_hits.values())} khối mã hóa, "
        f"S6={sum(c.get('S6',0) for c in doc_hits.values())} câu mệnh lệnh."
    )
    lines.append("")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Đã ghi {report_rel} — {flips}/{len(queries)} câu U5 có nguy cơ flip.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
