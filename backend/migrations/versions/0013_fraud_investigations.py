"""Fraud investigation queue: temporary blocks, detective decisions, audit trail.

Revision ID: 0013_fraud_investigations
Revises: 0012_revoked_tokens
Create Date: 2026-11-03

- accounts.status may now be TEMPORARILY_BLOCKED (cannot send; set automatically
  when a payment reaches the blocking threshold) or PERMANENTLY_BLOCKED (cannot
  send or receive; set by a detective).
- investigation_cases: one case per restricted account and fraud event.
- investigation_actions: append-only decision history. Triggers reject UPDATE
  always and DELETE unless the session variable @fs_maintenance = 1 (set only
  by the test-suite reset).
- Receivers already blocked after an owner's NO get an open case, so every
  restricted account is in the queue.
No data is deleted.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = '0013_fraud_investigations'
down_revision = '0012_revoked_tokens'
branch_labels = None
depends_on = None

DT3 = mysql.DATETIME(fsp=3)
OPTS = {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}
STATUSES = "'ACTIVE','FROZEN','CLOSED','BLOCKED','TEMPORARILY_BLOCKED','PERMANENTLY_BLOCKED'"


def _account_status_check(values):
    op.execute('ALTER TABLE accounts DROP CHECK ck_account_status')
    op.execute(f'ALTER TABLE accounts ADD CONSTRAINT ck_account_status CHECK (status IN ({values}))')


def upgrade():
    _account_status_check(STATUSES)
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table('investigation_cases'):
        op.create_table(
            'investigation_cases',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('case_ref', sa.String(20), nullable=False, unique=True),
            sa.Column('account_id', sa.Integer, sa.ForeignKey('accounts.id'), nullable=False),
            sa.Column('transaction_id', sa.BigInteger, sa.ForeignKey('transactions.id', ondelete='SET NULL')),
            sa.Column('case_type', sa.String(20), nullable=False),
            sa.Column('status', sa.String(20), nullable=False, server_default='TEMPORARILY_BLOCKED'),
            sa.Column('detection_reason', sa.String(500), nullable=False),
            sa.Column('risk_score', sa.Integer),
            sa.Column('risk_factors', sa.JSON),
            sa.Column('transaction_snapshot', sa.JSON),
            sa.Column('account_status_at_open', sa.String(20)),
            sa.Column('assigned_to', sa.Integer, sa.ForeignKey('users.id')),
            sa.Column('decision', sa.String(20)),
            sa.Column('decision_reason', sa.String(500)),
            sa.Column('decided_by', sa.Integer, sa.ForeignKey('users.id')),
            sa.Column('opened_at', DT3, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP(3)')),
            sa.Column('review_started_at', DT3),
            sa.Column('decided_at', DT3),
            sa.UniqueConstraint('account_id', 'transaction_id', 'case_type', name='uq_case_event'),
            sa.CheckConstraint("status IN ('TEMPORARILY_BLOCKED','UNDER_INVESTIGATION','PERMANENTLY_BLOCKED',"
                               "'APPROVED','RESOLVED')", name='ck_case_status'),
            sa.CheckConstraint("case_type IN ('HIGH_RISK_PAYMENT','RECEIVER_REPORTED')", name='ck_case_type'),
            **OPTS)
        op.create_index('ix_investigation_cases_account_id', 'investigation_cases', ['account_id'])
        op.create_index('ix_case_status_opened', 'investigation_cases', ['status', 'opened_at'])
    if not inspector.has_table('investigation_actions'):
        op.create_table(
            'investigation_actions',
            sa.Column('id', sa.BigInteger, primary_key=True),
            sa.Column('case_id', sa.Integer, sa.ForeignKey('investigation_cases.id'), nullable=False),
            sa.Column('detective_id', sa.Integer, sa.ForeignKey('users.id')),
            sa.Column('account_id', sa.Integer, sa.ForeignKey('accounts.id'), nullable=False),
            sa.Column('action', sa.String(30), nullable=False),
            sa.Column('previous_case_status', sa.String(20)),
            sa.Column('new_case_status', sa.String(20), nullable=False),
            sa.Column('previous_account_status', sa.String(20)),
            sa.Column('new_account_status', sa.String(20)),
            sa.Column('reason', sa.String(500)),
            sa.Column('created_at', DT3, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP(3)')),
            **OPTS)
        op.create_index('ix_investigation_actions_case_id', 'investigation_actions', ['case_id'])
    for name, event, rule in (
            ('trg_investigation_actions_no_update', 'UPDATE', "SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = "
                                                              "'investigation_actions is append-only';"),
            ('trg_investigation_actions_no_delete', 'DELETE', "IF COALESCE(@fs_maintenance, 0) <> 1 THEN "
                                                              "SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = "
                                                              "'investigation_actions is append-only'; END IF;")):
        op.execute(f'DROP TRIGGER IF EXISTS {name}')
        op.execute(f'CREATE TRIGGER {name} BEFORE {event} ON investigation_actions FOR EACH ROW BEGIN {rule} END')

    # Receivers already blocked after an owner's NO: open their case now.
    bind = op.get_bind()
    rows = bind.execute(sa.text("""
        SELECT b.account_id, b.transaction_id, b.reason, b.risk_score, b.risk_factors, b.transaction_snapshot,
               b.blocked_at, a.status
          FROM receiver_blocks b JOIN accounts a ON a.id = b.account_id
         WHERE b.status = 'ACTIVE'
           AND NOT EXISTS (SELECT 1 FROM investigation_cases c WHERE c.account_id = b.account_id
                           AND c.transaction_id = b.transaction_id AND c.case_type = 'RECEIVER_REPORTED')""")).all()
    for row in rows:
        next_id = bind.execute(sa.text('SELECT COALESCE(MAX(id), 0) + 1 FROM investigation_cases')).scalar()
        bind.execute(sa.text("""
            INSERT INTO investigation_cases (case_ref, account_id, transaction_id, case_type, status,
                   detection_reason, risk_score, risk_factors, transaction_snapshot, account_status_at_open, opened_at)
            VALUES (:ref, :acc, :txn, 'RECEIVER_REPORTED', 'TEMPORARILY_BLOCKED', :reason, :score, :factors, :snap,
                    :status, :at)"""), {
            'ref': f'CASE-{next_id:06d}', 'acc': row.account_id, 'txn': row.transaction_id, 'reason': row.reason,
            'score': row.risk_score, 'factors': row.risk_factors, 'snap': row.transaction_snapshot,
            'status': row.status, 'at': row.blocked_at})
        case_id = bind.execute(sa.text('SELECT LAST_INSERT_ID()')).scalar()
        bind.execute(sa.text("""
            INSERT INTO investigation_actions (case_id, account_id, action, new_case_status, new_account_status,
                   reason, created_at)
            VALUES (:case, :acc, 'CASE_OPENED', 'TEMPORARILY_BLOCKED', :status, :reason, :at)"""),
            {'case': case_id, 'acc': row.account_id, 'status': row.status,
             'reason': 'Opened for a receiver blocked before the investigation queue existed.', 'at': row.blocked_at})


def downgrade():
    op.execute('DROP TRIGGER IF EXISTS trg_investigation_actions_no_delete')
    op.execute('DROP TRIGGER IF EXISTS trg_investigation_actions_no_update')
    op.drop_table('investigation_actions')
    op.drop_table('investigation_cases')
    op.execute("UPDATE accounts SET status = 'FROZEN' WHERE status IN ('TEMPORARILY_BLOCKED','PERMANENTLY_BLOCKED')")
    _account_status_check("'ACTIVE','FROZEN','CLOSED','BLOCKED'")
