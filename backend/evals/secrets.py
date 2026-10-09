"""Scan cassettes for anything that looks like a credential before they are committed.

Cassettes are recorded at the `_call_provider` boundary (the model's message, usage
and latency), so no request or header is stored. This scan is the check that stays
true if that ever changes: it runs in the test suite over the committed files.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

PATTERNS = {
    "groq-style key": re.compile(r"gsk_[A-Za-z0-9]{10,}"),
    "authorization header": re.compile(r"authorization", re.IGNORECASE),
    "bearer token": re.compile(r"bearer\s+[A-Za-z0-9._\-]{8,}", re.IGNORECASE),
    "api key mention": re.compile(r"api[ _\-]?key", re.IGNORECASE),
    "jwt": re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\."),
    "generic secret assignment": re.compile(
        r"(secret|passw(?:or)?d|token)[\"']?\s*[:=]\s*[\"'][^\"']{8,}", re.IGNORECASE
    ),
}


def scan_text(text: str, extra_literals: list[str] | None = None) -> list[str]:
    findings = [name for name, pattern in PATTERNS.items() if pattern.search(text)]
    for literal in extra_literals or []:
        if len(literal) >= 8 and literal in text:
            findings.append("the configured key value")
    return findings


def scan_directory(directory: Path) -> dict[str, list[str]]:
    """Maps each offending file to what was found. Empty means clean."""
    literals = [v for k in ("GROQ_API_KEY", "JWT_SECRET") if (v := os.environ.get(k))]
    out: dict[str, list[str]] = {}
    for path in sorted(directory.glob("*.json")):
        found = scan_text(path.read_text(encoding="utf-8"), literals)
        if found:
            out[path.name] = found
    return out
