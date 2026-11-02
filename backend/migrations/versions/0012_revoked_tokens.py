"""Logout revokes the login token.

Revision ID: 0012_revoked_tokens
Revises: 0011_notification_cleared
Create Date: 2026-11-02

revoked_tokens: the JWT ids ended by logout; every request rejects them.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = '0012_revoked_tokens'
down_revision = '0011_notification_cleared'
branch_labels = None
depends_on = None

DT3 = mysql.DATETIME(fsp=3)


def upgrade():
    if not sa.inspect(op.get_bind()).has_table('revoked_tokens'):
        op.create_table(
            'revoked_tokens',
            sa.Column('jti', sa.String(36), primary_key=True),
            sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id')),
            sa.Column('expires_at', DT3, nullable=False),
            sa.Column('revoked_at', DT3, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP(3)')),
            mysql_engine='InnoDB', mysql_charset='utf8mb4', mysql_collate='utf8mb4_unicode_ci')
        op.create_index('ix_revoked_tokens_expires_at', 'revoked_tokens', ['expires_at'])


def downgrade():
    op.drop_table('revoked_tokens')
