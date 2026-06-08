"""rename_is_primary_to_is_cover

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-08 00:01:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('room_images', 'is_primary', new_column_name='is_cover')


def downgrade() -> None:
    op.alter_column('room_images', 'is_cover', new_column_name='is_primary')
