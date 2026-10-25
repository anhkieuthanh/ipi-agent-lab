# ipi-agent-lab

> README soạn với sự hỗ trợ của AI (Claude).

Hệ thống đánh giá và phòng chống tấn công tiêm nhiễm gián tiếp (Indirect Prompt Injection —
IPI) trên agent dùng RAG + MCP tool-calling.

## Cấu trúc thư mục

```
├── config/              # hợp đồng, viết trước src/: defenses.yaml · models.yaml · rag.yaml
├── data/                # benign_queries.json · carrier_tasks.json · customers.db (Faker vi_VN)
├── src/
│   ├── agent/           # lõi agent (STT-26)
│   ├── rag/             # ingest · embedder · retriever · corpus
│   ├── attack/payloads/ # schema + corpus payload T1–T8 (STT-20)
│   ├── defense/         # D1–D4 · pipeline
│   ├── eval/            # allowed_actions · scorer (STT-35) · bench hữu dụng (STT-37)
│   └── obs/             # trace store (STT-32) · canary (STT-33, STT-34)
├── dashboard/           # Streamlit: app.py + pages/
├── scripts/             # seed_db · gen_corpus_pdfs
└── tests/
```

## Cài đặt

```bash
uv sync --all-groups
cp .env.example .env   # rồi điền giá trị thật; không commit .env
```

## Hạ tầng lab

Năm service trong `docker-compose.yml`: `qdrant` (vector store) · `mailhog` (SMTP giả) ·
`canary-listener` (bồn chứa của `http_request`, `127.0.0.1:8099`, hit đọc qua `GET /hits?run=`) ·
`app` (dev container) · `dashboard` (Streamlit, cổng 8501).

```bash
make up          # dựng cả lab, chờ mọi service healthy
make dashboard   # chỉ dashboard — http://localhost:8501
make down
```

Các target khác: `reset` · `ps` · `logs` · `kb-build` · `kb-rebuild` ·
`kb-bench` · `kb-stats`.

## IPI Guard Console — giao diện chính

Console web (FastAPI + React) là giao diện chính: tổng quan ASR/DSR/USR/FRR và cổng nghiệm thu, lô
thực nghiệm, phân tích tấn công (bản đồ ASR), phân tích phòng thủ (đường đánh đổi Pareto), điều tra
run từng bước (payload và canary tô màu), phòng thí nghiệm tấn công trực tiếp, và cấu hình đã chốt.

```bash
make up             # hạ tầng lab: Qdrant, MailHog, canary listener
make console-build  # build giao diện vào web/dist (cần Node ≥ 20)
make console        # API + giao diện ở một cổng — http://localhost:8600
```

`make console` chỉ nghe `127.0.0.1` và từ chối mọi Host ngoài localhost (chặn DNS rebinding). Chỉ
ĐỌC trace store; lần ghi duy nhất là lượt demo trực tiếp ở trang "Phòng thí nghiệm" (bật khi
`DEMO_LIVE=1`, `make console` đã bật sẵn), đi đúng đường `run_one_attack` của lô thật và canh chi
phí như lô thực nghiệm. Run demo ghi `results/demo/` (không theo Git), không trộn với lô thực
nghiệm. Phát triển giao diện: `make console-dev` (Vite 5173 + API 8600).

Số liệu (ASR, DSR, USR, FRR, Wilson, tô màu bước) lấy từ cùng hàm mà scorer và dashboard dùng
(`dashboard/tracedata.py`, `src/eval/metrics.py`) — console không tính lại theo cách riêng. Lớp
API ở `src/console/`, giao diện ở `web/`.

### Demo trực tiếp (bản Streamlit cũ)

Dashboard Streamlit bốn trang vẫn còn cho đối chiếu: `make dashboard` (cổng 8501, chỉ xem) và
`make demo` (cổng 8502, có nút chạy). Chạy kịch bản từ dòng lệnh: `uv run python dashboard/demo.py --list`.

## Kiểm thử

```bash
uv run pytest -v        # test cần Qdrant tự bỏ qua nếu chưa `make up`
uv run ruff check .
```

## Bộ đo — đã khóa

`data/benign_queries.json` (60 câu U1–U5) và `data/carrier_tasks.json` (CT-01–CT-06)
không được sửa. Mọi thay đổi ghi ở `docs/06. Track/CHANGELOG_TAI_LIEU.md` của repo tài
liệu kèm lý do, không ghi trong chính file JSON.

## Giấy phép

MIT — xem [LICENSE](LICENSE).
