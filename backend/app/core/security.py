"""
Security primitives: password hashing, password complexity rules,
access-token + refresh-token issuing/verification.

Access tokens: short-lived, sent as Bearer tokens (unchanged from before).
Refresh tokens: longer-lived, opaque random strings stored (hashed) in the
DB so they can be individually revoked on logout - this is what makes
"logout" and "refresh" actually work, rather than just relying on the
access token's natural expiry.
"""

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone

from jose import jwt, JWTError
from passlib.context import CryptContext

from .config import settings
from .exceptions import AuthError

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

PASSWORD_MIN_LENGTH = 8


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def validate_password_complexity(password: str) -> None:
    """Raises AuthError with a human-readable message if the password is too weak.
    Rules: 8+ chars, at least one uppercase, one lowercase, one digit, one symbol."""
    problems = []
    if len(password) < PASSWORD_MIN_LENGTH:
        problems.append(f"at least {PASSWORD_MIN_LENGTH} characters")
    if not re.search(r"[A-Z]", password):
        problems.append("an uppercase letter")
    if not re.search(r"[a-z]", password):
        problems.append("a lowercase letter")
    if not re.search(r"\d", password):
        problems.append("a number")
    if not re.search(r"[^\w\s]", password):
        problems.append("a symbol")
    if problems:
        raise AuthError(
            "Password must contain " + ", ".join(problems) + ".",
            error_code="weak_password",
            status_code=422,
        )


# --------------------------------------------------------------------------
# Access tokens (JWT, short-lived)
# --------------------------------------------------------------------------


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {"sub": subject, "exp": expire, "type": "access"}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        if payload.get("type") != "access":
            raise AuthError("Invalid token type", error_code="invalid_token")
        return payload
    except JWTError:
        raise AuthError("Could not validate credentials", error_code="invalid_token")


# --------------------------------------------------------------------------
# Refresh tokens (opaque random string, stored hashed in DB, revocable)
# --------------------------------------------------------------------------


def generate_refresh_token() -> tuple[str, str, datetime]:
    """Returns (raw_token_to_send_to_client, hashed_token_to_store, expires_at)."""
    raw = secrets.token_urlsafe(48)
    hashed = hash_refresh_token(raw)
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
    return raw, hashed, expires_at


def hash_refresh_token(raw_token: str) -> str:
    # SHA-256 is fine here (not bcrypt): this is a high-entropy random token,
    # not a low-entropy user password, so we just need a fast, safe digest
    # to look it up by hash without storing it in plaintext.
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_opaque_token() -> str:
    """Used for email-verification and password-reset tokens."""
    return secrets.token_urlsafe(32)
