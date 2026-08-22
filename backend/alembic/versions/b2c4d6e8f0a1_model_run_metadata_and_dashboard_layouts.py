"""model run reproducibility metadata and dashboard layouts

Adds:
- model_runs.config / features / leaderboard / data_source / rows_used, so a
  training run can be reproduced and so /explain and /report can reuse a
  persisted model instead of retraining on every request.
- an index on (dataset_id, version), which is the lookup every "latest run"
  query performs.
- the dashboard_layouts table backing saved analytics dashboards.

Additive only: no column is dropped or retyped, so this upgrade is safe to run
against an existing database with live data.

Revision ID: b2c4d6e8f0a1
Revises: 61f00253b63b
Create Date: 2026-08-05 22:40:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c4d6e8f0a1"
down_revision: Union[str, None] = "61f00253b63b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- model run reproducibility metadata ------------------------------
    with op.batch_alter_table("model_runs") as batch:
        batch.add_column(sa.Column("config", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("features", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("leaderboard", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("data_source", sa.String(), nullable=True))
        batch.add_column(sa.Column("rows_used", sa.Integer(), nullable=True))

    op.create_index(
        "ix_model_runs_dataset_version", "model_runs", ["dataset_id", "version"], unique=False
    )

    # --- saved dashboard layouts -----------------------------------------
    op.create_table(
        "dashboard_layouts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("dataset_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("charts", sa.JSON(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dashboard_layouts_id", "dashboard_layouts", ["id"], unique=False)
    op.create_index("ix_dashboard_layouts_user_id", "dashboard_layouts", ["user_id"], unique=False)
    op.create_index(
        "ix_dashboard_layouts_dataset_id", "dashboard_layouts", ["dataset_id"], unique=False
    )
    op.create_index(
        "ix_dashboard_layouts_dataset_user",
        "dashboard_layouts",
        ["dataset_id", "user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_dashboard_layouts_dataset_user", table_name="dashboard_layouts")
    op.drop_index("ix_dashboard_layouts_dataset_id", table_name="dashboard_layouts")
    op.drop_index("ix_dashboard_layouts_user_id", table_name="dashboard_layouts")
    op.drop_index("ix_dashboard_layouts_id", table_name="dashboard_layouts")
    op.drop_table("dashboard_layouts")

    op.drop_index("ix_model_runs_dataset_version", table_name="model_runs")
    with op.batch_alter_table("model_runs") as batch:
        batch.drop_column("rows_used")
        batch.drop_column("data_source")
        batch.drop_column("leaderboard")
        batch.drop_column("features")
        batch.drop_column("config")
