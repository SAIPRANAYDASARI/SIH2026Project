"""Celery application instance.

Ingestion tasks (crawling, parsing, chunking, embedding — Steps 2-3) and any
scheduled refresh jobs register against this app. Broker/result backend URLs
come from the same `Settings` object the FastAPI service uses, so worker and
API always agree on configuration without duplicating env-var parsing.

Run locally with: celery -A celery_app worker --loglevel=info
"""

from __future__ import annotations

import sys
from pathlib import Path

# The worker image shares the backend's `app` package (settings, models) and
# the repo-root `ingestion` package (crawlers) so tasks can use the same
# Settings/DB session machinery as the API instead of re-implementing config
# loading. See infra/docker-compose.yml for how both are mounted in dev.
_repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo_root / "backend"))
sys.path.insert(0, str(_repo_root))

from celery import Celery  # noqa: E402

from app.core.config import get_settings  # noqa: E402

settings = get_settings()

celery_app = Celery(
    "manak_sahayak",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["tasks.health", "tasks.ingestion"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_track_started=True,
)
