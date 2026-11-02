"""Verification for every flagged payment, OTP after YES, receiver blocking after NO.

Revision ID: 0010_receiver_blocks
Revises: 0009_seed_accounts_engine
Create Date: 2026-11-02

- accounts.status may now be BLOCKED: the account cannot receive money because
  a payer's account owner denied a payment to it.
- receiver_blocks: one record per block with the reason, risk factors, a
  transaction snapshot and the timestamps of the block and of any lift.
- DECISION_MODE is retired: every payment on which a rule fires is held for the
  owner's verification, whatever the score. The setting row is kept, set to
  OWNER_CONFIRM, so nothing reads a stale AUTO value.
No data is deleted.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = '0010_receiver_blocks'
down_revision = '0009_seed_accounts_engine'
branch_labels = None
depends_on = None

OPTS = {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}
DT3 = mysql.DATETIME(fsp=3)


def _account_status_check(values):
    op.execute('ALTER TABLE accounts DROP CHECK ck_account_status')
    op.execute(f'ALTER TABLE accounts ADD CONSTRAINT ck_account_status CHECK (status IN ({values}))')


def upgrade():
    _account_status_check("'ACTIVE','FROZEN','CLOSED','BLOCKED'")
    if not sa.inspect(op.get_bind()).has_table('receiver_blocks'):
        op.create_table(
            'receiver_blocks',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('account_id', sa.Integer, sa.ForeignKey('accounts.id'), nullable=False),
            sa.Column('transaction_id', sa.BigInteger, sa.ForeignKey('transactions.id'), nullable=False),
            sa.Column('reported_by', sa.Integer, sa.ForeignKey('users.id'), nullable=False),
            sa.Column('reason', sa.String(255), nullable=False),
            sa.Column('risk_score', sa.Integer),
            sa.Column('risk_factors', sa.JSON),
            sa.Column('transaction_snapshot', sa.JSON),
            sa.Column('status', sa.String(10), nullable=False, server_default='ACTIVE'),
            sa.Column('blocked_at', DT3, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP(3)')),
            sa.Column('lifted_at', DT3),
            sa.Column('lifted_by', sa.Integer, sa.ForeignKey('users.id')),
            sa.Column('lift_reason', sa.String(255)),
            sa.CheckConstraint("status IN ('ACTIVE','LIFTED')", name='ck_receiver_block_status'),
            **OPTS)
        op.create_index('ix_receiver_block_account_status', 'receiver_blocks', ['account_id', 'status'])
        op.create_index('ix_receiver_blocks_transaction_id', 'receiver_blocks', ['transaction_id'])
    op.execute("""UPDATE system_settings
                     SET setting_value = 'OWNER_CONFIRM',
                         description = 'Retired: every payment on which a fraud rule fires is held for the owner (YES + OTP / NO).'
                   WHERE setting_key = 'DECISION_MODE'""")


def downgrade():
    op.drop_table('receiver_blocks')        # its indexes go with it
    op.execute("UPDATE accounts SET status = 'FROZEN' WHERE status = 'BLOCKED'")
    _account_status_check("'ACTIVE','FROZEN','CLOSED'")
