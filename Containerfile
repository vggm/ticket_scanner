FROM ghcr.io/astral-sh/uv:0.13.6 AS uv

FROM docker.io/library/python:3.12-slim AS build
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY ticket_scanner ./ticket_scanner
RUN uv sync --frozen --no-dev --no-editable

FROM docker.io/library/python:3.12-slim
RUN useradd --uid 1000 app \
    && mkdir /data && chown app:app /data
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
USER app
EXPOSE 8000
CMD ["uvicorn", "ticket_scanner.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
