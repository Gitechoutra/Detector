"""Seed master and configuration data.

Revision ID: 0002_seed_master_data
Revises: 0001_create_schema
Create Date: 2026-10-30

Runs portal/seeders: roles, locations, demo logins, simulation accounts, the
nine fraud rules, risk bands, fraud scenarios, watchlist entries and settings.
Every seeder is insert-if-missing, so this is safe on a database that already
holds some of the data and never duplicates or overwrites rows. No
transactions are inserted.
"""
from alembic import op

revision = '0002_seed_master_data'
down_revision = '0001_create_schema'
branch_labels = None
depends_on = None


def upgrade():
    from portal.seeders import run_all_seeders
    run_all_seeders(op.get_bind())


def downgrade():
    # Deliberately does not delete users, accounts or anything they may have
    # changed; removing master data is left to the schema downgrade.
    pass
