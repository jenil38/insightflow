"""add agent_runs and agent_steps tables

Revision ID: c4h3e5f6g7b8
Revises: b3g2d4e5f6a7
Create Date: 2026-10-07 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision: str = "c4h3e5f6g7b8"
down_revision: str | None = "b3g2d4e5f6a7"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "dataset_id",
            sa.Integer(),
            sa.ForeignKey("datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="running"),
        sa.Column("allow_actions", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column(
            "total_prompt_tokens", sa.Integer(), nullable=True, server_default="0"
        ),
        sa.Column(
            "total_completion_tokens",
            sa.Integer(),
            nullable=True,
            server_default="0",
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
    )
    # Indexes for agent_runs
    op.create_index("ix_agent_runs_id", "agent_runs", ["id"])
    op.create_index("ix_agent_runs_user_id", "agent_runs", ["user_id"])
    op.create_index("ix_agent_runs_dataset_id", "agent_runs", ["dataset_id"])
    op.create_index("ix_agent_runs_created_at", "agent_runs", ["created_at"])
    op.create_index(
        "ix_agent_runs_user_created", "agent_runs", ["user_id", "created_at"]
    )

    op.create_table(
        "agent_steps",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("tool_name", sa.String(), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("redacted", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("truncated", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    # Indexes for agent_steps
    op.create_index("ix_agent_steps_id", "agent_steps", ["id"])
    op.create_index("ix_agent_steps_run_id", "agent_steps", ["run_id"])


def downgrade() -> None:
    op.drop_table("agent_steps")
    op.drop_table("agent_runs")
