"""Run fraud simulations on the real demo accounts.

Revision ID: 0005_simulation_on_demo_accounts
Revises: 0004_registration_settings
Create Date: 2026-10-30

- transactions.risk_explanation: plain-language reason for REVIEW / BLOCKED;
  decline_reason widened to hold it.
- simulation_runs.request_key: idempotency for "run scenario" requests.
- simulation_events.attempt_ids: every payment a scenario attempted.
- notifications.is_simulated: lets the simulation reset remove only its own rows.
- Scenario catalogue now targets the demo accounts (Rahul, Karan → Priya, Amit,
  QuickCash). The old sim.* accounts are left untouched but no longer used.
Additive only; no existing row is deleted.
"""
import sqlalchemy as sa
from alembic import op

revision = '0005_simulation_on_demo_accounts'
down_revision = '0004_registration_settings'
branch_labels = None
depends_on = None


def _has_column(table, column):
    return any(c['name'] == column for c in sa.inspect(op.get_bind()).get_columns(table))


def upgrade():
    if not _has_column('transactions', 'risk_explanation'):
        op.add_column('transactions', sa.Column('risk_explanation', sa.String(500)))
    op.alter_column('transactions', 'decline_reason', existing_type=sa.String(255), type_=sa.String(500))
    if not _has_column('simulation_runs', 'request_key'):
        op.add_column('simulation_runs', sa.Column('request_key', sa.String(64)))
        op.create_unique_constraint('uq_simulation_request_key', 'simulation_runs', ['request_key'])
    if not _has_column('simulation_events', 'attempt_ids'):
        op.add_column('simulation_events', sa.Column('attempt_ids', sa.JSON))
    if not _has_column('notifications', 'is_simulated'):
        op.add_column('notifications', sa.Column('is_simulated', sa.Boolean, nullable=False,
                                                 server_default=sa.false()))

    # The catalogue is code-owned reference data: bring existing rows in line.
    from portal.seeders.seed_scenarios import refresh_scenarios
    refresh_scenarios(op.get_bind())


def downgrade():
    op.drop_column('notifications', 'is_simulated')
    op.drop_column('simulation_events', 'attempt_ids')
    op.drop_constraint('uq_simulation_request_key', 'simulation_runs', type_='unique')
    op.drop_column('simulation_runs', 'request_key')
    op.drop_column('transactions', 'risk_explanation')
