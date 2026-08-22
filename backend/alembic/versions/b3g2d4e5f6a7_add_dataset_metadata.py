"""add dataset metadata columns

Revision ID: b3g2d4e5f6a7
Revises: b2c4d6e8f0a1
Create Date: 2026-08-09 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3g2d4e5f6a7'
down_revision: Union[str, None] = 'b2c4d6e8f0a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    result = bind.execute(sa.text(f"PRAGMA table_info('{table}')"))
    return any(row[1] == column for row in result)


def upgrade() -> None:
    columns = [
        ('original_filename', sa.String(), {}),
        ('schema_info', sa.JSON(), {}),
        ('processing_status', sa.String(), {'server_default': 'ready'}),
        ('version', sa.Integer(), {'server_default': '1'}),
        ('parent_dataset_id', sa.Integer(), {}),
        ('cleaning_log', sa.JSON(), {}),
    ]
    for name, type_, kwargs in columns:
        if not _column_exists('datasets', name):
            op.add_column('datasets', sa.Column(name, type_, nullable=True, **kwargs))


def downgrade() -> None:
    for name in ['cleaning_log', 'parent_dataset_id', 'version',
                 'processing_status', 'schema_info', 'original_filename']:
        op.drop_column('datasets', name)
