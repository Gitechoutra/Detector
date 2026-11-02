"""Dummy accounts from .env, sample history, and the Detection Engine.

Revision ID: 0009_seed_accounts_engine
Revises: 0008_user_authorization
Create Date: 2026-11-02

- users.seed_key: a stable id for each predefined dummy account (rahul,
  analyst, ...). Their email and password come from backend/.env and are
  synchronised by the seeder; the key lets an email change rename the account
  instead of creating a duplicate. Existing dummy accounts are matched by email.
- The retired RECEIVER role: remaining RECEIVER users become USER (customers
  send and receive with one login), as on a freshly seeded database.
- detection_runs: results of Detection Engine runs.
- Re-runs every seeder, so a database migrated before now gets the missing
  settings, dummy accounts and the sample transaction history.
No data is deleted.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = '0009_seed_accounts_engine'
down_revision = '0008_user_authorization'
branch_labels = None
depends_on = None

OPTS = {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'seed_key' not in {c['name'] for c in inspector.get_columns('users')}:
        op.add_column('users', sa.Column('seed_key', sa.String(20)))
        op.create_unique_constraint('uq_users_seed_key', 'users', ['seed_key'])

    op.execute("""
        UPDATE users SET role_id = (SELECT id FROM (SELECT id FROM roles WHERE code = 'USER') r)
         WHERE role_id = (SELECT id FROM (SELECT id FROM roles WHERE code = 'RECEIVER') r)""")

    if not inspector.has_table('detection_runs'):
        op.create_table(
            'detection_runs',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('run_by', sa.Integer, sa.ForeignKey('users.id')),
            sa.Column('scope', sa.JSON),
            sa.Column('txns_scanned', sa.Integer, nullable=False, server_default='0'),
            sa.Column('txns_flagged', sa.Integer, nullable=False, server_default='0'),
            sa.Column('summary', sa.JSON),
            sa.Column('results', sa.JSON),
            sa.Column('duration_ms', sa.Numeric(10, 2)),
            sa.Column('created_at', mysql.DATETIME(fsp=3), nullable=False,
                      server_default=sa.text('CURRENT_TIMESTAMP(3)')),
            **OPTS)
        op.create_index('ix_detection_runs_created_at', 'detection_runs', ['created_at'])

    from portal.seeders import run_all_seeders
    run_all_seeders(bind)


def downgrade():
    op.drop_index('ix_detection_runs_created_at', 'detection_runs')
    op.drop_table('detection_runs')
    op.drop_constraint('uq_users_seed_key', 'users', type_='unique')
    op.drop_column('users', 'seed_key')
