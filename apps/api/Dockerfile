# Beacon API：Python 3.12 + uv。构建上下文为仓库根目录（需要 templates/）。
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS base
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/apps/api
# 先装依赖（利用缓存），再拷贝代码
COPY apps/api/pyproject.toml apps/api/uv.lock apps/api/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY apps/api/ ./
COPY templates/ /srv/templates/
RUN uv sync --frozen --no-dev
ENV PATH="/srv/apps/api/.venv/bin:$PATH" BEACON_TEMPLATES_DIR=/srv/templates
EXPOSE 8000
# 迁移后启动；BEACON_* 由 compose 注入
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
