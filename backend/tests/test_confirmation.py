""""Was this transaction initiated by you?" – the account owner's YES/NO on a
held payment, its expiry policy, and the manual (SIMULATED) attacker details
typed into the Frauder console."""
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import text

from portal.extensions import db
from portal.models import Alert, SystemSetting, Transaction, User, now

from .conftest import balance, login, send
from .test_frauder import OPENING, fr, rules  # noqa: F401  (fr is a fixture)

DENIED_REASON = 'Transaction blocked because the account owner denied initiating this payment.'


def _otp(client, headers, txn_id, response='YES'):
    res = client.post(f'/api/transactions/{txn_id}/confirmation', headers=headers, json={'response': response})
    assert res.status_code == 200, res.get_json()
    return res.get_json()['data']['verification']['simulated_sms'].split('OTP ')[1][:6]


def _verify(client, headers, txn_id, password='Rahul@123'):
    otp = _otp(client, headers, txn_id)
    res = client.post(f'/api/transactions/{txn_id}/verification/confirm', headers=headers,
                      json={'otp': otp, 'password': password})
    assert res.status_code == 200, res.get_json()
    return res.get_json()['data']


def _set(app, **settings):
    with app.app_context():
        for key, value in settings.items():
            db.session.get(SystemSetting, key).setting_value = str(value)
        db.session.commit()
        db.session.remove()


def _age_history(app):
    """Rahul's genuine payments happened two days ago (so R3/R2 stay quiet)."""
    with app.app_context():
        db.session.execute(text('UPDATE transactions SET txn_time = txn_time - INTERVAL 2 DAY'))
        db.session.commit()
        db.session.remove()


def _expire_now(app, txn_id):
    with app.app_context():
        db.session.get(Transaction, txn_id).confirmation_expires_at = now() - timedelta(seconds=1)
        db.session.commit()
        db.session.remove()


def _example_attempt(client, app, fr):
    """The viva example: Rahul's account, a different city, an unknown device, ₹80,000 to Priya."""
    rahul = login(client, 'rahul@demo.bank')
    for amount in (500, 1000, 1500):                 # genuine history: average ₹1,000
        send(client, rahul, amount)
    _age_history(app)
    result = fr.transfer(80000, device='ATK-PHONE-01', city='delhi', ip='49.36.12.8',
                         target_location='Connaught Place', scenario='ATO')
    assert rules(result) == {'R1', 'R4'} and result['status'] == 'UNDER_REVIEW', rules(result)
    assert result['confirmation']['status'] == 'PENDING'
    assert result['outcome_label'] == 'AWAITING USER CONFIRMATION'
    return rahul, result


# ── 1. YES + verification → SUCCESSFUL ──────────────────────────────────────

def test_yes_with_verification_completes_payment(client, app, fr):
    rahul, attempt = _example_attempt(client, app, fr)
    card = client.get('/api/user/dashboard', headers=rahul).get_json()['data']['pending_confirmations'][0]
    assert card['id'] == attempt['id'] and card['amount'] == 80000 and card['receiver']['name'].startswith('Priya')
    assert card['device_name'] == 'Android phone #ATK-PHONE-01' and card['ip_address'] == '49.36.12.8'
    assert card['city'] == 'Delhi' and card['risk_explanation'] and card['txn_ref']

    before_rahul, before_priya = balance(app, 'rahul@demo.bank'), balance(app, 'priya@demo.bank')
    result = _verify(client, rahul, attempt['id'])
    assert result['outcome'] == 'released' and [m['code'] for m in result['mitigations']] == ['R4']
    assert [h['code'] for h in result['hits']] == ['R1']          # re-evaluated, not bypassed
    txn = result['transaction']
    assert txn['status'] == 'COMPLETED' and txn['outcome_label'] == 'USER CONFIRMED – SUCCESSFUL'
    assert txn['confirmation']['response'] == 'YES' and 'Approved after the account owner' in txn['final_reason']
    assert balance(app, 'rahul@demo.bank') == before_rahul - 80000
    assert balance(app, 'priya@demo.bank') == before_priya + 80000

    priya = client.get('/api/receiver/payments', headers=login(client, 'priya@demo.bank')).get_json()['data']['items']
    assert priya[0]['id'] == attempt['id'] and priya[0]['credited'] is True
    notes = client.get('/api/notifications', headers=rahul).get_json()['data']['items']
    assert any(n['title'] == 'Payment successful' for n in notes)


# ── 2. NO → BLOCKED at once ─────────────────────────────────────────────────

def test_no_blocks_immediately_and_every_dashboard_agrees(client, app, fr):
    rahul, attempt = _example_attempt(client, app, fr)
    before_rahul, before_priya = balance(app, 'rahul@demo.bank'), balance(app, 'priya@demo.bank')
    res = client.post(f"/api/transactions/{attempt['id']}/confirmation", headers=rahul, json={'response': 'no'})
    assert res.status_code == 200
    txn = res.get_json()['data']['transaction']
    assert txn['status'] == 'BLOCKED' and txn['final_reason'] == DENIED_REASON
    assert txn['outcome_label'] == 'USER DENIED – BLOCKED' and txn['money_moved'] is False
    assert balance(app, 'rahul@demo.bank') == before_rahul and balance(app, 'priya@demo.bank') == before_priya

    with app.app_context():
        alert = Alert.query.filter_by(transaction_id=attempt['id'], alert_type='USER_DENIED').one()
        assert alert.severity == 'HIGH' and alert.status == 'OPEN'
        db.session.remove()

    blocked = client.get('/api/user/transactions?status=BLOCKED', headers=rahul).get_json()['data']['items']
    assert blocked[0]['id'] == attempt['id'] and blocked[0]['final_reason'] == DENIED_REASON
    analyst = login(client, 'analyst@demo.bank')
    detection = client.get('/api/detection/transactions', headers=analyst).get_json()['data']['items']
    confirmations = client.get('/api/detection/confirmations', headers=analyst).get_json()['data']
    frauder = client.get('/api/frauder/attempts', headers=fr.headers).get_json()['data']
    shown = next(t for t in detection if t['id'] == attempt['id'])
    assert shown['outcome_label'] == 'USER DENIED – BLOCKED' and shown['confirmation']['response'] == 'NO'
    assert confirmations['recent'][0]['id'] == attempt['id'] and confirmations['counts']['no'] == 1
    assert frauder[0]['transaction_id'] == attempt['id'] and frauder[0]['outcome_label'] == 'USER DENIED – BLOCKED'
    priya = client.get('/api/receiver/payments', headers=login(client, 'priya@demo.bank')).get_json()['data']['items']
    assert attempt['id'] not in [t['id'] for t in priya]          # never shown as received money
    result = client.get(f"/api/frauder/transactions/{attempt['id']}", headers=fr.headers).get_json()['data']
    labels = [i['label'] for i in result['timeline']]
    assert 'Confirmation requested from Rahul' in labels and 'Rahul answered NO' in labels


# ── 3. No answer → never approved ───────────────────────────────────────────

def test_unanswered_confirmation_is_blocked_on_expiry(client, app, fr):
    attempt = fr.transfer(2000, receiver='quickcash')
    _expire_now(app, attempt['id'])
    rahul = login(client, 'rahul@demo.bank')
    data = client.get('/api/user/dashboard', headers=rahul).get_json()['data']
    assert data['pending_confirmations'] == []
    txn = client.get(f"/api/user/transactions/{attempt['id']}", headers=rahul).get_json()['data']
    assert txn['status'] == 'BLOCKED' and txn['outcome_label'] == 'NO RESPONSE – BLOCKED'
    assert 'did not confirm it within 30 minutes' in txn['final_reason']
    assert balance(app, 'rahul@demo.bank') == OPENING['rahul@demo.bank']


def test_hold_policy_on_expiry_still_never_approves(client, app, fr):
    _set(app, CONFIRMATION_EXPIRY_ACTION='HOLD')
    attempt = fr.transfer(2000, receiver='quickcash')
    _expire_now(app, attempt['id'])
    result = client.get(f"/api/frauder/transactions/{attempt['id']}", headers=fr.headers).get_json()['data']
    assert result['status'] == 'UNDER_REVIEW' and result['review_stage'] == 'AWAITING_ANALYST'
    assert result['confirmation']['status'] == 'EXPIRED' and result['money_moved'] is False


# ── 4–6. Who may answer, and only once, and only in time ────────────────────

def test_only_the_owner_can_answer(client, app, fr):
    attempt = fr.transfer(2000, receiver='quickcash')
    url = f"/api/transactions/{attempt['id']}/confirmation"
    karan = login(client, 'karan@demo.bank')
    assert client.post(url, headers=karan, json={'response': 'NO'}).status_code == 404
    assert client.post(f"/api/transactions/{attempt['id']}/verification/start", headers=karan).status_code == 404
    for email in ('priya@demo.bank', 'analyst@demo.bank', 'frauder@demo.bank'):
        assert client.post(url, headers=login(client, email), json={'response': 'YES'}).status_code == 403
    assert client.post(url, json={'response': 'YES'}).status_code == 401
    rahul = login(client, 'rahul@demo.bank')
    assert client.post(url, headers=rahul, json={'response': 'MAYBE'}).status_code == 422
    # A user id in the body is ignored: identity comes from the login session.
    assert client.post(url, headers=karan, json={'response': 'YES', 'user_id': fr.ids['rahul']}).status_code == 404
    assert client.get('/api/transactions/confirmations', headers=rahul).get_json()['data'][0]['id'] == attempt['id']
    assert client.get('/api/transactions/confirmations', headers=karan).get_json()['data'] == []


def test_duplicate_answers_are_rejected(client, app, fr):
    rahul = login(client, 'rahul@demo.bank')
    first = fr.transfer(2000, receiver='quickcash')
    url = f"/api/transactions/{first['id']}/confirmation"
    assert client.post(url, headers=rahul, json={'response': 'NO'}).status_code == 200
    for answer in ('NO', 'YES'):
        again = client.post(url, headers=rahul, json={'response': answer})
        assert again.status_code == 409 and again.get_json()['error']['code'] == 'ALREADY_RESPONDED'

    second = fr.transfer(2000, receiver='quickcash')
    url = f"/api/transactions/{second['id']}/confirmation"
    assert client.post(url, headers=rahul, json={'response': 'YES'}).status_code == 200
    for answer in ('YES', 'NO'):
        assert client.post(url, headers=rahul, json={'response': answer}).status_code == 409
    assert client.post(f"/api/transactions/{first['id']}/report-fraud", headers=rahul).status_code == 409


def test_answer_after_expiry_is_rejected(client, app, fr):
    attempt = fr.transfer(2000, receiver='quickcash')
    _expire_now(app, attempt['id'])
    rahul = login(client, 'rahul@demo.bank')
    res = client.post(f"/api/transactions/{attempt['id']}/confirmation", headers=rahul, json={'response': 'YES'})
    assert res.status_code == 410 and res.get_json()['error']['code'] == 'CONFIRMATION_EXPIRED'
    again = client.post(f"/api/transactions/{attempt['id']}/confirmation", headers=rahul, json={'response': 'YES'})
    assert again.status_code == 410
    assert balance(app, 'quickcash@demo.bank') == OPENING['quickcash@demo.bank']


# ── 7. YES cannot override a hard-block condition ───────────────────────────

def test_yes_on_hard_block_rule_stays_blocked(client, app, fr):
    attempt = fr.transfer(2000, receiver='quickcash')             # R6 alone → REVIEW
    assert rules(attempt) == {'R6'} and attempt['status'] == 'UNDER_REVIEW'
    rahul = login(client, 'rahul@demo.bank')
    result = _verify(client, rahul, attempt['id'])
    txn = result['transaction']
    assert result['outcome'] == 'blocked' and txn['status'] == 'BLOCKED'
    assert txn['outcome_label'] == 'USER CONFIRMED – STILL BLOCKED'
    assert 'hard-block condition (R6)' in txn['final_reason']
    assert balance(app, 'rahul@demo.bank') == OPENING['rahul@demo.bank']
    assert balance(app, 'quickcash@demo.bank') == OPENING['quickcash@demo.bank']


def test_yes_that_still_scores_review_goes_to_analyst(client, app, fr):
    _set(app, CONFIRMATION_HARD_BLOCK_RULES='')
    attempt = fr.transfer(2000, receiver='quickcash')
    result = _verify(client, login(client, 'rahul@demo.bank'), attempt['id'])
    assert result['outcome'] == 'escalated' and result['transaction']['outcome_label'] == 'WITH FRAUD TEAM'
    assert balance(app, 'quickcash@demo.bank') == OPENING['quickcash@demo.bank']


# ── 8. Manually typed attacker details ──────────────────────────────────────

def test_manual_details_are_stored_unchanged_and_used_by_rules(client, app, fr):
    result = fr.transfer(1200, device='ATK-77', city='delhi', ip='49.36.12.8', target_location='Karol Bagh',
                         scenario='R3')
    sim = result['simulated_details']
    assert sim == {'source': 'SIMULATED', 'verified': False, 'city': 'Delhi', 'target_location': 'Karol Bagh',
                   'use_registered_device': False, 'device_type': 'Android phone', 'device_id': 'ATK-77',
                   'ip_address': '49.36.12.8', 'scenario': 'R3', 'scenario_name': 'R3 · Impossible travel'}
    assert result['ip_address'] == '49.36.12.8' and result['city'] == 'Delhi'
    assert result['device']['device_name'] == 'Android phone' and result['device']['is_trusted'] is False

    with app.app_context():                                      # the victim's real profile is untouched
        rahul = User.query.filter_by(email='rahul@demo.bank').one()
        assert rahul.home_location.city == 'Mumbai'
        db.session.remove()

    analyst = login(client, 'analyst@demo.bank')
    client.post('/api/detection/watchlist', headers=analyst,
                json={'entity_type': 'IP', 'entity_value': '49.36.12.8', 'reason': 'Known attacker IP'})
    flagged = fr.transfer(1200, device='ATK-77', city='delhi', ip='49.36.12.8')
    r6 = next(t for t in flagged['rule_trace'] if t['code'] == 'R6')
    assert r6['status'] == 'TRIGGERED' and '49.36.12.8' in r6['observed']   # typed IP fed the rule


def test_manual_details_are_validated(client, fr):
    def err(**fields):
        res = fr.transfer(1000, device='ATK-1', expect=422, **fields)
        return res['error']['details']['field']
    assert err(ip='999.1.1.1') == 'ip_address'
    assert err(ip='') == 'ip_address'
    assert err(device_id='x') == 'device_id'
    assert err(device_type='') == 'device_type'
    assert err(scenario='NOPE') == 'scenario'
    bad_city = client.post('/api/frauder/transfer', headers=fr.headers, json={
        'victim_id': fr.ids['rahul'], 'receiver_id': fr.ids['priya'], 'amount': 100, 'city': 'Atlantis',
        'device_type': 'Android phone', 'device_id': 'ATK-1', 'ip_address': '10.0.0.1'})
    assert bad_city.status_code == 422 and 'Unknown city' in bad_city.get_json()['error']['message']
    no_city = client.post('/api/frauder/transfer', headers=fr.headers, json={
        'victim_id': fr.ids['rahul'], 'receiver_id': fr.ids['priya'], 'amount': 100,
        'use_registered_device': True, 'ip_address': '10.0.0.1'})
    assert no_city.status_code == 422 and no_city.get_json()['error']['details']['field'] == 'city'


def test_context_fills_nothing_in(client, fr):
    ctx = client.get('/api/frauder/context', headers=fr.headers).get_json()['data']
    assert {'cities', 'device_types', 'scenarios', 'policy'} <= set(ctx)
    assert ctx['policy'] == {'confirmation_expiry_minutes': 30, 'expiry_action': 'BLOCK', 'hard_block_rules': ['R6']}
    guide = client.get('/api/frauder/rule-guide', headers=fr.headers).get_json()['data']
    assert all('preset' not in g for g in guide)


# ── 9–10. Balances stay consistent ──────────────────────────────────────────

def test_total_money_is_conserved_across_yes_and_no(client, app, fr):
    accounts = ('rahul@demo.bank', 'priya@demo.bank')
    total = sum(balance(app, a) for a in accounts)
    rahul, attempt = _example_attempt(client, app, fr)
    client.post(f"/api/transactions/{attempt['id']}/confirmation", headers=rahul, json={'response': 'NO'})
    _age_history(app)
    second = fr.transfer(80000, device='ATK-PHONE-02', city='delhi', ip='49.36.12.9')
    assert second['status'] == 'UNDER_REVIEW'
    _verify(client, rahul, second['id'])
    assert sum(balance(app, a) for a in accounts) == total
    assert balance(app, 'rahul@demo.bank') == OPENING['rahul@demo.bank'] - Decimal('3000') - 80000
