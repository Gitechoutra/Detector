"""Notifications cleared by "Mark all read".

Revision ID: 0011_notification_cleared
Revises: 0010_receiver_blocks
Create Date: 2026-11-02

notifications.cleared_at: set when the user clears their notification list.
Cleared notifications are hidden from the list but kept in the database.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = '0011_notification_cleared'
down_revision = '0010_receiver_blocks'
branch_labels = None
depends_on = None


def upgrade():
    if 'cleared_at' not in {c['name'] for c in sa.inspect(op.get_bind()).get_columns('notifications')}:
        op.add_column('notifications', sa.Column('cleared_at', mysql.DATETIME(fsp=3)))


def downgrade():
    op.drop_column('notifications', 'cleared_at')
