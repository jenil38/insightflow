"""
Cross-cutting HTTP middleware: request IDs (for log correlation) and
security headers. Rate limiting is configured separately via slowapi in
main.py (it needs to be attached to the app + individual routes).
"""
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .config import settings


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attaches a unique request_id to every request/response for tracing,
    and logs basic timing information."""

    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-ms"] = f"{duration_ms:.2f}"
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds standard security headers to every response.

    Notes:
    - HSTS is only meaningful over HTTPS, so it's only set in production.
    - CSP here is intentionally permissive-but-safe for an API (no HTML is
      served by this backend); tighten further if you start serving pages.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response
