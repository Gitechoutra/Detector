"""Platform-level checks: Demo Mode removed, audit trail, migrations."""

import pytest
from flask_migrate import downgrade, upgrade
from sqlalchemy import text

from portal.extensions import db
from portal.helpers.audit import verify_chain
from portal.models import AuditLog, FraudRule, User
from portal.seeders.seed_transactions import HISTORY

from .conftest import login, send


def test_demo_mode_is_gone(client):
    for method, url in (('get', '/api/demo/info'), ('post', '/api/demo/reset'), ('post', '/api/demo/unlock'),
                        ('post', '/api/demo/reset-attempts')):
        assert getattr(client, method)(url, json={'confirm': 'RESET'}).status_code == 404
    assert 'demo_mode' not in client.get('/api/health').get_json()['data']


def test_audit_trail_is_chained_and_append_only(client, app):
    analyst = login(client, 'analyst@demo.bank')
    with app.app_context():
        before = AuditLog.query.filter_by(action='RULE_UPDATED').count()
        db.session.remove()
    client.put('/api/detection/rules/R2', headers=analyst, json={'weight': 30})
    assert client.get('/api/security/audit/verify', headers=analyst).get_json()['data']['valid'] is True
    with app.app_context():
        assert AuditLog.query.filter_by(action='RULE_UPDATED').count() == before + 1
        with pytest.raises(Exception, match='append-only'):
            db.session.execute(text("UPDATE audit_logs SET action = 'X'"))
        db.session.rollback()
        with pytest.raises(Exception, match='append-only'):
            db.session.execute(text('DELETE FROM audit_logs'))
        db.session.rollback()
        assert verify_chain()['valid'] is True
        db.session.remove()


def test_migrations_are_repeatable_without_duplicates_or_data_loss(client, app):
    headers = login(client, 'rahul@demo.bank')
    send(client, headers, 1234)
    tables = ('roles', 'users', 'accounts', 'fraud_rules', 'risk_categories', 'fraud_scenarios', 'watchlist',
              'locations', 'system_settings')
    real_txns = "SELECT COUNT(*) FROM transactions WHERE txn_ref NOT LIKE 'SEED-%'"
    seeded_txns = "SELECT COUNT(*) FROM transactions WHERE txn_ref LIKE 'SEED-%'"
    with app.app_context():
        before = {t: db.session.execute(text(f'SELECT COUNT(*) FROM {t}')).scalar() for t in tables}
        real_before = db.session.execute(text(real_txns)).scalar()
        rule = FraudRule.query.filter_by(code='R5').first()
        rule.weight = 12  # an admin's change must survive re-running migrations
        db.session.commit()
        db.session.remove()

        for _ in range(2):
            downgrade(revision='0008_user_authorization')   # re-runs 0009 and every seeder
            upgrade()
            after = {t: db.session.execute(text(f'SELECT COUNT(*) FROM {t}')).scalar() for t in tables}
            assert after == before
            assert db.session.execute(text(real_txns)).scalar() == real_before
            assert db.session.execute(text(seeded_txns)).scalar() == len(HISTORY)     # restored once, never doubled
            assert FraudRule.query.filter_by(code='R5').first().weight == 12
            assert User.query.filter_by(email='rahul@demo.bank').count() == 1
            assert User.query.filter_by(seed_key='rahul').count() == 1
            db.session.remove()
