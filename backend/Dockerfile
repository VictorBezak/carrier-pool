FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY backend/pyproject.toml ./
COPY backend/src ./src

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e .

EXPOSE 8000

CMD ["sh", "-c", "carrier-pool-sync --data-dir ${DATA_DIR:-/app/data} && uvicorn carrier_pool.api.app:app --host 0.0.0.0 --port 8000"]
