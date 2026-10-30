"""Manual Frauder console.

Revision ID: 0006_manual_frauder_console
Revises: 0005_simulation_on_demo_accounts
Create Date: 2026-10-30

- risk_assessments.rule_trace: what each of the nine rules measured and its
  threshold, fired or not, for the explainable result screen.
- Seeds the designated dormant demo account (suresh@demo.bank) used for R8.
- Automatic scenarios are retired: their catalogue rows are kept (history stays
  readable) but marked inactive. No data is deleted.
"""
import sqlalchemy as sa
from alembic import op

revision = '0006_manual_frauder_console'
down_revision = '0005_simulation_on_demo_accounts'
branch_labels = None
depends_on = None


def upgrade():
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('risk_assessments')}
    if 'rule_trace' not in columns:
        op.add_column('risk_assessments', sa.Column('rule_trace', sa.JSON))

    from portal.seeders.seed_users import seed_users
    seed_users(op.get_bind())
    op.execute('UPDATE fraud_scenarios SET is_active = 0')


def downgrade():
    op.execute('UPDATE fraud_scenarios SET is_active = 1')
    op.drop_column('risk_assessments', 'rule_trace')
