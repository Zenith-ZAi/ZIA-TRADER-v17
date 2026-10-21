FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONBUFFERED=1 \
    PYTHONOPTIMIZE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.lock ./
RUN uv pip sync --system --torch-backend cpu requirements.lock \
    && uv pip check --system

COPY . .
RUN mkdir -p /app/data /app/models \
    && groupadd --system nonroot \
    && useradd --system --gid nonroot --create-home nonroot \
    && chown -R nonroot:nonroot /app

USER nonroot:nonroot

EXPOSE 8000

CMD ["python", "main.py"]
