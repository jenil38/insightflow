"""Storage abstraction.

All file I/O for uploads, cleaned data, models, and reports goes through
this module. The current implementation writes to local disk; replacing it
with S3/GCS/Azure Blob requires implementing the same interface.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from .config import settings


class LocalStorage:
    def __init__(self, base_dir: str | None = None):
        self.base_dir = base_dir or settings.UPLOAD_DIR

    def save(self, content: bytes, ext: str, prefix: str = "") -> str:
        os.makedirs(self.base_dir, exist_ok=True)
        name = f"{prefix}{uuid.uuid4().hex}{ext}"
        path = os.path.join(self.base_dir, name)
        with open(path, "wb") as f:
            f.write(content)
        return path

    def read(self, path: str) -> bytes:
        with open(path, "rb") as f:
            return f.read()

    def exists(self, path: str) -> bool:
        return path is not None and os.path.exists(path)

    def delete(self, path: str) -> None:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    def size(self, path: str) -> int:
        if not path or not os.path.exists(path):
            return 0
        return os.path.getsize(path)

    def model_dir(self) -> str:
        d = os.path.join(self.base_dir, "models")
        os.makedirs(d, exist_ok=True)
        return d

    def report_dir(self) -> str:
        d = os.path.join(self.base_dir, "reports")
        os.makedirs(d, exist_ok=True)
        return d


storage = LocalStorage()
