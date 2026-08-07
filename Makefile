.PHONY: up down reset ps logs canary-hits test lint

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

test:
	uv run pytest -q

lint:
	uv run ruff check .
