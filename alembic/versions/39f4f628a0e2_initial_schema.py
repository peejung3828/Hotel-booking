"""initial_schema

Revision ID: 39f4f628a0e2
Revises:
Create Date: 2026-06-07 02:36:37.126799

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '39f4f628a0e2'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE TYPE admin_role AS ENUM ('admin', 'super_admin')")

    op.create_table(
        'admin_users',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('username', sa.String(100), unique=True, nullable=True),
        sa.Column('hashed_password', sa.String(255), nullable=True),
        sa.Column('line_id', sa.String(100), unique=True, nullable=True),
        sa.Column('role', postgresql.ENUM('admin', 'super_admin', name='admin_role', create_type=False), nullable=False, server_default='admin'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
    )

    op.create_table(
        'rooms',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('type', sa.String(50), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('price_per_night', sa.Numeric(10, 2), nullable=False),
        sa.Column('price_weekend', sa.Numeric(10, 2), nullable=True),
        sa.Column('max_guests', sa.Integer(), nullable=False, server_default='2'),
        sa.Column('min_stay', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('amenities', postgresql.JSONB(), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='available'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
    )

    op.create_table(
        'room_images',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('room_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('rooms.id', ondelete='CASCADE'), nullable=False),
        sa.Column('url', sa.String(500), nullable=False),
        sa.Column('is_primary', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
    )

    op.create_table(
        'coupons',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('code', sa.String(50), unique=True, nullable=False),
        sa.Column('discount_type', sa.String(20), nullable=False),
        sa.Column('discount_value', sa.Numeric(10, 2), nullable=False),
        sa.Column('min_order_amount', sa.Numeric(10, 2), nullable=True),
        sa.Column('max_usage', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('used_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('expire_date', sa.Date(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
    )

    op.execute("""
        CREATE TYPE booking_status AS ENUM
        ('pending','confirmed','checked_in','checked_out','cancelled')
    """)

    op.create_table(
        'bookings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('booking_ref', sa.String(20), unique=True, nullable=False),
        sa.Column('room_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('rooms.id'), nullable=False),
        sa.Column('customer_line_id', sa.String(100), nullable=False),
        sa.Column('customer_name', sa.String(200), nullable=False),
        sa.Column('customer_phone', sa.String(20), nullable=False),
        sa.Column('check_in', sa.Date(), nullable=False),
        sa.Column('check_out', sa.Date(), nullable=False),
        sa.Column('nights', sa.Integer(), nullable=False),
        sa.Column('base_price', sa.Numeric(10, 2), nullable=False),
        sa.Column('discount_amount', sa.Numeric(10, 2), nullable=False, server_default='0'),
        sa.Column('total_price', sa.Numeric(10, 2), nullable=False),
        sa.Column('coupon_code', sa.String(50), nullable=True),
        sa.Column('status', postgresql.ENUM('pending','confirmed','checked_in','checked_out','cancelled', name='booking_status', create_type=False), nullable=False, server_default='pending'),
        sa.Column('notes', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_bookings_booking_ref', 'bookings', ['booking_ref'], unique=True)
    op.create_index('ix_bookings_customer_line_id', 'bookings', ['customer_line_id'])

    op.execute("CREATE TYPE payment_method AS ENUM ('bank_transfer','qr_promptpay','line_pay','debit_card','credit_card')")
    op.execute("CREATE TYPE payment_status AS ENUM ('pending','verified','rejected')")

    op.create_table(
        'payments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('booking_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('bookings.id', ondelete='CASCADE'), nullable=False),
        sa.Column('method', postgresql.ENUM('bank_transfer','qr_promptpay','line_pay','debit_card','credit_card', name='payment_method', create_type=False), nullable=False),
        sa.Column('amount', sa.Numeric(10, 2), nullable=False),
        sa.Column('status', postgresql.ENUM('pending','verified','rejected', name='payment_status', create_type=False), nullable=False, server_default='pending'),
        sa.Column('slip_url', sa.String(500), nullable=True),
        sa.Column('omise_charge_id', sa.String(100), nullable=True),
        sa.Column('verified_at', sa.DateTime(), nullable=True),
        sa.Column('verified_by', sa.String(200), nullable=True),
        sa.Column('rejection_reason', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
    )

    op.create_table(
        'blocked_dates',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('date', sa.Date(), unique=True, nullable=False),
        sa.Column('reason', sa.String(200), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
    )

    op.create_table(
        'line_configs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('key', sa.String(100), unique=True, nullable=False),
        sa.Column('value', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
    )


def downgrade() -> None:
    op.drop_table('line_configs')
    op.drop_table('blocked_dates')
    op.drop_table('payments')
    op.execute('DROP TYPE payment_status')
    op.execute('DROP TYPE payment_method')
    op.drop_table('bookings')
    op.execute('DROP TYPE booking_status')
    op.drop_table('coupons')
    op.drop_table('room_images')
    op.drop_table('rooms')
    op.drop_table('admin_users')
    op.execute('DROP TYPE admin_role')
