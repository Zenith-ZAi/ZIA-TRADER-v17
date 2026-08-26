FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONBUFFERED=1 \
    PYTHONOPTIMIZE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/data /app/models \
    && groupadd --system nonroot \
    && useradd --system --gid nonroot --create-home nonroot \
    && chown -R nonroot:nonroot /app

USER nonroot:nonroot

EXPOSE 8000

CMD ["python", "main.py"]
