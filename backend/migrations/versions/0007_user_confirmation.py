"""User confirmation of suspicious payments + manual Frauder target details.

Revision ID: 0007_user_confirmation
Revises: 0006_manual_frauder_console
Create Date: 2026-10-30

- transactions: the account owner's YES/NO confirmation (status, response,
  response time, expiry), the final decision reason, and the simulated
  attacker-supplied details (city, location, device, IP, scenario) entered by
  hand in the Frauder console.
- Confirmation policy settings (expiry, what happens on expiry, hard-block rules).
- Payments already waiting for their owner get a confirmation request.
Columns are only added; no data is deleted.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = '0007_user_confirmation'
down_revision = '0006_manual_frauder_console'
branch_labels = None
depends_on = None

DT3 = mysql.DATETIME(fsp=3)
COLUMNS = (
    ('confirmation_status', sa.String(12)),
    ('confirmation_response', sa.String(3)),
    ('confirmation_responded_at', DT3),
    ('confirmation_expires_at', DT3),
    ('final_reason', sa.String(500)),
    ('simulated_details', sa.JSON),
)


def upgrade():
    bind = op.get_bind()
    existing = {c['name'] for c in sa.inspect(bind).get_columns('transactions')}
    for name, type_ in COLUMNS:
        if name not in existing:
            op.add_column('transactions', sa.Column(name, type_))
    if 'ix_txn_confirmation' not in {i['name'] for i in sa.inspect(bind).get_indexes('transactions')}:
        op.create_index('ix_txn_confirmation', 'transactions', ['confirmation_status', 'confirmation_expires_at'])

    from portal.seeders.seed_settings import seed_settings
    seed_settings(bind)
    # Payments already waiting for their owner: open a confirmation request now.
    op.execute("""
        UPDATE transactions
           SET confirmation_status = 'PENDING',
               confirmation_expires_at = NOW(3) + INTERVAL 30 MINUTE
         WHERE status = 'UNDER_REVIEW' AND review_stage = 'AWAITING_CUSTOMER'
           AND confirmation_status IS NULL""")


def downgrade():
    op.drop_index('ix_txn_confirmation', 'transactions')
    for name, _ in reversed(COLUMNS):
        op.drop_column('transactions', name)
