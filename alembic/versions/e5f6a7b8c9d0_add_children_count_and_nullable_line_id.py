"""add_children_count_and_nullable_line_id

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-15 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('bookings', sa.Column('children_count', sa.Integer(), nullable=False, server_default='0'))
    op.alter_column('bookings', 'customer_line_id', nullable=True)


def downgrade() -> None:
    op.alter_column('bookings', 'customer_line_id', nullable=False)
    op.drop_column('bookings', 'children_count')
