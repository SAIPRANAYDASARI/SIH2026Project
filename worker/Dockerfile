# syntax=docker/dockerfile:1
# Build context is the repo root (see infra/docker-compose.yml) so this
# image can mount the backend's `app` package alongside worker code.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /worker

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

RUN addgroup --system app && adduser --system --ingroup app app

COPY worker/requirements.txt .
RUN pip install -r requirements.txt

COPY backend/app /backend/app
COPY ingestion /ingestion
COPY worker/ .

ENV PYTHONPATH=/backend:/worker:/

USER app
CMD ["celery", "-A", "celery_app", "worker", "--loglevel=info"]
