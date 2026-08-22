from datetime import datetime, timezone


from .. import models
from .base import BaseRepository


class UserRepository(BaseRepository[models.User]):
    model = models.User

    def get_by_email(self, email: str) -> models.User | None:
        return self.db.query(models.User).filter(models.User.email == email).first()

    def get_by_verification_token(self, token: str) -> models.User | None:
        return (
            self.db.query(models.User)
            .filter(models.User.verification_token == token)
            .first()
        )

    def get_by_reset_token(self, token: str) -> models.User | None:
        return (
            self.db.query(models.User).filter(models.User.reset_token == token).first()
        )


class RefreshTokenRepository(BaseRepository[models.RefreshToken]):
    model = models.RefreshToken

    def get_valid_by_hash(self, token_hash: str) -> models.RefreshToken | None:
        now = datetime.now(timezone.utc)
        return (
            self.db.query(models.RefreshToken)
            .filter(
                models.RefreshToken.token_hash == token_hash,
                models.RefreshToken.revoked.is_(False),
                models.RefreshToken.expires_at > now,
            )
            .first()
        )

    def revoke(self, token: models.RefreshToken) -> None:
        token.revoked = True
        self.db.commit()

    def revoke_all_for_user(self, user_id: int) -> None:
        self.db.query(models.RefreshToken).filter(
            models.RefreshToken.user_id == user_id,
            models.RefreshToken.revoked.is_(False),
        ).update({"revoked": True})
        self.db.commit()
