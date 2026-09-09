"""Pytest path setup so `ingestion/tests` can `import app.*` and
`import ingestion.*` without installing either as a package — mirrors the
sys.path handling in `ingestion/cli.py` and `worker/celery_app.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo_root / "backend"))
sys.path.insert(0, str(_repo_root))
