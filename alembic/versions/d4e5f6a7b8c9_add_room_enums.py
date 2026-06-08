"""add_room_enums

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-09 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE TYPE room_status AS ENUM ('available', 'maintenance', 'closed')")
    op.execute("CREATE TYPE room_type AS ENUM ('deluxe', 'superior', 'suite', 'family')")

    op.execute("ALTER TABLE rooms ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TABLE rooms ALTER COLUMN status TYPE room_status USING status::room_status")
    op.execute("ALTER TABLE rooms ALTER COLUMN status SET DEFAULT 'available'::room_status")

    op.execute("ALTER TABLE rooms ALTER COLUMN type TYPE room_type USING type::room_type")


def downgrade() -> None:
    op.execute("ALTER TABLE rooms ALTER COLUMN status TYPE VARCHAR(50) USING status::text")
    op.execute("ALTER TABLE rooms ALTER COLUMN type TYPE VARCHAR(50) USING type::text")
    op.execute("DROP TYPE room_status")
    op.execute("DROP TYPE room_type")
