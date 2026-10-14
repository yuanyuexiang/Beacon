FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58
ENV UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /srv/apps/api
COPY apps/api/pyproject.toml apps/api/uv.lock apps/api/.python-version ./
RUN uv sync --frozen --no-dev --extra maps-worker --no-install-project \
    && .venv/bin/playwright install --with-deps chrome \
    && apt-get update && apt-get install -y --no-install-recommends xvfb xauth gosu \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1000 --create-home maps \
    && mkdir /data && chown maps:maps /data
COPY apps/api/app/integrations/maps_menu_browser.py ./app/integrations/maps_menu_browser.py
COPY scripts/maps_menu_worker.py /srv/scripts/maps_menu_worker.py
COPY services/maps/entrypoint.sh /srv/maps-entrypoint.sh
ENV PATH="/srv/apps/api/.venv/bin:$PATH"
ENTRYPOINT ["sh", "/srv/maps-entrypoint.sh"]
