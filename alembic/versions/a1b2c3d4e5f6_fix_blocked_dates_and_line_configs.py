"""fix_blocked_dates_and_line_configs

Revision ID: a1b2c3d4e5f6
Revises: e2ffcf1a045b
Create Date: 2026-06-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'e2ffcf1a045b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add missing created_by FK on blocked_dates
    op.add_column(
        'blocked_dates',
        sa.Column(
            'created_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('admin_users.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )

    # Fix line_configs: rename key->config_key, change value to JSONB as config_value
    op.alter_column('line_configs', 'key', new_column_name='config_key')
    op.execute("ALTER TABLE line_configs ALTER COLUMN value TYPE JSONB USING value::jsonb")
    op.alter_column('line_configs', 'value', new_column_name='config_value')


def downgrade() -> None:
    op.alter_column('line_configs', 'config_value', new_column_name='value')
    op.execute("ALTER TABLE line_configs ALTER COLUMN value TYPE TEXT USING value::text")
    op.alter_column('line_configs', 'config_key', new_column_name='key')
    op.drop_column('blocked_dates', 'created_by')
