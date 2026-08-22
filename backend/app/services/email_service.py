"""
Email delivery service.

This is the "email verification / password reset architecture" piece: the
token generation, storage, and validation logic is fully functional. Actual
SMTP delivery is stubbed to a log line unless SMTP_HOST is configured, so
you can wire up a real provider (SES, SendGrid, Postmark, etc.) by filling
in `_send_via_smtp` without touching any calling code.
"""
import logging
import smtplib
from email.mime.text import MIMEText

from ..core.config import settings

logger = logging.getLogger("insightflow.email")


class EmailService:
    def send_verification_email(self, to_email: str, token: str) -> None:
        link = f"{settings.FRONTEND_URL}/verify-email?token={token}"
        self._send(
            to_email,
            subject="Verify your InsightFlow AI account",
            body=f"Welcome to InsightFlow AI! Verify your email by visiting: {link}",
        )

    def send_password_reset_email(self, to_email: str, token: str) -> None:
        link = f"{settings.FRONTEND_URL}/reset-password?token={token}"
        self._send(
            to_email,
            subject="Reset your InsightFlow AI password",
            body=f"Reset your password by visiting: {link}\nIf you didn't request this, ignore this email.",
        )

    def _send(self, to_email: str, subject: str, body: str) -> None:
        if not settings.SMTP_HOST:
            logger.info("[EMAIL:DEV-LOG-ONLY] To=%s Subject=%s Body=%s", to_email, subject, body)
            return
        self._send_via_smtp(to_email, subject, body)

    def _send_via_smtp(self, to_email: str, subject: str, body: str) -> None:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = settings.EMAIL_FROM
        msg["To"] = to_email
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.starttls()
            if settings.SMTP_USER:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.EMAIL_FROM, [to_email], msg.as_string())


email_service = EmailService()
