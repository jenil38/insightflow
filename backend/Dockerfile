# Backend image.
#
# Single stage on purpose: the heavy dependencies here (pandas, scikit-learn,
# xgboost, lightgbm, catboost, shap) ship as manylinux wheels, so there is
# nothing to compile and a builder stage would save almost nothing while making
# the build harder to follow.
FROM python:3.12-slim

# PYTHONUNBUFFERED keeps logs streaming to the container log rather than sitting
# in a buffer; PYTHONDONTWRITEBYTECODE avoids .pyc files in a layer that is
# rebuilt anyway.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# libgomp1 is required at runtime by LightGBM and XGBoost (OpenMP);
# curl is used by the container health check.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, so a source-only change doesn't reinstall the ML stack.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Run as a non-root user. UPLOAD_DIR must be writable by that user, so it is
# created and chowned before the switch.
RUN useradd --create-home --shell /bin/bash insightflow \
 && mkdir -p /app/uploads/models \
 && chown -R insightflow:insightflow /app
USER insightflow

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# Migrations run at start rather than at build time, because they need the
# database to exist. `alembic upgrade head` is idempotent.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
