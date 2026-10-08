"""add agent_steps.decided_at

When a person approved or declined an action the agent proposed. Nullable with
no default: steps that never needed a decision, and every row written before
this migration, genuinely have no decision time.

Revision ID: e6j5g7h8i9d0
Revises: d5i4f6g7h8c9
Create Date: 2026-10-08 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision: str = "e6j5g7h8i9d0"
down_revision: str | None = "d5i4f6g7h8c9"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "agent_steps",
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_steps", "decided_at")
