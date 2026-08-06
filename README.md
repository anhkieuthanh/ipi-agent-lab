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

## Trạng thái

Dự án đang trong Tuần 1 (thiết kế): threat model, taxonomy K1–K5, schema payload,
spec phòng thủ, trace schema, công thức đo (ASR, DSR, USR, FRR, TCP, ARR).
Xem `TASKS_V3.md` / `KE_HOACH_V3.md` (ở thư mục thesis gốc) cho kế hoạch chi tiết 8 tuần.

## Giấy phép

MIT — xem [LICENSE](LICENSE).
