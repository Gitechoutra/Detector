"""Every fraud-flagged payment waits for its owner's YES/NO.

Revision ID: 0008_user_authorization
Revises: 0007_user_confirmation
Create Date: 2026-10-30

- transactions.status may now be EXPIRED (owner did not answer in time; never authorized).
- Confirmation policy defaults change: no rule is a hard block any more (a YES
  authorizes the payment), and an unanswered request EXPIREs. Settings are only
  changed while they still hold the previous defaults.
No data is deleted.
"""
from alembic import op

revision = '0008_user_authorization'
down_revision = '0007_user_confirmation'
branch_labels = None
depends_on = None

OLD = "'PROCESSING','COMPLETED','UNDER_REVIEW','BLOCKED','DECLINED','CANCELLED'"
NEW = OLD + ",'EXPIRED'"


def _status_check(values):
    op.execute('ALTER TABLE transactions DROP CHECK ck_txn_status')
    op.execute(f'ALTER TABLE transactions ADD CONSTRAINT ck_txn_status CHECK (status IN ({values}))')


def upgrade():
    _status_check(NEW)
    op.execute("""UPDATE system_settings SET setting_value = ''
                   WHERE setting_key = 'CONFIRMATION_HARD_BLOCK_RULES' AND setting_value = 'R6'""")
    op.execute("""UPDATE system_settings SET setting_value = 'EXPIRE'
                   WHERE setting_key = 'CONFIRMATION_EXPIRY_ACTION' AND setting_value = 'BLOCK'""")
    op.execute("""UPDATE system_settings
                     SET description = 'Unanswered confirmation: EXPIRE it (default), BLOCK it, or HOLD it for the fraud team. Never approved.'
                   WHERE setting_key = 'CONFIRMATION_EXPIRY_ACTION'""")
    op.execute("""UPDATE system_settings
                     SET description = 'Comma-separated rules treated as an absolute restriction: the payment is blocked and a YES cannot authorize it. Empty = none.'
                   WHERE setting_key = 'CONFIRMATION_HARD_BLOCK_RULES'""")


def downgrade():
    op.execute("UPDATE transactions SET status = 'BLOCKED' WHERE status = 'EXPIRED'")
    _status_check(OLD)
