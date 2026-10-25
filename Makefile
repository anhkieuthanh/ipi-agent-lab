.PHONY: up down reset ps logs console console-build console-dev demo-cli kb-build kb-rebuild kb-bench kb-stats test lint

# --wait: chỉ trả về khi cả 5 service đã HEALTHY (xem healthcheck trong
# docker-compose.yml), thay vì trả về ngay lúc container vừa được tạo.
up:
	docker compose up -d --build --wait

down:
	docker compose down

# Xóa cả volume: mất collection Qdrant nền.
# Dùng khi muốn dựng lại từ đầu, KHÔNG dùng giữa chừng loạt thực nghiệm.
reset:
	docker compose down -v --remove-orphans
	docker compose up -d --build --wait

ps:
	docker compose ps

logs:
	docker compose logs -f --tail=100

# Kho tri thức (kênh K1). `src/` phải trên PYTHONPATH: các module nội bộ nạp theo
# đường dẫn chứ không cài thành package, pytest tự lo qua pyproject nhưng
# `python -m` chạy tay thì không.
kb-build:
	PYTHONPATH=src uv run python -m rag.ingest build

# Dựng lại từ đầu — chỉ khi đổi model embedding hoặc tham số chunk.
kb-rebuild:
	PYTHONPATH=src uv run python -m rag.ingest build --recreate

# Ngưỡng: chèn + xóa 1 tài liệu < 10 giây.
kb-bench:
	PYTHONPATH=src uv run python -m rag.ingest bench

kb-stats:
	PYTHONPATH=src uv run python -m rag.ingest stats

test:
	uv run pytest -q

lint:
	uv run ruff check .

# IPI Guard Console (STT-58/82) — API FastAPI + giao diện React.
# console-build: build giao diện vào web/dist (cần Node). console: API phục vụ cả giao diện đã
# build ở một cổng, chỉ nghe 127.0.0.1, mở nút chạy demo (DEMO_LIVE=1). console-dev: chạy Vite
# (5173) + API (8600) song song khi phát triển giao diện.
console-build:
	cd web && npm install --no-audit --no-fund && npm run build

console:
	DEMO_LIVE=1 PYTHONPATH=src uv run uvicorn console.app:app --host 127.0.0.1 --port 8600

console-dev:
	DEMO_LIVE=1 PYTHONPATH=src uv run uvicorn console.app:app --host 127.0.0.1 --port 8600 --reload &
	cd web && npm run dev

# Chạy một kịch bản demo từ dòng lệnh (không cần giao diện).
demo-cli:
	PYTHONPATH=src DEMO_LIVE=1 uv run python -m console.demo $(ARGS)
