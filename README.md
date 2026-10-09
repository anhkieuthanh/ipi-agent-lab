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

Bốn service trong `docker-compose.yml`: `qdrant` (vector store) · `mailhog` (SMTP giả) ·
`app` (dev container) · `dashboard` (Streamlit, cổng 8501). Canary listener (STT-34) thêm khi
hiện thực xong.

```bash
make up          # dựng cả lab, chờ mọi service healthy
make dashboard   # chỉ dashboard — http://localhost:8501
make down
```

Các target khác: `reset` · `ps` · `logs` · `kb-build` · `kb-rebuild` ·
`kb-bench` · `kb-stats`.

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
