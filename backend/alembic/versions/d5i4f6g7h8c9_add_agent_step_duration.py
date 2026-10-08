"""add agent_steps.duration_seconds

Per-step wall-clock time for the tool call itself. Without it a trace can say
which tools ran but not which one was slow, which is the first question asked
of a run that took too long.

Revision ID: d5i4f6g7h8c9
Revises: c4h3e5f6g7b8
Create Date: 2026-10-08 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision: str = "d5i4f6g7h8c9"
down_revision: str | None = "c4h3e5f6g7b8"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Nullable with no default: rows written before this migration genuinely
    # have no timing, and backfilling a zero would claim they were instant.
    op.add_column(
        "agent_steps", sa.Column("duration_seconds", sa.Float(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("agent_steps", "duration_seconds")
