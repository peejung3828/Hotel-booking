"""add_missing_columns

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-08 00:02:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('rooms', sa.Column('price_holiday', sa.Numeric(10, 2), nullable=True))
    op.add_column('payments', sa.Column('updated_at', sa.DateTime(), nullable=True,
                                        server_default=sa.text('now()')))
    op.add_column('coupons', sa.Column('updated_at', sa.DateTime(), nullable=True,
                                       server_default=sa.text('now()')))


def downgrade() -> None:
    op.drop_column('coupons', 'updated_at')
    op.drop_column('payments', 'updated_at')
    op.drop_column('rooms', 'price_holiday')
