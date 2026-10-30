"""Analytics views and audit-log immutability triggers.

Revision ID: 0003_views_and_audit_triggers
Revises: 0002_seed_master_data
Create Date: 2026-10-30
"""
from alembic import op

revision = '0003_views_and_audit_triggers'
down_revision = '0002_seed_master_data'
branch_labels = None
depends_on = None


def upgrade():
    # Per-rule hit counts and analyst outcomes (precision = confirmed / resolved).
    op.execute("""
        CREATE OR REPLACE VIEW v_rule_performance AS
        SELECT fr.code, fr.name, fr.weight, fr.is_active,
               COUNT(DISTINCT CASE WHEN ra.assessment_type = 'INITIAL' THEN tr.transaction_id END) AS hits,
               COUNT(DISTINCT CASE WHEN ra.assessment_type = 'INITIAL' AND al.resolution = 'CONFIRMED_FRAUD'
                                   THEN tr.transaction_id END) AS confirmed_fraud,
               COUNT(DISTINCT CASE WHEN ra.assessment_type = 'INITIAL' AND al.resolution = 'FALSE_POSITIVE'
                                   THEN tr.transaction_id END) AS false_positive
        FROM fraud_rules fr
        LEFT JOIN triggered_rules tr ON tr.rule_id = fr.id
        LEFT JOIN risk_assessments ra ON ra.id = tr.assessment_id
        LEFT JOIN alerts al ON al.transaction_id = tr.transaction_id
                           AND al.alert_type IN ('TRANSACTION_REVIEW', 'TRANSACTION_BLOCKED')
        GROUP BY fr.id, fr.code, fr.name, fr.weight, fr.is_active
    """)

    # Daily volume and decision mix, using the initial (real-time) decision.
    op.execute("""
        CREATE OR REPLACE VIEW v_daily_transaction_summary AS
        SELECT DATE(t.txn_time) AS day,
               COUNT(*) AS total,
               SUM(ra.decision = 'APPROVED') AS approved,
               SUM(ra.decision = 'REVIEW') AS review,
               SUM(ra.decision = 'BLOCKED') AS blocked,
               SUM(t.amount) AS amount,
               ROUND(AVG(t.latency_ms), 2) AS avg_latency_ms
        FROM transactions t
        JOIN risk_assessments ra ON ra.transaction_id = t.id AND ra.assessment_type = 'INITIAL'
        GROUP BY DATE(t.txn_time)
    """)

    # The audit trail is append-only: the database itself refuses edits and deletes.
    op.execute('DROP TRIGGER IF EXISTS trg_audit_logs_no_update')
    op.execute("""
        CREATE TRIGGER trg_audit_logs_no_update BEFORE UPDATE ON audit_logs
        FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'audit_logs is append-only'
    """)
    op.execute('DROP TRIGGER IF EXISTS trg_audit_logs_no_delete')
    op.execute("""
        CREATE TRIGGER trg_audit_logs_no_delete BEFORE DELETE ON audit_logs
        FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'audit_logs is append-only'
    """)


def downgrade():
    op.execute('DROP TRIGGER IF EXISTS trg_audit_logs_no_delete')
    op.execute('DROP TRIGGER IF EXISTS trg_audit_logs_no_update')
    op.execute('DROP VIEW IF EXISTS v_daily_transaction_summary')
    op.execute('DROP VIEW IF EXISTS v_rule_performance')
