.PHONY: up down reset ps logs canary-hits kb-build kb-rebuild kb-bench kb-stats test lint

# --wait: chỉ trả về khi cả 4 service đã HEALTHY (xem healthcheck trong
# docker-compose.yml), thay vì trả về ngay lúc container vừa được tạo.
up:
	docker compose up -d --build --wait

down:
	docker compose down

# Xóa cả volume: mất collection Qdrant nền VÀ file canary_hits.jsonl.
# Dùng khi muốn dựng lại từ đầu, KHÔNG dùng giữa chừng loạt thực nghiệm.
reset:
	docker compose down -v --remove-orphans
	docker compose up -d --build --wait

ps:
	docker compose ps

logs:
	docker compose logs -f --tail=100

# Bằng chứng G1: mọi request đã chạm canary sink.
canary-hits:
	docker compose exec canary cat /data/canary_hits.jsonl

# Kho tri thức (W2-05). `src/` phải trên PYTHONPATH: các module nội bộ nạp theo
# đường dẫn chứ không cài thành package, pytest tự lo qua pyproject nhưng
# `python -m` chạy tay thì không.
kb-build:
	PYTHONPATH=src uv run python -m rag.ingest build

# Dựng lại từ đầu — chỉ khi đổi model embedding hoặc tham số chunk.
kb-rebuild:
	PYTHONPATH=src uv run python -m rag.ingest build --recreate

# DoD W2-05: chèn + xóa 1 tài liệu < 10 giây.
kb-bench:
	PYTHONPATH=src uv run python -m rag.ingest bench

kb-stats:
	PYTHONPATH=src uv run python -m rag.ingest stats

test:
	uv run pytest -q

lint:
	uv run ruff check .
