FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CARRIER_POOL_DATA_DIR=/data

WORKDIR /srv

COPY pyproject.toml ./
COPY app ./app
COPY tests ./tests

# Dependencies come from pyproject so they cannot drift from local installs.
# tzdata is explicit: HaulDesk timestamps are naive US Central, and slim images
# ship no zoneinfo database, so without it the adapter falls back to a fixed
# offset that would be wrong across a DST boundary.
RUN pip install --no-cache-dir '.[dev]' tzdata

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
