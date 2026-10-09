"""Point this process at a throwaway database BEFORE any application module loads.

`app.database` builds its engine at import time from the environment, so this must
run first. The CLI calls `isolate()` and only then imports the harness.
"""

from __future__ import annotations

import os
import secrets
import tempfile
from pathlib import Path


def isolate() -> Path:
    """Create a temp directory and aim DATABASE_URL, UPLOAD_DIR and secrets at it.
    Returns the database file path so the harness can assert it is connected to it."""
    tmp = Path(tempfile.mkdtemp(prefix="agent-eval-"))
    db_path = tmp / "eval.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["UPLOAD_DIR"] = str(tmp / "uploads")
    os.environ["JWT_SECRET"] = secrets.token_hex(32)
    os.environ["ENVIRONMENT"] = "development"
    os.environ["DEBUG"] = "false"
    return db_path


def create_schema() -> None:
    from app import models  # noqa: F401  (registers the tables)
    from app.database import Base, engine

    Base.metadata.create_all(bind=engine)
