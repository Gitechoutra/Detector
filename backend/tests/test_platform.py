"""Platform-level checks: Demo Mode, audit trail, migrations."""
from decimal import Decimal

import pytest
from flask_migrate import downgrade, upgrade
from sqlalchemy import text

from portal.extensions import db
from portal.helpers.audit import verify_chain
from portal.models import AuditLog, FraudRule, Transaction, User

from .conftest import balance, login, send


def test_demo_mode_info_and_resets(client, app):
    info = client.get('/api/demo/info').get_json()['data']
    assert {c['role'] for c in info['credentials']} == {'USER', 'RECEIVER', 'DETECTION', 'FRAUDER'}
    assert 'scenarios' not in info
    headers = login(client, 'rahul@demo.bank')
    send(client, headers, 1000)
    assert client.post('/api/demo/reset-attempts', json={'confirm': 'RESET'}).status_code == 200
    assert balance(app, 'rahul@demo.bank') == Decimal('249000')          # genuine payment kept
    assert client.post('/api/demo/reset', json={}).status_code == 422
    assert client.post('/api/demo/reset', json={'confirm': 'RESET'}).status_code == 200
    assert balance(app, 'rahul@demo.bank') == Decimal('250000')
    with app.app_context():
        assert Transaction.query.count() == 0
        db.session.remove()


def test_demo_endpoints_disabled_when_flag_off(client, app):
    app.config['DEMO_MODE_ENABLED'] = False
    try:
        assert client.get('/api/demo/info').status_code == 403
        assert client.post('/api/demo/reset', json={'confirm': 'RESET'}).status_code == 403
        assert client.post('/api/demo/reset-attempts', json={'confirm': 'RESET'}).status_code == 403
    finally:
        app.config['DEMO_MODE_ENABLED'] = True


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
    with app.app_context():
        before = {t: db.session.execute(text(f'SELECT COUNT(*) FROM {t}')).scalar()
                  for t in ('roles', 'users', 'accounts', 'fraud_rules', 'risk_categories', 'fraud_scenarios',
                            'watchlist', 'locations', 'system_settings', 'transactions')}
        rule = FraudRule.query.filter_by(code='R5').first()
        rule.weight = 12  # an admin's change must survive re-running migrations
        db.session.commit()
        db.session.remove()

        downgrade(revision='0001_create_schema')
        upgrade()
        after = {t: db.session.execute(text(f'SELECT COUNT(*) FROM {t}')).scalar() for t in before}
        assert after == before
        assert FraudRule.query.filter_by(code='R5').first().weight == 12
        assert User.query.filter_by(email='rahul@demo.bank').count() == 1
        db.session.remove()
