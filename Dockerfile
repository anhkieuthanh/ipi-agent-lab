# Dockerfile — image dùng chung cho service `app` và `dashboard` (STT-13).
#
# Lõi agent (STT-26) chưa có entrypoint nên `app` chỉ sync dependency rồi đứng chờ
# (sleep infinity) — chạy việc bằng `docker compose exec app ...`. Đổi CMD khi có.

FROM python:3.12-slim

RUN pip install --no-cache-dir uv

# Venv nằm NGOÀI /workspace: docker-compose mount mã nguồn vào /workspace, nếu venv
# ở /workspace/.venv thì bị .venv của máy host (macOS) đè lên và `uv run` hỏng.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /workspace

COPY pyproject.toml uv.lock ./
RUN uv sync --all-groups --no-install-project

COPY . .
RUN uv sync --all-groups

CMD ["sleep", "infinity"]
