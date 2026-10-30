"""Every fraud-flagged payment waits for its owner: "Security Verification
Required – did you initiate this transaction?". YES authorizes it, NO blocks it,
no answer lets it EXPIRE. Plus the manual (SIMULATED) attacker details typed
into the Frauder console."""
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from portal.extensions import db
from portal.models import Alert, FraudRule, SystemSetting, Transaction, User, now

from .conftest import balance, login, send
from .test_frauder import OPENING, fr, rules  # noqa: F401  (fr is a fixture)

DENIED_REASON = 'Account owner denied initiating this transaction.'
YES_MESSAGE = 'Transaction successfully authorized. The amount has been transferred to the Receiver.'
NO_MESSAGE = ('Transaction blocked successfully. You reported that this transaction was not initiated by you. '
              'No money has been transferred.')
EMAILS = {'rahul': 'rahul@demo.bank', 'suresh': 'suresh@demo.bank', 'priya': 'priya@demo.bank',
          'amit': 'amit@demo.bank', 'quickcash': 'quickcash@demo.bank'}


def _answer(client, headers, txn_id, response):
    return client.post(f'/api/transactions/{txn_id}/confirmation', headers=headers, json={'response': response})


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


def _weight(app, code):
    with app.app_context():
        weight = FraudRule.query.filter_by(code=code).one().weight
        db.session.remove()
        return weight


def _example_attempt(client, app, fr):
    """The viva example: Rahul's account, a different city, an unknown device, ₹80,000 to Priya."""
    rahul = login(client, 'rahul@demo.bank')
    for amount in (500, 1000, 1500):                 # genuine history: average ₹1,000
        send(client, rahul, amount)
    _age_history(app)
    result = fr.transfer(80000, device='ATK-PHONE-01', city='delhi', ip='49.36.12.8',
                         target_location='Connaught Place', scenario='ATO')
    assert rules(result) == {'R1', 'R4'} and result['status'] == 'UNDER_REVIEW', rules(result)
    assert result['confirmation']['status'] == 'PENDING' and result['display_status'] == 'USER_CONFIRMATION_PENDING'
    assert result['outcome_label'] == 'USER CONFIRMATION PENDING'
    return rahul, result


# ── Each of the nine rules on its own: held → YES pays / NO blocks ──────────

def _trigger_r9(fr):
    for _ in range(3):
        fr.login('WRONG_PASSWORD', device='ATK-R9', city='hyderabad')
    device = fr.login('STOLEN_PASSWORD', device='ATK-R9', city='hyderabad')['device_id']
    return fr.transfer(6000, receiver='amit', device=str(device), city='hyderabad')


def _trigger_r1(fr, client):
    rahul = login(client, 'rahul@demo.bank')
    for amount in (500, 1000, 1500):
        send(client, rahul, amount)
    return fr.transfer(8000)


TRIGGERS = {   # rule → (victim, receiver, how the Frauder triggers it by hand)
    'R1': ('rahul', 'priya', _trigger_r1),
    'R2': ('rahul', 'priya', lambda fr, c: [fr.transfer(200) for _ in range(6)][-1]),
    'R3': ('rahul', 'amit', lambda fr, c: [fr.transfer(500, receiver='amit', city=city)
                                           for city in ('mumbai', 'delhi')][-1]),
    'R4': ('rahul', 'priya', lambda fr, c: fr.transfer(30000, device='new')),
    'R5': ('rahul', 'priya', lambda fr, c: fr.transfer(12000, demo_time='02:30')),
    'R6': ('rahul', 'quickcash', lambda fr, c: fr.transfer(2000, receiver='quickcash')),
    'R7': ('rahul', 'amit', lambda fr, c: [fr.transfer(46000, receiver='amit') for _ in range(3)][-1]),
    'R8': ('suresh', 'priya', lambda fr, c: fr.transfer(30000, victim='suresh')),
    'R9': ('rahul', 'amit', lambda fr, c: _trigger_r9(fr)),
}


@pytest.mark.parametrize('answer', ['YES', 'NO'])
@pytest.mark.parametrize('code', sorted(TRIGGERS))
def test_each_rule_alone_waits_for_the_owner(client, app, fr, code, answer):
    victim, receiver, trigger = TRIGGERS[code]
    owner_email, receiver_email = EMAILS[victim], EMAILS[receiver]
    # Balances just before the flagged attempt (earlier set-up payments complete normally).
    before = {}

    def snapshot():
        before.update({e: balance(app, e) for e in (owner_email, receiver_email)})
    attempt = trigger(_Snap(fr, snapshot), client)

    assert rules(attempt) == {code}, rules(attempt)
    assert attempt['risk_score'] == _weight(app, code)                       # the actual weighted score
    assert attempt['status'] == 'UNDER_REVIEW' and attempt['display_status'] == 'USER_CONFIRMATION_PENDING'
    assert attempt['money_moved'] is False
    assert {e: balance(app, e) for e in before} == before                    # nothing moved yet

    owner = login(client, owner_email)
    cards = client.get('/api/user/dashboard', headers=owner).get_json()['data']['pending_confirmations']
    card = next(c for c in cards if c['id'] == attempt['id'])
    assert card['risk_score'] == attempt['risk_score'] and card['rules'][0]['code'] == code

    res = _answer(client, owner, attempt['id'], answer)
    body = res.get_json()
    assert res.status_code == 200, body
    txn = body['data']['transaction']
    amount = Decimal(str(attempt['amount']))
    if answer == 'YES':
        assert body['message'] == YES_MESSAGE and txn['display_status'] == 'SUCCESSFUL'
        assert txn['outcome_label'] == 'USER AUTHORIZED – PAYMENT SUCCESSFUL'
        assert balance(app, owner_email) == before[owner_email] - amount
        assert balance(app, receiver_email) == before[receiver_email] + amount
    else:
        assert body['message'] == NO_MESSAGE and txn['status'] == 'BLOCKED'
        assert txn['outcome_label'] == 'USER DENIED – PAYMENT BLOCKED' and txn['final_reason'] == DENIED_REASON
        assert {e: balance(app, e) for e in before} == before
    assert txn['risk_score'] == attempt['risk_score']                        # preserved for investigation
    frauder = client.get(f"/api/frauder/transactions/{attempt['id']}", headers=fr.headers).get_json()['data']
    assert frauder['outcome_label'] == txn['outcome_label']


class _Snap:
    """Wraps the Frauder helper so the balance snapshot is taken right before
    the last (flagged) transfer of each trigger sequence."""
    def __init__(self, fr, snapshot):
        self._fr, self._snapshot = fr, snapshot

    def transfer(self, *args, **kwargs):
        self._snapshot()
        return self._fr.transfer(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._fr, name)


def test_multiple_rules_still_wait_for_the_owner(client, app, fr):
    for _ in range(3):
        fr.login('WRONG_PASSWORD', device='ATK-MULTI', city='hyderabad')
    device = fr.login('STOLEN_PASSWORD', device='ATK-MULTI', city='hyderabad')['device_id']
    attempt = fr.transfer(80000, receiver='quickcash', device=str(device), city='hyderabad')
    assert {'R4', 'R6', 'R9'} <= rules(attempt) and attempt['risk_score'] == 100
    assert attempt['decision'] == 'BLOCKED' and attempt['display_status'] == 'USER_CONFIRMATION_PENDING'
    rahul = login(client, 'rahul@demo.bank')
    assert _answer(client, rahul, attempt['id'], 'YES').get_json()['data']['outcome'] == 'authorized'
    assert balance(app, 'rahul@demo.bank') == OPENING['rahul@demo.bank'] - 80000
    assert balance(app, 'quickcash@demo.bank') == OPENING['quickcash@demo.bank'] + 80000


def test_frauder_attempt_without_rules_is_still_held(app, fr):
    attempt = fr.transfer(1500)
    assert rules(attempt) == set() and attempt['risk_score'] == 0
    assert attempt['display_status'] == 'USER_CONFIRMATION_PENDING' and attempt['money_moved'] is False
    assert "not made from the owner's own banking session" in attempt['risk_explanation']
    assert balance(app, 'rahul@demo.bank') == OPENING['rahul@demo.bank']


def test_genuine_payment_without_rules_completes_normally(client, app):
    data = send(client, login(client, 'rahul@demo.bank'), 1500).get_json()['data']
    assert data['display_status'] == 'SUCCESSFUL' and data['confirmation'] is None


def test_no_blocks_the_attacker_device_and_ip(client, app, fr):
    attempt = fr.transfer(1500, device='ATK-BAD', ip='49.36.12.50')
    _answer(client, login(client, 'rahul@demo.bank'), attempt['id'], 'NO')
    again = fr.transfer(1500, device='ATK-BAD', ip='49.36.12.50')
    r6 = next(t for t in again['rule_trace'] if t['code'] == 'R6')
    assert r6['status'] == 'TRIGGERED' and '49.36.12.50' in r6['observed']


# ── The notification, and every dashboard agreeing ─────────────────────────

def test_security_notification_until_answered(client, app, fr):
    rahul, attempt = _example_attempt(client, app, fr)
    card = client.get('/api/user/dashboard', headers=rahul).get_json()['data']['pending_confirmations'][0]
    assert card['id'] == attempt['id'] and card['amount'] == 80000 and card['receiver']['name'].startswith('Priya')
    assert card['device_name'] == 'Android phone #ATK-PHONE-01' and card['ip_address'] == '49.36.12.8'
    assert card['risk_score'] == 50 and {r['code'] for r in card['rules']} == {'R1', 'R4'}
    assert all(r['name'] and r['reason'] for r in card['rules']) and card['risk_explanation'] and card['txn_ref']

    def notice():
        items = client.get('/api/notifications', headers=rahul).get_json()['data']['items']
        return next(n for n in items if n['title'] == 'Security Verification Required')
    assert notice()['is_read'] is False and 'Please confirm whether you initiated' in notice()['message']
    _answer(client, rahul, attempt['id'], 'YES')
    assert notice()['is_read'] is True


def test_yes_completes_payment_and_receiver_sees_it(client, app, fr):
    rahul, attempt = _example_attempt(client, app, fr)
    before_rahul, before_priya = balance(app, 'rahul@demo.bank'), balance(app, 'priya@demo.bank')
    body = _answer(client, rahul, attempt['id'], 'YES').get_json()
    txn = body['data']['transaction']
    assert body['message'] == YES_MESSAGE and txn['status'] == 'COMPLETED'
    assert txn['confirmation']['response'] == 'YES' and txn['confirmation']['responded_at']
    assert 'authorized by the account owner' in txn['final_reason']
    assert balance(app, 'rahul@demo.bank') == before_rahul - 80000
    assert balance(app, 'priya@demo.bank') == before_priya + 80000

    priya = client.get('/api/receiver/payments', headers=login(client, 'priya@demo.bank')).get_json()['data']['items']
    assert priya[0]['id'] == attempt['id'] and priya[0]['credited'] is True
    titles = [n['title'] for n in client.get('/api/notifications', headers=rahul).get_json()['data']['items']]
    assert 'Payment successful' in titles
    analyst = login(client, 'analyst@demo.bank')
    shown = client.get(f"/api/detection/transactions/{attempt['id']}", headers=analyst).get_json()['data']
    assert shown['outcome_label'] == 'USER AUTHORIZED – PAYMENT SUCCESSFUL' and shown['risk_score'] == 50


def test_no_blocks_immediately_and_every_dashboard_agrees(client, app, fr):
    rahul, attempt = _example_attempt(client, app, fr)
    before_rahul, before_priya = balance(app, 'rahul@demo.bank'), balance(app, 'priya@demo.bank')
    res = _answer(client, rahul, attempt['id'], 'no')
    assert res.status_code == 200 and res.get_json()['message'] == NO_MESSAGE
    txn = res.get_json()['data']['transaction']
    assert txn['status'] == 'BLOCKED' and txn['final_reason'] == DENIED_REASON
    assert txn['outcome_label'] == 'USER DENIED – PAYMENT BLOCKED' and txn['money_moved'] is False
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
    assert shown['outcome_label'] == 'USER DENIED – PAYMENT BLOCKED' and shown['confirmation']['response'] == 'NO'
    assert confirmations['recent'][0]['id'] == attempt['id'] and confirmations['counts']['no'] == 1
    assert frauder[0]['transaction_id'] == attempt['id']
    assert frauder[0]['outcome_label'] == 'USER DENIED – PAYMENT BLOCKED'
    priya = client.get('/api/receiver/payments', headers=login(client, 'priya@demo.bank')).get_json()['data']['items']
    assert attempt['id'] not in [t['id'] for t in priya]          # never shown as received money
    result = client.get(f"/api/frauder/transactions/{attempt['id']}", headers=fr.headers).get_json()['data']
    labels = [i['label'] for i in result['timeline']]
    assert 'Confirmation requested from Rahul' in labels and 'Rahul answered NO' in labels


def test_receiver_never_sees_a_pending_payment(client, fr):
    attempt = fr.transfer(30000, device='new')
    priya = login(client, 'priya@demo.bank')
    assert attempt['id'] not in [t['id'] for t in
                                 client.get('/api/receiver/payments', headers=priya).get_json()['data']['items']]


# ── No answer → EXPIRED, never authorized ───────────────────────────────────

def test_unanswered_confirmation_expires(client, app, fr):
    attempt = fr.transfer(2000, receiver='quickcash')
    _expire_now(app, attempt['id'])
    rahul = login(client, 'rahul@demo.bank')
    data = client.get('/api/user/dashboard', headers=rahul).get_json()['data']
    assert data['pending_confirmations'] == []
    txn = client.get(f"/api/user/transactions/{attempt['id']}", headers=rahul).get_json()['data']
    assert txn['status'] == 'EXPIRED' and txn['outcome_label'] == 'EXPIRED – NOT AUTHORIZED'
    assert 'did not respond within 30 minutes' in txn['final_reason']
    assert balance(app, 'rahul@demo.bank') == OPENING['rahul@demo.bank']
    assert balance(app, 'quickcash@demo.bank') == OPENING['quickcash@demo.bank']


def test_block_policy_on_expiry(client, app, fr):
    _set(app, CONFIRMATION_EXPIRY_ACTION='BLOCK')
    attempt = fr.transfer(2000, receiver='quickcash')
    _expire_now(app, attempt['id'])
    result = client.get(f"/api/frauder/transactions/{attempt['id']}", headers=fr.headers).get_json()['data']
    assert result['status'] == 'BLOCKED' and result['outcome_label'] == 'NO RESPONSE – BLOCKED'


def test_hold_policy_on_expiry_still_never_approves(client, app, fr):
    _set(app, CONFIRMATION_EXPIRY_ACTION='HOLD')
    attempt = fr.transfer(2000, receiver='quickcash')
    _expire_now(app, attempt['id'])
    result = client.get(f"/api/frauder/transactions/{attempt['id']}", headers=fr.headers).get_json()['data']
    assert result['status'] == 'UNDER_REVIEW' and result['review_stage'] == 'AWAITING_ANALYST'
    assert result['confirmation']['status'] == 'EXPIRED' and result['money_moved'] is False


# ── Who may answer, and only once, and only in time ─────────────────────────

def test_only_the_owner_can_answer(client, app, fr):
    attempt = fr.transfer(2000, receiver='quickcash')
    url = f"/api/transactions/{attempt['id']}/confirmation"
    karan = login(client, 'karan@demo.bank')
    assert client.post(url, headers=karan, json={'response': 'NO'}).status_code == 404
    for email in ('priya@demo.bank', 'analyst@demo.bank', 'frauder@demo.bank'):
        assert client.post(url, headers=login(client, email), json={'response': 'YES'}).status_code == 403
    assert client.post(url, json={'response': 'YES'}).status_code == 401
    rahul = login(client, 'rahul@demo.bank')
    assert client.post(url, headers=rahul, json={'response': 'MAYBE'}).status_code == 422
    # A user id in the body is ignored: identity comes from the login session.
    assert client.post(url, headers=karan, json={'response': 'YES', 'user_id': fr.ids['rahul']}).status_code == 404
    assert client.get('/api/transactions/confirmations', headers=rahul).get_json()['data'][0]['id'] == attempt['id']
    assert client.get('/api/transactions/confirmations', headers=karan).get_json()['data'] == []
    assert balance(app, 'quickcash@demo.bank') == OPENING['quickcash@demo.bank']


def test_duplicate_answers_are_rejected_and_money_moves_once(client, app, fr):
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
    assert balance(app, 'rahul@demo.bank') == OPENING['rahul@demo.bank'] - 2000      # debited exactly once
    assert balance(app, 'quickcash@demo.bank') == OPENING['quickcash@demo.bank'] + 2000


def test_answer_after_expiry_is_rejected(client, app, fr):
    attempt = fr.transfer(2000, receiver='quickcash')
    _expire_now(app, attempt['id'])
    rahul = login(client, 'rahul@demo.bank')
    res = _answer(client, rahul, attempt['id'], 'YES')
    assert res.status_code == 410 and res.get_json()['error']['code'] == 'CONFIRMATION_EXPIRED'
    assert _answer(client, rahul, attempt['id'], 'YES').status_code == 410
    assert balance(app, 'quickcash@demo.bank') == OPENING['quickcash@demo.bank']


def test_yes_with_insufficient_balance_is_explained_not_processed(client, app, fr):
    attempt = fr.transfer(30000, device='new')
    with app.app_context():
        User.query.filter_by(email='rahul@demo.bank').one().primary_account.balance = Decimal('100')
        db.session.commit()
        db.session.remove()
    body = _answer(client, login(client, 'rahul@demo.bank'), attempt['id'], 'YES').get_json()['data']
    assert body['outcome'] == 'blocked' and body['transaction']['status'] == 'BLOCKED'
    assert 'lower than the amount' in body['transaction']['final_reason']
    assert balance(app, 'rahul@demo.bank') == Decimal('100')
    assert balance(app, 'priya@demo.bank') == OPENING['priya@demo.bank']


def test_frauder_cannot_answer_or_change_the_confirmation(client, app, fr):
    attempt = fr.transfer(2000, receiver='quickcash')
    url = f"/api/transactions/{attempt['id']}/confirmation"
    assert client.post(url, headers=fr.headers, json={'response': 'YES'}).status_code == 403
    assert client.post(f"/api/transactions/{attempt['id']}/report-fraud", headers=fr.headers).status_code == 403
    with app.app_context():
        assert db.session.get(Transaction, attempt['id']).confirmation_status == 'PENDING'
        db.session.remove()


# ── Manually typed attacker details ─────────────────────────────────────────

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
    assert ctx['policy'] == {'confirmation_expiry_minutes': 30, 'expiry_action': 'EXPIRE', 'hard_block_rules': []}
    guide = client.get('/api/frauder/rule-guide', headers=fr.headers).get_json()['data']
    assert all('preset' not in g for g in guide)


def test_total_money_is_conserved_across_yes_and_no(client, app, fr):
    accounts = ('rahul@demo.bank', 'priya@demo.bank')
    total = sum(balance(app, a) for a in accounts)
    rahul, attempt = _example_attempt(client, app, fr)
    _answer(client, rahul, attempt['id'], 'NO')
    second = fr.transfer(80000, device='ATK-PHONE-02', city='delhi', ip='49.36.12.9')
    assert second['status'] == 'UNDER_REVIEW'
    _answer(client, rahul, second['id'], 'YES')
    assert sum(balance(app, a) for a in accounts) == total
    assert balance(app, 'rahul@demo.bank') == OPENING['rahul@demo.bank'] - Decimal('3000') - 80000


def test_security_notice_stays_open_until_answered(client, app, fr):
    attempt = fr.transfer(30000, device='new')
    rahul = login(client, 'rahul@demo.bank')

    def notice():
        items = client.get('/api/notifications', headers=rahul).get_json()['data']['items']
        return next(n for n in items if n['title'] == 'Security Verification Required')
    client.post(f"/api/notifications/{notice()['id']}/read", headers=rahul)
    client.post('/api/notifications/read-all', headers=rahul)
    assert notice()['is_read'] is False                          # still waiting for YES/NO
    _answer(client, rahul, attempt['id'], 'NO')
    assert notice()['is_read'] is True
