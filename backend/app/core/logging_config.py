"""
Centralized logging setup. Call configure_logging() once on startup.

Produces structured, timestamped logs to stdout. In production this format
is easy to ship into any log aggregator (CloudWatch, Loki, etc.) without
extra parsing work.
"""
import logging
import sys

from .config import settings


class RequestIdFilter(logging.Filter):
    """Injects a request_id field (defaults to '-') so the formatter never breaks
    even for log lines emitted outside of a request context."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        return True


def configure_logging() -> None:
    level = logging.DEBUG if settings.DEBUG else logging.INFO

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | req=%(request_id)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.addFilter(RequestIdFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Quiet down noisy third-party loggers unless we're in debug mode.
    for noisy in ("uvicorn.access", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING if not settings.DEBUG else logging.INFO)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
