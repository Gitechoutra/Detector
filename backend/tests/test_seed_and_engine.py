"""Dummy accounts kept in sync with .env, the seeded sample history, and the
Detection Engine that replays the rules over it without changing anything."""
import pytest
from sqlalchemy import text

from portal.extensions import db
from portal.models import DetectionRun, RiskAssessment, Transaction, User
from portal.seeders.seed_transactions import HISTORY, seed_transactions
from portal.seeders.seed_users import ACCOUNTS, configured_credentials, seed_users

from .conftest import login


@pytest.fixture
def env(app):
    """Point the seeder at a fake .env, then put every account back as it was."""
    def apply(**values):
        app.config['SEED_ACCOUNT_ENV'] = values
        with app.app_context():
            report = seed_users(db.session.connection())
            db.session.commit()
            db.session.remove()
        return report
    yield apply
    apply()                                    # back to the .env.example defaults


def _users(app):
    with app.app_context():
        rows = db.session.execute(text('SELECT seed_key, email FROM users WHERE seed_key IS NOT NULL')).all()
        total = User.query.count()
        db.session.remove()
        return dict(rows), total


# ── Accounts and credentials ────────────────────────────────────────────────

def test_every_dummy_account_is_seeded_once_with_a_key(app):
    keys, _ = _users(app)
    assert set(keys) == {a.key for a in ACCOUNTS}
    assert keys['rahul'] == 'rahul@demo.bank' and keys['analyst'] == 'analyst@demo.bank'


def test_changed_env_credentials_are_synchronised_without_duplicates(client, app, env):
    _, total = _users(app)
    report = env(SEED_RAHUL_EMAIL='Rahul.New@Example.com', SEED_RAHUL_PASSWORD='N3w-Secret!',
                 SEED_ANALYST_PASSWORD='Analyst#2026')
    assert report == {'rahul': ['email', 'password'], 'analyst': ['password']}
    keys, after = _users(app)
    assert after == total and keys['rahul'] == 'rahul.new@example.com'      # renamed, not duplicated

    login(client, 'rahul.new@example.com', password='N3w-Secret!')
    login(client, 'rahul@demo.bank', password='Rahul@123', expect=401)        # old credentials no longer work
    login(client, 'analyst@demo.bank', password='Analyst#2026')
    login(client, 'analyst@demo.bank', password='Detect@123', expect=401)
    assert env(SEED_RAHUL_EMAIL='Rahul.New@Example.com', SEED_RAHUL_PASSWORD='N3w-Secret!',
               SEED_ANALYST_PASSWORD='Analyst#2026') == {}                    # nothing left to change


def test_sync_keeps_the_same_account_and_its_money(client, app, env):
    with app.app_context():
        before = User.query.filter_by(seed_key='karan').one().primary_account.id
        db.session.remove()
    env(SEED_KARAN_EMAIL='karan.m@example.com')
    with app.app_context():
        user = User.query.filter_by(seed_key='karan').one()
        assert user.email == 'karan.m@example.com' and user.primary_account.id == before
        db.session.remove()


def test_email_already_used_by_someone_else_is_not_taken(app, env):
    report = env(SEED_KARAN_EMAIL='priya@demo.bank')
    assert 'karan' not in report
    keys, _ = _users(app)
    assert keys['karan'] == 'karan@demo.bank' and keys['priya'] == 'priya@demo.bank'


def test_password_typed_into_the_database_is_rehashed(client, app):
    with app.app_context():
        db.session.execute(text("UPDATE users SET password_hash = 'Rahul@123' WHERE seed_key = 'rahul'"))
        db.session.commit()
        assert seed_users(db.session.connection()) == {'rahul': ['password']}
        db.session.commit()
        db.session.remove()
    login(client, 'rahul@demo.bank')


def test_credentials_fall_back_to_env_example(app):
    with app.app_context():
        creds = configured_credentials()
    assert creds['frauder'] == ('frauder@demo.bank', 'Fraud@123')


def test_retired_receiver_role_is_upgraded_to_user(app):
    with app.app_context():
        db.session.execute(text("UPDATE users SET role_id = (SELECT id FROM roles WHERE code = 'RECEIVER') "
                                "WHERE seed_key = 'priya'"))
        db.session.commit()
        assert seed_users(db.session.connection()) == {'priya': ['role']}
        db.session.commit()
        assert User.query.filter_by(seed_key='priya').one().role.code == 'USER'
        db.session.remove()


def test_no_account_creation_endpoint_for_dummy_accounts(client):
    detection = login(client, 'analyst@demo.bank')
    assert client.post('/api/detection/accounts', headers=detection, json={}).status_code in (404, 405)


# ── Seeded sample history ───────────────────────────────────────────────────

def test_sample_history_is_seeded_once_and_never_moves_money(app):
    with app.app_context():
        balances = dict(db.session.execute(text('SELECT id, balance FROM accounts')).all())
        assert seed_transactions(db.session.connection()) == len(HISTORY)
        assert seed_transactions(db.session.connection()) == 0                 # idempotent
        db.session.commit()
        assert Transaction.query.filter(Transaction.txn_ref.like('SEED-%')).count() == len(HISTORY)
        assert dict(db.session.execute(text('SELECT id, balance FROM accounts')).all()) == balances
        suresh = User.query.filter_by(seed_key='suresh').one().primary_account
        assert suresh.last_txn_at is None                                      # still dormant for R8
        db.session.remove()


# ── Detection Engine ────────────────────────────────────────────────────────

def _seed_history(app):
    with app.app_context():
        seed_transactions(db.session.connection())
        db.session.commit()
        db.session.remove()


def test_engine_finds_the_seeded_patterns_without_changing_transactions(client, app):
    _seed_history(app)
    with app.app_context():
        assessments = RiskAssessment.query.count()
        db.session.remove()
    analyst = login(client, 'analyst@demo.bank')
    res = client.post('/api/detection/engine/run', headers=analyst, json={})
    assert res.status_code == 201, res.get_json()
    data = res.get_json()['data']
    assert data['txns_scanned'] == len(HISTORY)
    fired = {r['code'] for row in data['results'] for r in row['rules']}
    assert {'R1', 'R2', 'R3', 'R5', 'R6', 'R7'} <= fired
    counts = {r['code']: r['count'] for r in data['summary']['by_rule']}
    assert counts['R2'] == 1 and counts['R7'] == 1 and counts['R8'] == 0
    assert data['txns_flagged'] == sum(1 for row in data['results'] if row['rules'])
    assert data['results'][0]['score'] == max(row['score'] for row in data['results'])   # highest risk first

    with app.app_context():                                       # the scan saved nothing on the payments
        assert RiskAssessment.query.count() == assessments
        assert Transaction.query.filter(Transaction.risk_score.isnot(None)).count() == 0
        assert DetectionRun.query.count() == 1
        db.session.remove()

    again = client.get(f"/api/detection/engine/runs/{data['id']}", headers=analyst).get_json()['data']
    assert again['results'] == data['results']
    overview = client.get('/api/detection/engine', headers=analyst).get_json()['data']
    assert overview['runs'][0]['id'] == data['id'] and 'results' not in overview['runs'][0]
    assert {a['seed_key'] for a in overview['accounts']} == {'rahul', 'karan', 'priya', 'amit', 'quickcash',
                                                             'suresh'}


def test_engine_scope_filters(client, app):
    _seed_history(app)
    analyst = login(client, 'analyst@demo.bank')
    accounts = client.get('/api/detection/engine', headers=analyst).get_json()['data']['accounts']
    karan = next(a for a in accounts if a['seed_key'] == 'karan')['account_id']
    data = client.post('/api/detection/engine/run', headers=analyst, json={'account_id': karan}).get_json()['data']
    assert {row['sender'] for row in data['results']} == {'Karan Mehta'}
    assert {r['code'] for row in data['results'] for r in row['rules']} == {'R1', 'R2'}
    recent = client.post('/api/detection/engine/run', headers=analyst, json={'days': 30}).get_json()['data']
    assert recent['txns_scanned'] == sum(1 for h in HISTORY if h[0] <= 30) and recent['txns_flagged'] == 0


def test_engine_reports_live_payments_against_their_stored_result(client, app):
    rahul = login(client, 'rahul@demo.bank')
    client.post('/api/transactions/send', headers=rahul, json={'payment_method': 'UPI',
                                                               'upi_id': 'quickcash@fsbank', 'amount': 1000})
    analyst = login(client, 'analyst@demo.bank')
    data = client.post('/api/detection/engine/run', headers=analyst, json={}).get_json()['data']
    row = data['results'][0]
    assert row['stored_rules'] == ['R6'] and [r['code'] for r in row['rules']] == ['R6'] and row['changed'] is False


def test_engine_is_for_the_detection_role_only(client):
    for email in ('rahul@demo.bank', 'frauder@demo.bank'):
        headers = login(client, email)
        assert client.post('/api/detection/engine/run', headers=headers, json={}).status_code == 403
    analyst = login(client, 'analyst@demo.bank')
    bad = client.post('/api/detection/engine/run', headers=analyst, json={'account_id': 999999})
    assert bad.status_code == 422
    assert client.get('/api/detection/engine/runs/999999', headers=analyst).status_code == 404
