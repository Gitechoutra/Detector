"""Create the fraud-detection schema.

Revision ID: 0001_create_schema
Revises:
Create Date: 2026-10-30

Every table is created only if it does not already exist, so the migration is
safe on a database that already holds some of these tables and never drops or
rewrites existing data on upgrade.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = '0001_create_schema'
down_revision = None
branch_labels = None
depends_on = None

DT3 = mysql.DATETIME(fsp=3)
DT6 = mysql.DATETIME(fsp=6)
OPTS = {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}


def _now():
    return sa.text('CURRENT_TIMESTAMP')


def _now3():
    return sa.text('CURRENT_TIMESTAMP(3)')


def _create(name, *items):
    if sa.inspect(op.get_bind()).has_table(name):
        return False
    op.create_table(name, *items, **OPTS)
    return True


def _index(table, name, columns, created, unique=False):
    if created:
        op.create_index(name, table, columns, unique=unique)


def upgrade():
    _create('roles',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('code', sa.String(20), nullable=False, unique=True),
            sa.Column('name', sa.String(50), nullable=False),
            sa.Column('description', sa.String(255)),
            sa.Column('created_at', sa.DateTime, nullable=False, server_default=_now()))

    _create('locations',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('city', sa.String(60), nullable=False, unique=True),
            sa.Column('state', sa.String(60), nullable=False),
            sa.Column('latitude', sa.Numeric(9, 6), nullable=False),
            sa.Column('longitude', sa.Numeric(9, 6), nullable=False),
            sa.CheckConstraint('latitude BETWEEN -90 AND 90', name='ck_location_lat'),
            sa.CheckConstraint('longitude BETWEEN -180 AND 180', name='ck_location_lng'))

    created = _create('users',
                      sa.Column('id', sa.Integer, primary_key=True),
                      sa.Column('role_id', sa.Integer, sa.ForeignKey('roles.id'), nullable=False),
                      sa.Column('full_name', sa.String(100), nullable=False),
                      sa.Column('email', sa.String(120), nullable=False, unique=True),
                      sa.Column('phone', sa.String(20)),
                      sa.Column('password_hash', sa.String(255), nullable=False),
                      sa.Column('status', sa.String(20), nullable=False, server_default='ACTIVE'),
                      sa.Column('home_location_id', sa.Integer, sa.ForeignKey('locations.id')),
                      sa.Column('failed_login_count', sa.Integer, nullable=False, server_default='0'),
                      sa.Column('locked_until', sa.DateTime),
                      sa.Column('is_demo', sa.Boolean, nullable=False, server_default=sa.false()),
                      sa.Column('is_simulated', sa.Boolean, nullable=False, server_default=sa.false()),
                      sa.Column('last_login_at', sa.DateTime),
                      sa.Column('created_at', sa.DateTime, nullable=False, server_default=_now()),
                      sa.Column('updated_at', sa.DateTime, nullable=False, server_default=_now()),
                      sa.CheckConstraint("status IN ('ACTIVE','LOCKED','SUSPENDED')", name='ck_user_status'))
    _index('users', 'ix_users_role_id', ['role_id'], created)

    created = _create('accounts',
                      sa.Column('id', sa.Integer, primary_key=True),
                      sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id'), nullable=False),
                      sa.Column('account_number', sa.String(20), nullable=False, unique=True),
                      sa.Column('ifsc', sa.String(11), nullable=False),
                      sa.Column('upi_id', sa.String(60), nullable=False, unique=True),
                      sa.Column('qr_token', sa.String(40), nullable=False, unique=True),
                      sa.Column('account_type', sa.String(20), nullable=False, server_default='SAVINGS'),
                      sa.Column('balance', sa.Numeric(15, 2), nullable=False, server_default='0'),
                      sa.Column('opening_balance', sa.Numeric(15, 2), nullable=False, server_default='0'),
                      sa.Column('status', sa.String(20), nullable=False, server_default='ACTIVE'),
                      sa.Column('last_txn_at', DT3),
                      sa.Column('created_at', sa.DateTime, nullable=False, server_default=_now()),
                      sa.CheckConstraint('balance >= 0', name='ck_account_balance_non_negative'),
                      sa.CheckConstraint("status IN ('ACTIVE','FROZEN','CLOSED')", name='ck_account_status'))
    _index('accounts', 'ix_accounts_user_id', ['user_id'], created)

    _create('devices',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id'), nullable=False),
            sa.Column('fingerprint', sa.String(64), nullable=False),
            sa.Column('device_name', sa.String(150)),
            sa.Column('is_trusted', sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column('first_seen_at', sa.DateTime, nullable=False, server_default=_now()),
            sa.Column('last_seen_at', sa.DateTime, nullable=False, server_default=_now()),
            sa.Column('last_ip', sa.String(45)),
            sa.Column('last_location_id', sa.Integer, sa.ForeignKey('locations.id')),
            sa.UniqueConstraint('user_id', 'fingerprint', name='uq_device_user_fp'))

    _create('fraud_rules',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('code', sa.String(5), nullable=False, unique=True),
            sa.Column('name', sa.String(80), nullable=False),
            sa.Column('description', sa.Text, nullable=False),
            sa.Column('sql_technique', sa.String(150), nullable=False),
            sa.Column('weight', sa.Integer, nullable=False),
            sa.Column('params', sa.JSON, nullable=False),
            sa.Column('default_weight', sa.Integer, nullable=False),
            sa.Column('default_params', sa.JSON, nullable=False),
            sa.Column('is_active', sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column('updated_by', sa.Integer, sa.ForeignKey('users.id')),
            sa.Column('updated_at', sa.DateTime, nullable=False, server_default=_now()),
            sa.Column('created_at', sa.DateTime, nullable=False, server_default=_now()),
            sa.CheckConstraint('weight BETWEEN 0 AND 100', name='ck_rule_weight'))

    _create('risk_categories',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('code', sa.String(10), nullable=False, unique=True),
            sa.Column('label', sa.String(30), nullable=False),
            sa.Column('min_score', sa.Integer, nullable=False),
            sa.Column('max_score', sa.Integer, nullable=False),
            sa.Column('action', sa.String(255), nullable=False),
            sa.Column('color', sa.String(10), nullable=False),
            sa.CheckConstraint('min_score BETWEEN 0 AND 100 AND max_score BETWEEN 0 AND 100 '
                               'AND min_score <= max_score', name='ck_risk_band_range'))

    _create('fraud_scenarios',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('code', sa.String(40), nullable=False, unique=True),
            sa.Column('name', sa.String(100), nullable=False),
            sa.Column('description', sa.Text, nullable=False),
            sa.Column('victim_email', sa.String(120), nullable=False),
            sa.Column('expected_rules', sa.JSON, nullable=False),
            sa.Column('expected_decision', sa.String(10), nullable=False),
            sa.Column('is_fraud', sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column('display_order', sa.Integer, nullable=False, server_default='0'),
            sa.Column('is_active', sa.Boolean, nullable=False, server_default=sa.true()))

    _create('simulation_runs',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('started_by', sa.Integer, sa.ForeignKey('users.id'), nullable=False),
            sa.Column('mode', sa.String(10), nullable=False),
            sa.Column('status', sa.String(12), nullable=False, server_default='RUNNING'),
            sa.Column('interval_seconds', sa.Integer),
            sa.Column('scenarios_executed', sa.Integer, nullable=False, server_default='0'),
            sa.Column('started_at', sa.DateTime, nullable=False, server_default=_now()),
            sa.Column('ended_at', sa.DateTime))

    created = _create('transactions',
                      sa.Column('id', sa.BigInteger, primary_key=True),
                      sa.Column('txn_ref', sa.String(24), nullable=False, unique=True),
                      sa.Column('idempotency_key', sa.String(64)),
                      sa.Column('sender_account_id', sa.Integer, sa.ForeignKey('accounts.id'), nullable=False),
                      sa.Column('receiver_account_id', sa.Integer, sa.ForeignKey('accounts.id'), nullable=False),
                      sa.Column('amount', sa.Numeric(15, 2), nullable=False),
                      sa.Column('payment_method', sa.String(15), nullable=False),
                      sa.Column('remarks', sa.String(140)),
                      sa.Column('status', sa.String(15), nullable=False, server_default='PROCESSING'),
                      sa.Column('review_stage', sa.String(20)),
                      sa.Column('risk_score', sa.Integer),
                      sa.Column('decision', sa.String(10)),
                      sa.Column('decline_reason', sa.String(255)),
                      sa.Column('device_id', sa.Integer, sa.ForeignKey('devices.id')),
                      sa.Column('ip_address', sa.String(45)),
                      sa.Column('location_id', sa.Integer, sa.ForeignKey('locations.id')),
                      sa.Column('step_up_verified', sa.Boolean, nullable=False, server_default=sa.false()),
                      sa.Column('is_simulated', sa.Boolean, nullable=False, server_default=sa.false()),
                      sa.Column('simulation_run_id', sa.Integer, sa.ForeignKey('simulation_runs.id')),
                      sa.Column('scenario_code', sa.String(40)),
                      sa.Column('is_fraud_label', sa.Boolean),
                      sa.Column('txn_time', DT3, nullable=False),
                      sa.Column('decided_at', DT3),
                      sa.Column('completed_at', DT3),
                      sa.Column('latency_ms', sa.Numeric(10, 2)),
                      sa.Column('created_at', DT3, nullable=False, server_default=_now3()),
                      sa.UniqueConstraint('sender_account_id', 'idempotency_key', name='uq_txn_idempotency'),
                      sa.CheckConstraint('amount > 0', name='ck_txn_amount_positive'),
                      sa.CheckConstraint('sender_account_id <> receiver_account_id', name='ck_txn_distinct_accounts'),
                      sa.CheckConstraint("payment_method IN ('UPI','QR','BANK_TRANSFER')", name='ck_txn_method'),
                      sa.CheckConstraint("status IN ('PROCESSING','COMPLETED','UNDER_REVIEW','BLOCKED',"
                                         "'DECLINED','CANCELLED')", name='ck_txn_status'),
                      sa.CheckConstraint('risk_score IS NULL OR risk_score BETWEEN 0 AND 100', name='ck_txn_score'))
    # Composite (account, time) indexes serve every per-account time-window rule.
    _index('transactions', 'ix_txn_sender_time', ['sender_account_id', 'txn_time'], created)
    _index('transactions', 'ix_txn_receiver_time', ['receiver_account_id', 'txn_time'], created)
    _index('transactions', 'ix_txn_status', ['status'], created)
    _index('transactions', 'ix_txn_time', ['txn_time'], created)

    created = _create('risk_assessments',
                      sa.Column('id', sa.BigInteger, primary_key=True),
                      sa.Column('transaction_id', sa.BigInteger,
                                sa.ForeignKey('transactions.id', ondelete='CASCADE'), nullable=False),
                      sa.Column('assessment_type', sa.String(20), nullable=False),
                      sa.Column('risk_score', sa.Integer, nullable=False),
                      sa.Column('decision', sa.String(10), nullable=False),
                      sa.Column('rules_evaluated', sa.Integer, nullable=False),
                      sa.Column('rules_triggered', sa.Integer, nullable=False),
                      sa.Column('mitigations', sa.JSON),
                      sa.Column('latency_ms', sa.Numeric(10, 2)),
                      sa.Column('assessed_by', sa.Integer, sa.ForeignKey('users.id')),
                      sa.Column('notes', sa.String(255)),
                      sa.Column('created_at', DT3, nullable=False, server_default=_now3()),
                      sa.CheckConstraint("decision IN ('APPROVED','REVIEW','BLOCKED')", name='ck_ra_decision'))
    _index('risk_assessments', 'ix_risk_assessments_transaction_id', ['transaction_id'], created)

    created = _create('triggered_rules',
                      sa.Column('id', sa.BigInteger, primary_key=True),
                      sa.Column('transaction_id', sa.BigInteger,
                                sa.ForeignKey('transactions.id', ondelete='CASCADE'), nullable=False),
                      sa.Column('assessment_id', sa.BigInteger,
                                sa.ForeignKey('risk_assessments.id', ondelete='CASCADE'), nullable=False),
                      sa.Column('rule_id', sa.Integer, sa.ForeignKey('fraud_rules.id'), nullable=False),
                      sa.Column('rule_code', sa.String(5), nullable=False),
                      sa.Column('weight_applied', sa.Integer, nullable=False),
                      sa.Column('reason', sa.String(255), nullable=False),
                      sa.Column('evidence', sa.JSON),
                      sa.Column('created_at', DT3, nullable=False, server_default=_now3()))
    _index('triggered_rules', 'ix_triggered_rules_transaction_id', ['transaction_id'], created)
    _index('triggered_rules', 'ix_hit_rule_time', ['rule_id', 'created_at'], created)

    created = _create('verification_challenges',
                      sa.Column('id', sa.BigInteger, primary_key=True),
                      sa.Column('transaction_id', sa.BigInteger,
                                sa.ForeignKey('transactions.id', ondelete='CASCADE'), nullable=False),
                      sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id'), nullable=False),
                      sa.Column('otp_hash', sa.String(255), nullable=False),
                      sa.Column('attempts', sa.Integer, nullable=False, server_default='0'),
                      sa.Column('max_attempts', sa.Integer, nullable=False, server_default='3'),
                      sa.Column('status', sa.String(10), nullable=False, server_default='PENDING'),
                      sa.Column('expires_at', sa.DateTime, nullable=False),
                      sa.Column('created_at', sa.DateTime, nullable=False, server_default=_now()),
                      sa.Column('verified_at', sa.DateTime))
    _index('verification_challenges', 'ix_verification_challenges_transaction_id', ['transaction_id'], created)

    created = _create('login_attempts',
                      sa.Column('id', sa.BigInteger, primary_key=True),
                      sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id')),
                      sa.Column('email', sa.String(120), nullable=False),
                      sa.Column('success', sa.Boolean, nullable=False),
                      sa.Column('failure_reason', sa.String(50)),
                      sa.Column('device_id', sa.Integer, sa.ForeignKey('devices.id')),
                      sa.Column('fingerprint', sa.String(64)),
                      sa.Column('ip_address', sa.String(45)),
                      sa.Column('location_id', sa.Integer, sa.ForeignKey('locations.id')),
                      sa.Column('is_new_device', sa.Boolean, nullable=False, server_default=sa.false()),
                      sa.Column('is_simulated', sa.Boolean, nullable=False, server_default=sa.false()),
                      sa.Column('created_at', DT3, nullable=False, server_default=_now3()))
    _index('login_attempts', 'ix_login_user_time', ['user_id', 'created_at'], created)
    _index('login_attempts', 'ix_login_attempts_created_at', ['created_at'], created)

    created = _create('security_events',
                      sa.Column('id', sa.BigInteger, primary_key=True),
                      sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id')),
                      sa.Column('event_type', sa.String(40), nullable=False),
                      sa.Column('severity', sa.String(10), nullable=False, server_default='LOW'),
                      sa.Column('description', sa.String(255), nullable=False),
                      sa.Column('device_id', sa.Integer, sa.ForeignKey('devices.id')),
                      sa.Column('ip_address', sa.String(45)),
                      sa.Column('location_id', sa.Integer, sa.ForeignKey('locations.id')),
                      sa.Column('transaction_id', sa.BigInteger,
                                sa.ForeignKey('transactions.id', ondelete='SET NULL')),
                      sa.Column('is_simulated', sa.Boolean, nullable=False, server_default=sa.false()),
                      sa.Column('created_at', DT3, nullable=False, server_default=_now3()))
    _index('security_events', 'ix_secevent_user_type_time', ['user_id', 'event_type', 'created_at'], created)
    _index('security_events', 'ix_security_events_created_at', ['created_at'], created)

    _create('watchlist',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('entity_type', sa.String(15), nullable=False),
            sa.Column('entity_value', sa.String(120), nullable=False),
            sa.Column('reason', sa.String(255), nullable=False),
            sa.Column('source', sa.String(10), nullable=False, server_default='MANUAL'),
            sa.Column('is_active', sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column('added_by', sa.Integer, sa.ForeignKey('users.id')),
            sa.Column('created_at', sa.DateTime, nullable=False, server_default=_now()),
            sa.UniqueConstraint('entity_type', 'entity_value', name='uq_watchlist_entity'),
            sa.CheckConstraint("entity_type IN ('ACCOUNT','UPI','DEVICE','IP')", name='ck_watchlist_type'))

    created = _create('alerts',
                      sa.Column('id', sa.BigInteger, primary_key=True),
                      sa.Column('transaction_id', sa.BigInteger,
                                sa.ForeignKey('transactions.id', ondelete='CASCADE')),
                      sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id')),
                      sa.Column('alert_type', sa.String(25), nullable=False),
                      sa.Column('severity', sa.String(10), nullable=False),
                      sa.Column('title', sa.String(150), nullable=False),
                      sa.Column('message', sa.Text, nullable=False),
                      sa.Column('risk_score', sa.Integer),
                      sa.Column('status', sa.String(15), nullable=False, server_default='OPEN'),
                      sa.Column('resolution', sa.String(20)),
                      sa.Column('assigned_to', sa.Integer, sa.ForeignKey('users.id')),
                      sa.Column('analyst_notes', sa.Text),
                      sa.Column('is_simulated', sa.Boolean, nullable=False, server_default=sa.false()),
                      sa.Column('created_at', DT3, nullable=False, server_default=_now3()),
                      sa.Column('updated_at', DT3, nullable=False, server_default=_now3()),
                      sa.Column('resolved_at', DT3),
                      sa.CheckConstraint("status IN ('OPEN','INVESTIGATING','RESOLVED')", name='ck_alert_status'))
    _index('alerts', 'ix_alerts_transaction_id', ['transaction_id'], created)
    _index('alerts', 'ix_alert_status_time', ['status', 'created_at'], created)
    _index('alerts', 'ix_alerts_created_at', ['created_at'], created)

    created = _create('notifications',
                      sa.Column('id', sa.BigInteger, primary_key=True),
                      sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id'), nullable=False),
                      sa.Column('title', sa.String(150), nullable=False),
                      sa.Column('message', sa.Text, nullable=False),
                      sa.Column('category', sa.String(10), nullable=False, server_default='INFO'),
                      sa.Column('transaction_id', sa.BigInteger,
                                sa.ForeignKey('transactions.id', ondelete='SET NULL')),
                      sa.Column('is_read', sa.Boolean, nullable=False, server_default=sa.false()),
                      sa.Column('created_at', DT3, nullable=False, server_default=_now3()))
    _index('notifications', 'ix_notif_user_read', ['user_id', 'is_read', 'created_at'], created)

    created = _create('simulation_events',
                      sa.Column('id', sa.BigInteger, primary_key=True),
                      sa.Column('run_id', sa.Integer, sa.ForeignKey('simulation_runs.id', ondelete='CASCADE'),
                                nullable=False),
                      sa.Column('scenario_id', sa.Integer, sa.ForeignKey('fraud_scenarios.id'), nullable=False),
                      sa.Column('transaction_id', sa.BigInteger,
                                sa.ForeignKey('transactions.id', ondelete='SET NULL')),
                      sa.Column('detected', sa.Boolean, nullable=False),
                      sa.Column('risk_score', sa.Integer),
                      sa.Column('decision', sa.String(10), nullable=False),
                      sa.Column('triggered_rules', sa.JSON, nullable=False),
                      sa.Column('expected_rules', sa.JSON, nullable=False),
                      sa.Column('steps', sa.JSON, nullable=False),
                      sa.Column('created_at', DT3, nullable=False, server_default=_now3()))
    _index('simulation_events', 'ix_simulation_events_run_id', ['run_id'], created)

    created = _create('audit_logs',
                      sa.Column('id', sa.BigInteger, primary_key=True),
                      sa.Column('actor_user_id', sa.Integer, sa.ForeignKey('users.id')),
                      sa.Column('actor_role', sa.String(20)),
                      sa.Column('action', sa.String(60), nullable=False),
                      sa.Column('entity_type', sa.String(40)),
                      sa.Column('entity_id', sa.String(40)),
                      sa.Column('details', sa.JSON),
                      sa.Column('ip_address', sa.String(45)),
                      sa.Column('prev_hash', sa.CHAR(64), nullable=False),
                      sa.Column('row_hash', sa.CHAR(64), nullable=False),
                      sa.Column('created_at', DT6, nullable=False))
    _index('audit_logs', 'ix_audit_logs_created_at', ['created_at'], created)

    _create('system_settings',
            sa.Column('setting_key', sa.String(60), primary_key=True),
            sa.Column('setting_value', sa.String(255), nullable=False),
            sa.Column('description', sa.String(255)))


def downgrade():
    for table in ('system_settings', 'audit_logs', 'simulation_events', 'notifications', 'alerts', 'watchlist',
                  'security_events', 'login_attempts', 'verification_challenges', 'triggered_rules',
                  'risk_assessments', 'transactions', 'simulation_runs', 'fraud_scenarios', 'risk_categories',
                  'fraud_rules', 'devices', 'accounts', 'users', 'locations', 'roles'):
        op.execute(f'DROP TABLE IF EXISTS {table}')
