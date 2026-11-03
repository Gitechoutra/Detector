"""Authorization: the full role × endpoint matrix, and IDOR – a customer can never
read or act on another customer's payments, notifications or cases."""
import re
from decimal import Decimal

import pytest

from portal.extensions import db
from portal.models import Account, InvestigationCase, Notification, Transaction, User

from .conftest import balance, login, send
from .test_investigations import _decide, _high_risk

# Which roles each area of the API is for (from the product spec, not the code).
AREAS = [
    (r'^/api/(detection|security|alerts|analytics)(/|$)', {'DETECTION'}),
    (r'^/api/frauder/reset$', {'FRAUDER', 'DETECTION'}),
    (r'^/api/frauder(/|$)', {'FRAUDER'}),
    (r'^/api/(user|transactions|receiver)(/|$)', {'USER'}),
    (r'^/api/(notifications|auth/me|auth/logout)(/|$)', {'USER', 'DETECTION', 'FRAUDER'}),
]
ACCOUNTS = {'USER': 'karan@demo.bank', 'DETECTION': 'analyst@demo.bank', 'FRAUDER': 'frauder@demo.bank'}
PUBLIC = {'/api/auth/login', '/api/auth/register', '/api/health', '/api/meta/locations', '/api/meta/risk-categories'}


def _allowed(rule):
    for pattern, roles in AREAS:
        if re.match(pattern, rule):
            return roles
    raise AssertionError(f'{rule} is not covered by the access matrix – classify it')


def test_every_endpoint_enforces_its_roles(client, app):
    tokens = {role: login(client, email) for role, email in ACCOUNTS.items()}
    checked = 0
    for r in app.url_map.iter_rules():
        if not r.rule.startswith('/api/') or r.rule in PUBLIC:
            continue
        path = re.sub(r'<(int:)?[a-z_]+>', '1', r.rule)
        allowed = _allowed(r.rule)
        for method in r.methods - {'HEAD', 'OPTIONS'}:
            for role, headers in tokens.items():
                if path == '/api/auth/logout':
                    continue                     # would revoke the shared token
                res = client.open(path, method=method, headers=headers, json={})
                if role in allowed:
                    assert res.status_code != 403, (method, path, role)
                else:
                    assert res.status_code == 403, (method, path, role, res.status_code)
                    assert res.get_json()['error']['code'] == 'FORBIDDEN'
                checked += 1
    assert checked > 150


def test_role_is_re_read_from_the_database_not_trusted_from_the_token(client, app):
    """A token issued while the user was a customer gains nothing if the role changes,
    and loses access the moment the account is suspended."""
    karan = login(client, 'karan@demo.bank')
    with app.app_context():
        db.session.query(User).filter_by(email='karan@demo.bank').update({'status': 'SUSPENDED'})
        db.session.commit()
        db.session.remove()
    res = client.get('/api/user/dashboard', headers=karan)
    assert res.status_code == 401 and res.get_json()['error']['code'] == 'ACCOUNT_UNAVAILABLE'
    with app.app_context():
        db.session.query(User).filter_by(email='karan@demo.bank').update({'status': 'ACTIVE'})
        db.session.commit()
        db.session.remove()


# ── IDOR: Rahul's payment, attacked by Karan ───────────────────────────────

@pytest.fixture
def victim_txn(client):
    rahul = login(client, 'rahul@demo.bank')
    held = send(client, rahul, 300, upi='quickcash@fsbank').get_json()['data']       # held for YES/NO
    done = send(client, rahul, 50, upi='priya@fsbank').get_json()['data']            # completed
    return rahul, held, done


def test_other_customers_cannot_read_a_payment(client, victim_txn):
    _, held, done = victim_txn
    karan = login(client, 'karan@demo.bank')
    for txn in (held, done):
        res = client.get(f'/api/user/transactions/{txn["id"]}', headers=karan)
        assert res.status_code == 404
    listing = client.get('/api/user/transactions', headers=karan, query_string={'q': held['txn_ref']}).get_json()
    assert listing['data']['meta']['total'] == 0


def test_receiver_sees_only_credited_payments(client, victim_txn):
    _, held, done = victim_txn
    priya = login(client, 'priya@demo.bank')
    assert client.get(f'/api/user/transactions/{done["id"]}', headers=priya).status_code == 200
    quickcash = login(client, 'quickcash@demo.bank')
    assert client.get(f'/api/user/transactions/{held["id"]}', headers=quickcash).status_code == 404


@pytest.mark.parametrize('action, body', [('confirmation', {'response': 'YES'}), ('confirmation', {'response': 'NO'}),
                                          ('verification/start', {}), ('verification/confirm', {'otp': '123456'}),
                                          ('cancel', {}), ('report-fraud', {})])
def test_other_customers_cannot_act_on_a_payment(client, app, victim_txn, action, body):
    _, held, _ = victim_txn
    karan = login(client, 'karan@demo.bank')
    res = client.post(f'/api/transactions/{held["id"]}/{action}', headers=karan, json=body)
    assert res.status_code == 404, res.get_json()
    with app.app_context():
        txn = db.session.get(Transaction, held['id'])
        assert txn.status == 'UNDER_REVIEW' and txn.confirmation_status == 'PENDING'
        assert Account.query.filter_by(upi_id='quickcash@fsbank').one().status == 'ACTIVE'
        db.session.remove()
    assert balance(app, 'rahul@demo.bank') == Decimal('250000') - 50


def test_other_customers_cannot_read_or_clear_notifications(client, app, victim_txn):
    karan = login(client, 'karan@demo.bank')
    with app.app_context():
        rahul_id = User.query.filter_by(email='rahul@demo.bank').one().id
        note_ids = [n.id for n in Notification.query.filter_by(user_id=rahul_id).all()]
        db.session.remove()
    assert note_ids
    for note_id in note_ids:
        assert client.post(f'/api/notifications/{note_id}/read', headers=karan).status_code == 404
    client.post('/api/notifications/read-all', headers=karan)
    with app.app_context():
        assert Notification.query.filter(Notification.id.in_(note_ids), Notification.cleared_at.isnot(None)).count() == 0
        db.session.remove()
    listed = client.get('/api/notifications', headers=karan).get_json()['data']['items']
    assert not {n['id'] for n in listed} & set(note_ids)


def test_customer_and_frauder_cannot_decide_investigations(client, app):
    rahul, analyst, _ = _high_risk(client)
    case_id = client.get('/api/detection/investigations', headers=analyst).get_json()['data']['items'][0]['id']
    for email in ('rahul@demo.bank', 'karan@demo.bank', 'frauder@demo.bank'):
        headers = login(client, email)
        assert _decide(client, headers, case_id, 'APPROVE').status_code == 403
        assert client.post(f'/api/detection/investigations/{case_id}/start', headers=headers).status_code == 403
        assert client.get(f'/api/detection/investigations/{case_id}', headers=headers).status_code == 403
    with app.app_context():
        case = db.session.get(InvestigationCase, case_id)
        assert case.status == 'TEMPORARILY_BLOCKED' and case.decision is None
        assert db.session.get(Account, case.account_id).status == 'TEMPORARILY_BLOCKED'
        db.session.remove()


def test_customer_cannot_reach_other_users_through_detection_filters(client):
    karan = login(client, 'karan@demo.bank')
    for path in ('/api/detection/transactions?user_id=1', '/api/detection/users', '/api/detection/search?q=rahul',
                 '/api/security/audit-logs', '/api/detection/investigations/history'):
        assert client.get(path, headers=karan).status_code == 403


def test_sensitive_fields_never_leave_the_server(client):
    rahul = login(client, 'rahul@demo.bank')
    analyst = login(client, 'analyst@demo.bank')
    send(client, rahul, 300, upi='quickcash@fsbank')
    bodies = [client.get(p, headers=h).get_data(as_text=True) for p, h in (
        ('/api/user/dashboard', rahul), ('/api/auth/me', rahul), ('/api/user/security', rahul),
        ('/api/detection/users', analyst), ('/api/detection/transactions', analyst),
        ('/api/security/login-attempts', analyst), ('/api/notifications', rahul))]
    for body in bodies:
        for secret in ('password_hash', 'otp_hash', 'pbkdf2:', 'scrypt:', 'Rahul@123', 'JWT_SECRET'):
            assert secret not in body


def test_login_errors_do_not_reveal_whether_an_email_exists(client):
    unknown = client.post('/api/auth/login', json={'email': 'ghost@demo.bank', 'password': 'x', 'device_id': 'd'})
    wrong = client.post('/api/auth/login', json={'email': 'priya@demo.bank', 'password': 'x', 'device_id': 'd'})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.get_json()['error']['code'] == wrong.get_json()['error']['code'] == 'INVALID_CREDENTIALS'


def test_a_spoofed_forwarded_for_header_is_ignored(client, app):
    """Otherwise an attacker could dodge an IP watchlist entry by sending any address."""
    from portal.models import LoginAttempt, WatchlistEntry
    with app.app_context():
        db.session.add(WatchlistEntry(entity_type='IP', entity_value='203.0.113.9', reason='test', source='MANUAL'))
        db.session.commit()
        db.session.remove()
    res = client.post('/api/auth/login', headers={'X-Forwarded-For': '8.8.8.8'},
                      json={'email': 'rahul@demo.bank', 'password': 'Rahul@123', 'device_id': 'device-main'})
    assert res.status_code == 200
    with app.app_context():
        assert LoginAttempt.query.order_by(LoginAttempt.id.desc()).first().ip_address == '127.0.0.1'
        db.session.remove()
    rahul = {'Authorization': 'Bearer ' + res.get_json()['data']['token']}
    data = client.post('/api/transactions/send', headers={**rahul, 'X-Forwarded-For': '8.8.8.8'},
                       json={'payment_method': 'UPI', 'upi_id': 'priya@fsbank', 'amount': 10}).get_json()['data']
    with app.app_context():
        assert db.session.get(Transaction, data['id']).ip_address == '127.0.0.1'
        db.session.remove()


def test_one_address_guessing_across_many_accounts_is_throttled(client):
    from portal.helpers.auth import IP_MAX_FAILURES
    emails = ['rahul@demo.bank', 'karan@demo.bank', 'priya@demo.bank', 'amit@demo.bank', 'ghost@demo.bank']
    for i in range(IP_MAX_FAILURES):          # 4 per account: no single account reaches its own lock
        res = client.post('/api/auth/login', json={'email': emails[i % 5], 'password': f'guess{i}', 'device_id': 'd'})
        assert res.status_code == 401
    blocked = client.post('/api/auth/login', json={'email': 'rahul@demo.bank', 'password': 'Rahul@123',
                                                   'device_id': 'device-main'})
    assert blocked.status_code == 429 and blocked.get_json()['error']['code'] == 'RATE_LIMITED'


def test_a_few_typos_do_not_throttle(client):
    for i in range(3):
        client.post('/api/auth/login', json={'email': 'rahul@demo.bank', 'password': 'typo', 'device_id': 'd'})
    assert login(client, 'rahul@demo.bank')
