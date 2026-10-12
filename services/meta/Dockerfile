FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58
WORKDIR /srv
COPY services/meta/pyproject.toml services/meta/uv.lock ./
RUN uv sync --frozen --no-dev
COPY services/meta/meta_service ./meta_service
COPY services/meta/entrypoint.py ./entrypoint.py
RUN useradd --uid 10002 --create-home meta && mkdir /data && chown meta:meta /data
ENV META_DATA_DIR=/data
CMD ["python", "entrypoint.py"]
