FROM ghcr.io/astral-sh/uv:0.12.10 AS uv

FROM node:22-bookworm-slim AS codex
RUN npm install --global @openai/codex@0.153.4

FROM python:3.12-slim-bookworm AS base
COPY --from=uv /uv /usr/local/bin/uv
COPY --from=codex /usr/local/bin/node /usr/local/bin/node
COPY --from=codex /usr/local/lib/node_modules/@openai /opt/openai
RUN ln -s /opt/openai/codex/bin/codex.js /usr/local/bin/codex
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY alembic.ini ./
RUN uv sync --frozen --no-dev \
    && useradd --uid 10001 --create-home autopost \
    && mkdir -p /data/codex /data/media \
    && chown -R autopost:autopost /data

FROM base AS test
USER root
RUN uv sync --frozen --group dev \
    && python -m playwright install --with-deps chromium \
    && apt-get update && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*
COPY tests ./tests
COPY .env.example ./
CMD ["python", "-m", "pytest", "-q"]

FROM base AS unit-test
USER root
RUN uv sync --frozen --group dev
COPY tests ./tests
COPY .env.example ./
CMD ["python", "-m", "pytest", "-q"]

FROM base AS app
USER autopost
EXPOSE 8000
CMD ["python", "-m", "postify.container_start"]
