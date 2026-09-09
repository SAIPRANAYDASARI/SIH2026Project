"""Smoke-test task proving the worker can reach the broker and (once wired
in Step 2+) the database — used by `docs/RUNBOOK.md`'s "is Celery actually
working" check: `celery -A celery_app call tasks.health.ping`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from celery_app import celery_app


@celery_app.task(name="tasks.health.ping")
def ping() -> dict[str, str]:
    return {"status": "ok", "checked_at": datetime.now(UTC).isoformat()}
