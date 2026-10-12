FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /srv
COPY services/meta/pyproject.toml services/meta/uv.lock ./
RUN uv sync --frozen --no-dev
COPY services/meta/meta_service ./meta_service
COPY services/meta/entrypoint.py ./entrypoint.py
RUN useradd --uid 10002 --create-home meta && mkdir /data && chown meta:meta /data
ENV META_DATA_DIR=/data
CMD ["python", "entrypoint.py"]
