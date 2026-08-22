"""
SQLAlchemy models.

Phase 1/3 additions on top of the original schema:
- Foreign keys with ON DELETE CASCADE (Dataset/RefreshToken -> User) so
  deleting a user cleans up their data instead of leaving orphan rows.
- Indexes on frequently-filtered columns (owner_id, created_at, etc.)
- RefreshToken table, to support real logout/refresh instead of relying
  purely on short-lived access tokens.
- Email verification + password reset fields/tables (architecture only -
  see services/auth_service.py for how they're used).
- History tables for model training runs, chat messages, and reports
  (analysis history piggybacks on the Dataset row's own audit fields).
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    Index,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=True)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    verification_token = Column(String, nullable=True, index=True)
    reset_token = Column(String, nullable=True, index=True)
    reset_token_expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    datasets = relationship(
        "Dataset", back_populates="owner", cascade="all, delete-orphan"
    )
    refresh_tokens = relationship(
        "RefreshToken", back_populates="user", cascade="all, delete-orphan"
    )
    model_runs = relationship(
        "ModelRun", back_populates="user", cascade="all, delete-orphan"
    )
    chat_messages = relationship(
        "ChatMessage", back_populates="user", cascade="all, delete-orphan"
    )
    reports = relationship(
        "ReportRecord", back_populates="user", cascade="all, delete-orphan"
    )
    dashboard_layouts = relationship(
        "DashboardLayout", back_populates="user", cascade="all, delete-orphan"
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash = Column(String, unique=True, index=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="refresh_tokens")

    __table_args__ = (Index("ix_refresh_tokens_user_revoked", "user_id", "revoked"),)


class Dataset(Base):
    __tablename__ = "datasets"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename = Column(String, nullable=False)
    original_filename = Column(String, nullable=True)
    stored_path = Column(String, nullable=False)
    file_type = Column(String, nullable=False)
    rows = Column(Integer, nullable=True)
    columns = Column(Integer, nullable=True)
    size_bytes = Column(Integer, nullable=True)
    cleaned_path = Column(String, nullable=True)
    schema_info = Column(JSON, nullable=True)
    processing_status = Column(String, nullable=True, default="ready")
    version = Column(Integer, nullable=True, default=1)
    parent_dataset_id = Column(
        Integer, ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True
    )
    cleaning_log = Column(JSON, nullable=True)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    owner = relationship("User", back_populates="datasets")
    model_runs = relationship(
        "ModelRun", back_populates="dataset", cascade="all, delete-orphan"
    )
    chat_messages = relationship(
        "ChatMessage", back_populates="dataset", cascade="all, delete-orphan"
    )
    reports = relationship(
        "ReportRecord", back_populates="dataset", cascade="all, delete-orphan"
    )
    dashboard_layouts = relationship(
        "DashboardLayout", back_populates="dataset", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_datasets_owner_uploaded", "owner_id", "uploaded_at"),)


class ModelRun(Base):
    """History of ML training runs against a dataset.

    `config`, `features`, `data_source` and `rows_used` together capture enough
    to reproduce a run, and let /explain and /report reuse a persisted model
    instead of retraining (which is what the original code did on every single
    request, silently creating a new model version each time a PDF downloaded).
    """

    __tablename__ = "model_runs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dataset_id = Column(
        Integer,
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_column = Column(String, nullable=True)
    task_type = Column(String, nullable=True)  # "classification" | "regression"
    best_model_name = Column(String, nullable=True)
    metrics = Column(JSON, nullable=True)
    model_path = Column(String, nullable=True)
    version = Column(Integer, default=1, nullable=False)
    # --- reproducibility metadata ---
    config = Column(JSON, nullable=True)  # the TrainRequest that produced this run
    features = Column(JSON, nullable=True)  # feature columns actually used
    leaderboard = Column(JSON, nullable=True)  # per-model scores, for history views
    data_source = Column(String, nullable=True)  # "original" | "cleaned"
    rows_used = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    user = relationship("User", back_populates="model_runs")
    dataset = relationship("Dataset", back_populates="model_runs")

    __table_args__ = (Index("ix_model_runs_dataset_version", "dataset_id", "version"),)


class ChatMessage(Base):
    """History of AI-chat messages per dataset, so conversation memory
    (Phase 6) has somewhere to persist to."""

    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dataset_id = Column(
        Integer,
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(String, nullable=False)  # "user" | "assistant"
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    user = relationship("User", back_populates="chat_messages")
    dataset = relationship("Dataset", back_populates="chat_messages")


class DashboardLayout(Base):
    """A saved analytics dashboard: an ordered list of chart configurations.

    Charts are stored as JSON rather than as columns because the shape is a
    user-authored chart spec (measure/aggregation/dimension/grain/type), and
    normalising it would buy nothing - it is only ever read and written whole.
    """

    __tablename__ = "dashboard_layouts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dataset_id = Column(
        Integer,
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String, nullable=False)
    charts = Column(JSON, nullable=False, default=list)
    is_default = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User", back_populates="dashboard_layouts")
    dataset = relationship("Dataset", back_populates="dashboard_layouts")

    __table_args__ = (
        Index("ix_dashboard_layouts_dataset_user", "dataset_id", "user_id"),
    )


class ReportRecord(Base):
    """History of generated reports per dataset."""

    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dataset_id = Column(
        Integer,
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    format = Column(String, nullable=False)  # "pdf" | "docx" | "xlsx" | "html"
    file_path = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    user = relationship("User", back_populates="reports")
    dataset = relationship("Dataset", back_populates="reports")
