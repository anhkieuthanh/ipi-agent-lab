# Dockerfile — W2-01
#
# Image cho service `app`. Lõi agent (W3-01) chưa tồn tại tại thời điểm viết
# ticket này (Tuần 1 mới xong thiết kế), nên container chỉ sync dependency
# bằng uv và đứng chờ (sleep infinity) — sẵn sàng để `docker compose exec app
# ...` chạy pytest/script khi code lõi được thêm vào. Cập nhật CMD sang lệnh
# chạy server thật khi W3-xx có entrypoint.

FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /workspace

COPY pyproject.toml uv.lock ./
RUN uv sync --all-groups --no-install-project

COPY . .
RUN uv sync --all-groups

CMD ["sleep", "infinity"]
