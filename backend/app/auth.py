"""
Backward-compatible auth module.

Historically every other module did `from . import auth` and used
`auth.get_current_user`, `auth.hash_password`, etc. Rather than touching all
of those call sites, this module now re-exports the same names, backed by
the new core/security.py + services/auth_service.py implementation. New
code should prefer importing from `app.core.security` / `app.services.auth_service`
directly; this file exists purely for compatibility.
"""

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from . import models
from .core.exceptions import AuthError
from .core.security import (  # noqa: F401 - re-exported for backward compatibility
    create_access_token,
    hash_password,
    verify_password,
)
from .database import get_db
from .core import security

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> models.User:
    payload = security.decode_access_token(token)
    email: str | None = payload.get("sub")
    if email is None:
        raise AuthError("Could not validate credentials", error_code="invalid_token")
    user = db.query(models.User).filter(models.User.email == email).first()
    if user is None:
        raise AuthError("Could not validate credentials", error_code="invalid_token")
    if not user.is_active:
        raise AuthError("Account is disabled", error_code="account_disabled")
    return user
