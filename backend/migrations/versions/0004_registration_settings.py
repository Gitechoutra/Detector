"""Settings for customer self-registration (NEW_USER_OPENING_BALANCE).

Revision ID: 0004_registration_settings
Revises: 0003_views_and_audit_triggers
Create Date: 2026-10-30

Re-runs the settings seeder, which only inserts keys that are missing.
"""
from alembic import op

revision = '0004_registration_settings'
down_revision = '0003_views_and_audit_triggers'
branch_labels = None
depends_on = None


def upgrade():
    from portal.seeders.seed_settings import seed_settings
    seed_settings(op.get_bind())


def downgrade():
    op.execute("DELETE FROM system_settings WHERE setting_key = 'NEW_USER_OPENING_BALANCE'")
