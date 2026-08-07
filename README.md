# ipi-agent-lab

Nghiên cứu và xây dựng hệ thống đánh giá, phòng chống tấn công tiêm nhiễm gián tiếp
(Indirect Prompt Injection — IPI) cho agent dùng RAG + MCP tool-calling.

## Cấu trúc thư mục

```
├── src/
│   ├── attack/payloads/   # schema payload (technique × goal_binding), W1-07
│   ├── obs/                # trace schema, DDL SQLite (runs/steps), W1-09
│   └── defense/             # 4 cơ chế phòng thủ D1–D4, W1-08
├── data/                    # carrier_tasks.json, payloads_sample.json
├── config/                  # defenses.yaml
├── docs/                    # related_work, threat_model, taxonomy, metrics...
├── tests/                   # test tích hợp
└── scripts/                 # tiện ích chạy thử nghiệm
```

## Cài đặt

```bash
uv sync --all-groups
```

## Kiểm thử

```bash
uv run pytest -v
uv run ruff check .
```

## Bộ đo (benchmark) — KHÓA tại `v-bench-1.0`

- 60 câu hỏi lành tính: `data/benign_queries.json` (nhóm U1–U5, `false_positive_gate`).
- 6 tác vụ chở (carrier tasks): `data/carrier_tasks.json` (CT-01..CT-06).

Hai file này **KHÔNG được sửa sau tuần 2** (mốc git tag `v-bench-1.0`).
Mọi thay đổi sau mốc này phải ghi vào khối `changelog` trong chính file JSON
(field `version`, `date`, `reason`, `changes`) kèm lý do rõ ràng — xem ví dụ
trong `carrier_tasks.json`. Đây là điều kiện cổng M1, chống rủi ro R4
(bộ đo trôi giữa chừng làm số liệu không so sánh được).

## Trạng thái

Dự án đang trong Tuần 1 (thiết kế): threat model, taxonomy K1–K5, schema payload,
spec phòng thủ, trace schema, công thức đo (ASR, DSR, USR, FRR, TCP, ARR).
Xem `TASKS_V3.md` / `KE_HOACH_V3.md` (ở thư mục thesis gốc) cho kế hoạch chi tiết 8 tuần.

## Giấy phép

MIT — xem [LICENSE](LICENSE).
