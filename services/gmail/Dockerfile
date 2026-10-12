FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /srv
COPY services/gmail/pyproject.toml services/gmail/uv.lock ./
RUN uv sync --frozen --no-dev
COPY services/gmail/gmail_service ./gmail_service
COPY services/gmail/entrypoint.py ./entrypoint.py
RUN useradd --uid 10001 --create-home gmail && mkdir /data && chown gmail:gmail /data
ENV GMAIL_CREDENTIALS_PATH=/data/credentials.json GMAIL_TOKEN_PATH=/data/token.json GMAIL_APPROVAL_SECRET_PATH=/data/approval-secret GMAIL_AUDIT_DB=/data/audit.db
CMD ["python", "entrypoint.py"]
