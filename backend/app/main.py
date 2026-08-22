"""
Application entrypoint.

Responsibilities kept here on purpose (everything else is delegated):
- Wiring: middleware, exception handlers, routers, rate limiter.
- Auth endpoints: thin routes that call into AuthService.
- Health/metrics endpoints for ops.

Every route from the original main.py still exists at the same path with the
same response shape (register/login/me/health). New routes are additive. All
routers are mounted both at their legacy unprefixed path AND under /api/v1/...
so existing frontend code keeps working while new code can use the versioned
surface.
"""

from fastapi import APIRouter, Depends, FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import models, schemas
from .agent import router as agent_router
from .analysis import router as analysis_router
from .auth import get_current_user
from .chat import router as chat_router
from .cleaning import router as cleaning_router
from .core.config import settings
from .core.exceptions import register_exception_handlers
from .core.logging_config import configure_logging, get_logger
from .core.middleware import RequestIdMiddleware, SecurityHeadersMiddleware
from .dashboard import router as dashboard_router
from .database import engine, get_db
from .datasets import router as datasets_router
from .explain import router as explain_router
from .jobs import router as jobs_router
from .ml import router as ml_router
from .report import router as report_router
from .services.auth_service import AuthService
from .users import router as users_router

configure_logging()
logger = get_logger("insightflow.main")

# In dev/test, auto-create tables so the app boots without running alembic.
# Production should use `alembic upgrade head` before starting the server.
if not settings.is_production:
    models.Base.metadata.create_all(bind=engine)

limiter = Limiter(
    key_func=get_remote_address, default_limits=[settings.RATE_LIMIT_DEFAULT]
)

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "Self-service analytics API: dataset management, profiling and data quality, "
        "configurable cleaning, analytics, AutoML with model versioning, explainability, "
        "a dataset-grounded AI Copilot, and PDF reporting."
    ),
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

register_exception_handlers(app)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Request-ID"],
)


# --------------------------------------------------------------------------
# Auth router (register/login/refresh/logout/me/verify/reset)
# --------------------------------------------------------------------------
auth_router = APIRouter(prefix="/auth", tags=["auth"])


@auth_router.post(
    "/register", response_model=schemas.UserOut, status_code=status.HTTP_201_CREATED
)
@limiter.limit(settings.RATE_LIMIT_AUTH)
def register(request: Request, user: schemas.UserCreate, db: Session = Depends(get_db)):
    service = AuthService(db)
    return service.register(user.email, user.password, user.full_name)


@auth_router.post("/login", response_model=schemas.Token)
@limiter.limit(settings.RATE_LIMIT_AUTH)
def login(request: Request, data: schemas.LoginRequest, db: Session = Depends(get_db)):
    service = AuthService(db)
    user = service.authenticate(data.email, data.password)
    access_token, refresh_token = service.issue_tokens(user)
    return schemas.Token(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@auth_router.post("/refresh", response_model=schemas.Token)
@limiter.limit(settings.RATE_LIMIT_AUTH)
def refresh(
    request: Request, data: schemas.RefreshRequest, db: Session = Depends(get_db)
):
    service = AuthService(db)
    access_token, refresh_token = service.refresh_access_token(data.refresh_token)
    return schemas.Token(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(data: schemas.RefreshRequest, db: Session = Depends(get_db)):
    service = AuthService(db)
    service.logout(data.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@auth_router.get("/me", response_model=schemas.UserOut)
def me(current_user: models.User = Depends(get_current_user)):
    return current_user


@auth_router.post("/verify-email", response_model=schemas.UserOut)
def verify_email(data: schemas.EmailVerifyRequest, db: Session = Depends(get_db)):
    service = AuthService(db)
    return service.verify_email(data.token)


@auth_router.post("/request-password-reset", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(settings.RATE_LIMIT_AUTH)
def request_password_reset(
    request: Request, data: schemas.PasswordResetRequest, db: Session = Depends(get_db)
):
    service = AuthService(db)
    service.request_password_reset(data.email)
    # Always 202, whether or not the email exists, to avoid user enumeration.
    return {"detail": "If that email is registered, a reset link has been sent."}


@auth_router.post("/reset-password", status_code=status.HTTP_200_OK)
def reset_password(data: schemas.PasswordResetConfirm, db: Session = Depends(get_db)):
    service = AuthService(db)
    service.confirm_password_reset(data.token, data.new_password)
    return {"detail": "Password updated. Please log in again."}


# --------------------------------------------------------------------------
# Ops endpoints
# --------------------------------------------------------------------------
@app.get("/health", tags=["ops"])
def health(db: Session = Depends(get_db)):
    """Unauthenticated liveness probe.

    Also reports whether optional integrations are configured, so the frontend
    can show an honest "Copilot not configured" state instead of offering a
    chat box that always errors. No counts or user data are exposed here.
    """
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Health check DB failure: %s", exc)
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "database": "ok" if db_ok else "unreachable",
        "features": {
            "copilot": settings.copilot_enabled,
            "email_delivery": bool(settings.SMTP_HOST),
        },
        "limits": {
            "max_upload_mb": settings.MAX_UPLOAD_SIZE_MB,
            "supported_formats": ["csv", "xlsx", "json"],
            "max_preview_page_size": settings.PREVIEW_MAX_PAGE_SIZE,
        },
    }


@app.get("/metrics", tags=["ops"])
def metrics(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Instance-wide totals.

    Authentication is required: these are global counts across all users, so
    leaving them public leaked how many accounts and datasets exist. Per-user
    figures for the dashboard come from /users/me/summary instead.
    """
    return {
        "users_total": db.query(models.User).count(),
        "datasets_total": db.query(models.Dataset).count(),
        "model_runs_total": db.query(models.ModelRun).count(),
        "reports_total": db.query(models.ReportRecord).count(),
    }


# --------------------------------------------------------------------------
# Mount feature routers - both at legacy (root) paths and under /api/v1
# --------------------------------------------------------------------------
feature_routers = [
    auth_router,
    users_router,
    datasets_router,
    analysis_router,
    cleaning_router,
    dashboard_router,
    ml_router,
    explain_router,
    chat_router,
    agent_router,
    report_router,
    jobs_router,
]

for r in feature_routers:
    app.include_router(r)  # legacy path, e.g. /datasets/upload

v1 = APIRouter(prefix="/api/v1")
for r in feature_routers:
    v1.include_router(r)  # versioned path, e.g. /api/v1/datasets/upload
app.include_router(v1)
