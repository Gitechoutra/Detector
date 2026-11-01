"""Manual Frauder console: each of the nine rules triggered by hand, money
movement, permissions, idempotency and demo-time handling."""
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from portal.extensions import db
from portal.models import Transaction, User

from .conftest import balance, login, send

# Written for the owner-confirmation policy (DECISION_MODE=OWNER_CONFIRM);
# the automatic policy is covered by test_auto_decisions.py.
pytestmark = pytest.mark.usefixtures('owner_confirm')

OPENING = {'rahul@demo.bank': Decimal('250000'), 'suresh@demo.bank': Decimal('300000'),
           'priya@demo.bank': Decimal('25000'), 'amit@demo.bank': Decimal('10000'),
           'quickcash@demo.bank': Decimal('5000')}


@pytest.fixture
def fr(client, app):
    """Frauder session plus the ids it needs. Each victim signs in once, so
    they have a registered device (the remote-access scam option)."""
    for email in ('rahul@demo.bank', 'suresh@demo.bank', 'karan@demo.bank'):
        login(client, email)
    headers = login(client, 'frauder@demo.bank')
    ctx = client.get('/api/frauder/context', headers=headers).get_json()['data']
    ids = {v['name'].split()[0].lower(): v['id'] for v in ctx['victims']}
    ids.update({r['name'].split()[0].lower(): r['id'] for r in ctx['receivers']})
    cities = {c.lower(): c for c in ctx['cities']}
    homes = {v['name'].split()[0].lower(): v['home_city'] for v in ctx['victims']}

    def attacker(victim, device, city, ip):
        """The values the presenter types. 'own' = victim's registered device,
        'new' = a device ID never used before, anything else = that device ID."""
        fields = {'city': cities[city] if city else homes[victim], 'ip_address': ip}
        if device == 'own':
            return {**fields, 'use_registered_device': True}
        return {**fields, 'device_type': 'Android phone',
                'device_id': 'ATK-' + uuid.uuid4().hex[:8] if device == 'new' else device}

    class F:
        def transfer(self, amount, victim='rahul', receiver='priya', device='own', city=None, demo_time=None,
                     key=None, expect=201, ip='203.0.113.10', **extra):
            body = {'victim_id': ids[victim], 'receiver_id': ids[receiver], 'amount': amount,
                    **attacker(victim, device, city, ip), **extra}
            if demo_time:
                body['demo_time'] = demo_time
            res = client.post('/api/frauder/transfer', json=body,
                              headers={**headers, 'Idempotency-Key': key or uuid.uuid4().hex})
            assert res.status_code == expect, res.get_json()
            return res.get_json()['data'] if res.status_code < 300 else res.get_json()

        def login(self, outcome, victim='rahul', device='new', city=None, ip='198.51.100.77'):
            res = client.post('/api/frauder/login-attempt', headers=headers, json={
                'victim_id': ids[victim], 'outcome': outcome, **attacker(victim, device, city, ip)})
            assert res.status_code == 200, res.get_json()
            return res.get_json()['data']

        def otp(self, victim='rahul'):
            return client.post('/api/frauder/otp-attempt', headers=headers, json={'victim_id': ids[victim]})

    f = F()
    f.headers, f.ids, f.ctx = headers, ids, ctx
    return f


def rules(result):
    return {t['code'] for t in result['rule_trace'] if t['status'] == 'TRIGGERED'}


# ── The nine rules, one at a time ───────────────────────────────────────────

def test_r1_high_amount_against_victims_own_average(client, app, fr):
    rahul = login(client, 'rahul@demo.bank')
    for amount in (500, 1000, 1500):                     # genuine history: average ₹1,000
        assert send(client, rahul, amount).get_json()['data']['status'] == 'COMPLETED'
    result = fr.transfer(8000)                            # limit 5 × 1,000 = 5,000
    assert rules(result) == {'R1'} and result['risk_score'] == 30 and result['status'] == 'UNDER_REVIEW'
    r1 = next(t for t in result['rule_trace'] if t['code'] == 'R1')
    assert '₹1,000.00' in r1['observed'] and '₹5,000.00' in r1['threshold']


def test_r2_velocity_after_six_manual_transfers(fr):
    results = [fr.transfer(200) for _ in range(6)]
    assert all('R2' not in rules(r) for r in results[:5])
    assert rules(results[5]) == {'R2'}
    r2 = next(t for t in results[5]['rule_trace'] if t['code'] == 'R2')
    assert r2['observed'].startswith('6 payment(s)')


def test_r3_impossible_travel_by_changing_city(fr):
    fr.transfer(500, receiver='amit', city='mumbai')
    result = fr.transfer(500, receiver='amit', city='delhi')
    assert rules(result) == {'R3'}
    r3 = next(t for t in result['rule_trace'] if t['code'] == 'R3')
    assert 'Mumbai → Delhi' in r3['observed']


def test_r4_new_device_high_amount_without_login(fr):
    result = fr.transfer(30000, device='new')
    assert rules(result) == {'R4'} and result['risk_score'] == 20


def test_r5_odd_hour_with_demo_clock(fr):
    result = fr.transfer(12000, demo_time='02:30')
    assert rules(result) == {'R5'}
    assert datetime.fromisoformat(result['txn_time']).strftime('%H:%M') == '02:30'


def test_r6_watchlisted_receiver_names_the_entity(fr):
    result = fr.transfer(2000, receiver='quickcash')
    assert rules(result) == {'R6'} and result['status'] == 'UNDER_REVIEW'
    r6 = next(t for t in result['rule_trace'] if t['code'] == 'R6')
    assert 'quickcash@fsbank' in r6['observed']
    assert 'watchlist' in result['risk_explanation']


def test_r7_structuring_just_under_threshold(fr):
    results = [fr.transfer(46000, receiver='amit') for _ in range(3)]
    assert 'R7' not in rules(results[0]) and 'R7' not in rules(results[1])
    assert rules(results[2]) == {'R7'}


def test_r8_dormant_demo_account(client, app, fr):
    result = fr.transfer(30000, victim='suresh')
    assert rules(result) == {'R8'}
    r8 = next(t for t in result['rule_trace'] if t['code'] == 'R8')
    assert int(r8['observed'].split()[0]) >= 180


def test_r9_failed_logins_then_stolen_login(app, fr):
    for _ in range(3):
        fr.login('WRONG_PASSWORD', device='ATK-R9', city='hyderabad')
    login_result = fr.login('STOLEN_PASSWORD', device='ATK-R9', city='hyderabad')
    assert login_result['success'] is True
    result = fr.transfer(6000, receiver='amit', device=str(login_result['device_id']), city='hyderabad')
    assert rules(result) == {'R9'} and result['risk_score'] == 45
    assert result['status'] == 'UNDER_REVIEW' and result['review_stage'] == 'AWAITING_CUSTOMER'
    labels = [i['label'] for i in result['timeline']]
    assert labels.count('Wrong password attempt') == 3 and 'Login with stolen password' in labels


def test_r9_wrong_otps(client, fr):
    login(client, 'rahul@demo.bank')
    assert fr.otp().status_code == 200 and fr.otp().status_code == 200
    result = fr.transfer(6000)
    assert rules(result) == {'R9'}


# ── Decisions & money ───────────────────────────────────────────────────────

def test_held_attempt_moves_no_money_and_explains(app, fr):
    fr.login('WRONG_PASSWORD'), fr.login('WRONG_PASSWORD'), fr.login('WRONG_PASSWORD')
    device = fr.login('STOLEN_PASSWORD', city='hyderabad')['device_id']
    result = fr.transfer(80000, receiver='quickcash', device=str(device))
    assert {'R4', 'R6', 'R9'} <= rules(result) and result['risk_score'] == 100 and result['status'] == 'UNDER_REVIEW'
    assert result['outcome_label'] == 'USER CONFIRMATION PENDING'
    assert result['risk_explanation'].startswith("Held for the account owner's authorization because")
    assert 'unrecognized device' in result['risk_explanation']
    assert result['balances']['sender']['before'] == result['balances']['sender']['after'] == 250000
    labels = [i['label'] for i in result['timeline']]
    for step in ('Transaction submitted', 'Fraud rules evaluated', 'Rules triggered', 'Risk score calculated',
                 'Risk band (recorded)', 'Security alert created', 'Waiting – no money moved yet'):
        assert step in labels, step
    assert balance(app, 'rahul@demo.bank') == OPENING['rahul@demo.bank']
    assert balance(app, 'quickcash@demo.bank') == OPENING['quickcash@demo.bank']


def test_attempt_without_rules_still_needs_the_owner_then_moves_money(client, app, fr):
    result = fr.transfer(1500)
    assert result['rule_trace'] and not rules(result) and result['risk_score'] == 0
    assert result['status'] == 'UNDER_REVIEW' and result['money_moved'] is False
    assert result['balances']['sender']['after'] == 250000
    rahul = login(client, 'rahul@demo.bank')
    client.post(f"/api/transactions/{result['id']}/confirmation", headers=rahul, json={'response': 'YES'})
    assert balance(app, 'rahul@demo.bank') == Decimal('248500')
    assert balance(app, 'priya@demo.bank') == Decimal('26500')


def test_review_stays_pending_until_owner_verifies(client, app, fr):
    result = fr.transfer(2000, receiver='quickcash')
    assert result['status'] == 'UNDER_REVIEW'
    assert balance(app, 'rahul@demo.bank') == OPENING['rahul@demo.bank']
    assert result['confirmation']['status'] == 'PENDING'
    rahul = login(client, 'rahul@demo.bank')
    pending = client.get('/api/user/dashboard', headers=rahul).get_json()['data']['pending_confirmations']
    assert pending[0]['id'] == result['id'] and pending[0]['risk_explanation']


def test_same_record_on_every_dashboard(client, fr):
    result = fr.transfer(1250)
    client.post(f"/api/transactions/{result['id']}/confirmation", headers=login(client, 'rahul@demo.bank'),
                json={'response': 'YES'})
    rahul = client.get('/api/user/transactions', headers=login(client, 'rahul@demo.bank')).get_json()['data']['items']
    priya = client.get('/api/receiver/payments', headers=login(client, 'priya@demo.bank')).get_json()['data']['items']
    analyst = client.get('/api/detection/transactions', headers=login(client, 'analyst@demo.bank')).get_json()['data']['items']
    views = [next(t for t in rows if t['id'] == result['id']) for rows in (rahul, priya, analyst)]
    assert {(v['txn_ref'], v['amount'], v['status']) for v in views} == {(result['txn_ref'], 1250.0, 'COMPLETED')}
    history = client.get('/api/frauder/attempts', headers=fr.headers).get_json()['data']
    assert history[0]['transaction_id'] == result['id'] and history[0]['money_moved'] is True


def test_repeated_submission_does_not_pay_twice(app, fr):
    first = fr.transfer(1000, key='same-click')
    again = fr.transfer(1000, key='same-click', expect=200)
    assert again['replayed'] is True and again['id'] == first['id']
    assert balance(app, 'rahul@demo.bank') == OPENING['rahul@demo.bank']          # held, not paid


def test_genuine_owner_payment_not_blocked_after_attacks(client, fr):
    for _ in range(3):
        fr.login('WRONG_PASSWORD')
    rahul = login(client, 'rahul@demo.bank')      # the real owner signs in on his own device
    data = send(client, rahul, 6000).get_json()['data']
    assert data['status'] == 'COMPLETED' and data['rules'] == []


def test_lockout_then_reset_attempts(client, app, fr):
    for _ in range(5):
        fr.login('WRONG_PASSWORD')
    assert fr.ctx and fr.login('STOLEN_PASSWORD')['success'] is False     # locked: login refused
    refused = fr.transfer(1000, expect=423)
    assert refused['error']['code'] == 'ACCOUNT_LOCKED'
    login(client, 'rahul@demo.bank', expect=423)
    assert client.post('/api/frauder/reset', headers=fr.headers, json={'confirm': 'RESET'}).status_code == 200
    login(client, 'rahul@demo.bank')


def test_reset_attempts_reverses_only_frauder_money(client, app, fr):
    rahul = login(client, 'rahul@demo.bank')
    genuine = send(client, rahul, 700).get_json()['data']
    fr.transfer(1500)
    fr.transfer(30000, victim='suresh')
    res = client.post('/api/frauder/reset', headers=fr.headers, json={'confirm': 'RESET'})
    assert res.status_code == 200
    assert balance(app, 'rahul@demo.bank') == OPENING['rahul@demo.bank'] - 700
    assert balance(app, 'priya@demo.bank') == OPENING['priya@demo.bank'] + 700
    assert balance(app, 'suresh@demo.bank') == OPENING['suresh@demo.bank']
    with app.app_context():
        assert [t.id for t in Transaction.query.all()] == [genuine['id']]
        db.session.remove()
    assert rules(fr.transfer(30000, victim='suresh')) == {'R8'}   # still dormant after reset


# ── Guards ──────────────────────────────────────────────────────────────────

def test_frauder_cannot_bypass_permissions(client, fr):
    user = login(client, 'rahul@demo.bank')
    body = {'victim_id': fr.ids['rahul'], 'receiver_id': fr.ids['priya'], 'amount': 100}
    assert client.post('/api/frauder/transfer', headers=user, json=body).status_code == 403
    assert client.get('/api/frauder/context', headers=user).status_code == 403
    bad_victim = client.post('/api/frauder/transfer', headers=fr.headers,
                             json={**body, 'victim_id': fr.ids['priya']})
    assert bad_victim.status_code == 422 and bad_victim.get_json()['error']['code'] == 'NOT_A_DEMO_VICTIM'
    bad_receiver = client.post('/api/frauder/transfer', headers=fr.headers,
                               json={**body, 'receiver_id': fr.ids['rahul']})
    assert bad_receiver.status_code == 422
    for method, path in (('post', '/api/transactions/send'), ('put', '/api/detection/rules/R1'),
                         ('post', '/api/detection/transactions/1/decision')):
        assert getattr(client, method)(path, headers=fr.headers, json={}).status_code == 403
    ctx = client.get('/api/frauder/context', headers=fr.headers).get_json()['data']
    assert 'password' not in str(ctx).lower()


def test_demo_time_validation_and_future_times(fr):
    bad = fr.transfer(100, demo_time='25:99', expect=422)
    assert bad['error']['code'] == 'VALIDATION_ERROR'
    soon = (datetime.now() + timedelta(minutes=5)).strftime('%H:%M')
    result = fr.transfer(100, demo_time=soon)
    assert datetime.fromisoformat(result['txn_time']) < datetime.now()   # future time → yesterday


def test_trace_covers_all_nine_rules(fr):
    result = fr.transfer(100)
    assert [t['code'] for t in result['rule_trace']] == [f'R{i}' for i in range(1, 10)]
    assert all(t['observed'] and t['threshold'] for t in result['rule_trace'])


def test_rule_guide_uses_live_thresholds(client, fr):
    analyst = login(client, 'analyst@demo.bank')
    client.put('/api/detection/rules/R4', headers=analyst, json={'params': {'amount_threshold': 40000}})
    guide = client.get('/api/frauder/rule-guide', headers=fr.headers).get_json()['data']
    assert [g['code'] for g in guide] == [f'R{i}' for i in range(1, 10)]
    r4 = next(g for g in guide if g['code'] == 'R4')
    assert '₹40,000' in r4['hint'] and 'preset' not in r4      # hints never fill the form


def test_automatic_simulation_is_gone(client, fr):
    assert client.post('/api/simulation/start', headers=fr.headers, json={}).status_code == 404
    assert client.post('/api/simulation/scenarios/HIGH_VALUE/run', headers=fr.headers).status_code == 404
    assert client.post('/api/demo/scenarios/HIGH_VALUE/run').status_code == 404
