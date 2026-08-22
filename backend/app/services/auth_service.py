"""
Auth service layer - all business logic for authentication lives here.
Routers stay thin (parse request -> call service -> return response);
repositories stay dumb (just DB queries). This is the separation the
"service layer / repository layer" requirement asks for.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from .. import models
from ..core import security
from ..core.config import settings
from ..core.exceptions import AuthError, ConflictError, NotFoundError
from ..repositories.user_repository import RefreshTokenRepository, UserRepository
from .email_service import email_service


class AuthService:
    def __init__(self, db: Session):
        self.db = db
        self.users = UserRepository(db)
        self.refresh_tokens = RefreshTokenRepository(db)

    def register(self, email: str, password: str, full_name: str | None) -> models.User:
        if self.users.get_by_email(email):
            raise ConflictError("Email already registered", error_code="email_taken")

        verification_token = security.generate_opaque_token()
        user = models.User(
            email=email,
            full_name=full_name,
            hashed_password=security.hash_password(password),
            verification_token=verification_token,
        )
        user = self.users.create(user)
        email_service.send_verification_email(user.email, verification_token)
        return user

    def authenticate(self, email: str, password: str) -> models.User:
        user = self.users.get_by_email(email)
        if not user or not security.verify_password(password, user.hashed_password):
            raise AuthError("Incorrect email or password", error_code="invalid_credentials")
        if not user.is_active:
            raise AuthError("Account is disabled", error_code="account_disabled")
        return user

    def issue_tokens(self, user: models.User) -> tuple[str, str]:
        access_token = security.create_access_token(subject=user.email)
        raw_refresh, hashed_refresh, expires_at = security.generate_refresh_token()
        self.refresh_tokens.create(
            models.RefreshToken(user_id=user.id, token_hash=hashed_refresh, expires_at=expires_at)
        )
        return access_token, raw_refresh

    def refresh_access_token(self, raw_refresh_token: str) -> tuple[str, str]:
        """Rotates the refresh token (old one revoked, new one issued) and
        returns a fresh (access_token, refresh_token) pair."""
        token_hash = security.hash_refresh_token(raw_refresh_token)
        stored = self.refresh_tokens.get_valid_by_hash(token_hash)
        if not stored:
            raise AuthError("Invalid or expired refresh token", error_code="invalid_refresh_token")

        user = self.users.get(stored.user_id)
        if not user or not user.is_active:
            raise AuthError("Account is disabled", error_code="account_disabled")

        self.refresh_tokens.revoke(stored)
        return self.issue_tokens(user)

    def logout(self, raw_refresh_token: str) -> None:
        token_hash = security.hash_refresh_token(raw_refresh_token)
        stored = self.refresh_tokens.get_valid_by_hash(token_hash)
        if stored:
            self.refresh_tokens.revoke(stored)

    def verify_email(self, token: str) -> models.User:
        user = self.users.get_by_verification_token(token)
        if not user:
            raise NotFoundError("Invalid verification token", error_code="invalid_verification_token")
        user.is_verified = True
        user.verification_token = None
        self.db.commit()
        self.db.refresh(user)
        return user

    def request_password_reset(self, email: str) -> None:
        user = self.users.get_by_email(email)
        if not user:
            return
        token = security.generate_opaque_token()
        user.reset_token = token
        user.reset_token_expires_at = datetime.now(timezone.utc) + timedelta(
            hours=settings.RESET_TOKEN_EXPIRE_HOURS
        )
        self.db.commit()
        email_service.send_password_reset_email(user.email, token)

    def confirm_password_reset(self, token: str, new_password: str) -> None:
        user = self.users.get_by_reset_token(token)
        if not user or not user.reset_token_expires_at:
            raise NotFoundError("Invalid or expired reset token", error_code="invalid_reset_token")
        expires_at = user.reset_token_expires_at
        if expires_at.tzinfo is None:
            # SQLite drops tzinfo on round-trip even for DateTime(timezone=True) columns,
            # so normalize to UTC-aware before comparing.
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            raise NotFoundError("Invalid or expired reset token", error_code="invalid_reset_token")

        user.hashed_password = security.hash_password(new_password)
        user.reset_token = None
        user.reset_token_expires_at = None
        self.db.commit()
        # Revoking all refresh tokens forces re-login everywhere after a reset.
        self.refresh_tokens.revoke_all_for_user(user.id)


