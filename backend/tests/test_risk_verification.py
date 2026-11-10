"""Every payment on which a risk factor fires is held for the owner, whatever the
score. YES leads to an OTP sent to the owner's registered contacts; only a correct,
unexpired OTP authorizes it. NO stops it and blocks the receiver account.

Payments are pinned to midday so R5 (odd hour) never adds to the score; the
watch-listed receiver (R6) is re-weighted to land in each band."""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from portal.extensions import db
from portal.helpers import analytics, payment_engine
from portal.models import Account, FraudRule, ReceiverBlock, Transaction, User, VerificationChallenge, WatchlistEntry, now

from .conftest import answer, balance, login, otp_from, send
from .test_frauder import fr  # noqa: F401  (fixture)

NOON = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)


def _pay(app, amount, upi='quickcash@fsbank', r6_weight=None, owner_must_confirm=False):
    with app.app_context():
        if r6_weight is not None:
            FraudRule.query.filter_by(code='R6').first().weight = r6_weight
            db.session.commit()
        rahul = User.query.filter_by(email='rahul@demo.bank').first()
        txn, _ = payment_engine.send_money(rahul, 'UPI', {'upi_id': upi}, Decimal(amount), txn_time=NOON,
                                           owner_must_confirm=owner_must_confirm)
        out = {'id': txn.id, 'status': txn.status, 'decision': txn.decision, 'score': txn.risk_score,
               'rules': sorted(r.rule_code for r in txn.triggered_rules), 'latency_ms': float(txn.latency_ms),
               'confirmation': txn.confirmation_status, 'display': txn.display_status()}
        db.session.remove()
        return out


# ── 1. Any risk factor → verification, whatever the score ──────────────────

@pytest.mark.parametrize('weight, band', [(20, 'APPROVED'), (50, 'REVIEW'), (69, 'REVIEW')])
def test_any_risk_factor_below_the_blocking_threshold_is_held_for_the_owner(app, weight, band):
    t = _pay(app, 1000, r6_weight=weight)
    assert t['rules'] == ['R6'] and t['score'] == weight and t['decision'] == band   # band is still recorded
    assert t['status'] == 'UNDER_REVIEW' and t['confirmation'] == 'PENDING'          # never auto-approved/blocked
    assert t['display'] == 'USER_CONFIRMATION_PENDING'
    assert balance(app, 'rahul@demo.bank') == Decimal('250000')
    assert balance(app, 'quickcash@demo.bank') == Decimal('5000')


def test_no_risk_factor_completes_normally(app):
    t = _pay(app, 1000, upi='priya@fsbank')
    assert t['rules'] == [] and t['status'] == 'COMPLETED' and t['confirmation'] is None
    assert balance(app, 'priya@demo.bank') == Decimal('26000')


def test_frauder_attempts_are_always_held(app):
    assert _pay(app, 1000, upi='priya@fsbank', owner_must_confirm=True)['status'] == 'UNDER_REVIEW'
    # At the blocking threshold a Frauder attempt is stopped like any other payment.
    assert _pay(app, 1000, r6_weight=90, owner_must_confirm=True)['status'] == 'BLOCKED'


def test_decision_is_made_within_the_request(app):
    t = _pay(app, 1000, r6_weight=80)
    assert t['status'] != 'PROCESSING' and t['latency_ms'] < 1000


def test_overview_counts_pending_verifications(app):
    for weight in (20, 50, 80):
        _pay(app, 1000, r6_weight=weight)
    with app.app_context():
        totals = analytics.summary()['totals']
        db.session.remove()
    # 20 and 50 wait for the owner; 80 reached the blocking threshold and was stopped.
    assert totals['pending_owner'] == 2 and totals['auto_approved'] == 0 and totals['auto_blocked'] == 1


def test_notification_wording(client):
    rahul = login(client, 'rahul@demo.bank')
    send(client, rahul, 1000, upi='quickcash@fsbank')
    notes = client.get('/api/notifications', headers=rahul).get_json()['data']['items']
    note = next(n for n in notes if n['title'] == 'Suspicious transaction detected')
    assert note['message'].startswith('Suspicious transaction detected. Did you initiate this transaction?')


# ── 2. YES → OTP → authorized ───────────────────────────────────────────────

def _held(client, amount=1000, upi='quickcash@fsbank'):
    rahul = login(client, 'rahul@demo.bank')
    data = send(client, rahul, amount, upi=upi).get_json()['data']
    assert data['status'] == 'UNDER_REVIEW'
    return rahul, data


def test_yes_sends_an_otp_and_moves_no_money_until_it_is_verified(client, app):
    rahul, data = _held(client)
    res = client.post(f"/api/transactions/{data['id']}/confirmation", headers=rahul, json={'response': 'YES'})
    body = res.get_json()['data']
    assert res.status_code == 200 and body['outcome'] == 'otp_sent'
    assert body['otp']['sent_to'] == ['+91 ••••••0001', 'r•••@demo.bank']           # registered contacts, masked
    assert body['transaction']['display_status'] == 'OTP_VERIFICATION_PENDING'
    assert body['transaction']['outcome_label'] == 'USER SAID YES – OTP PENDING'
    assert balance(app, 'rahul@demo.bank') == Decimal('250000')                    # nothing moved on YES alone
    notes = client.get('/api/notifications', headers=rahul).get_json()['data']['items']
    assert all(n['category'] != 'OTP' for n in notes)                       # not listed in the notification centre
    with app.app_context():                                                    # but delivered (stored) for the demo
        from portal.models import Notification
        assert Notification.query.filter(Notification.category == 'OTP',
                                         Notification.message.contains(otp_from(res))).count() == 1
        db.session.remove()
    with app.app_context():                                                        # only a hash is stored
        assert otp_from(res) not in VerificationChallenge.query.filter_by(transaction_id=data['id']).one().otp_hash
        db.session.remove()

    ok = client.post(f"/api/transactions/{data['id']}/verification/confirm", headers=rahul,
                     json={'otp': otp_from(res)}).get_json()
    assert ok['data']['outcome'] == 'authorized' and ok['data']['transaction']['display_status'] == 'SUCCESSFUL'
    assert ok['data']['transaction']['confirmation']['otp']['status'] == 'VERIFIED'
    assert balance(app, 'rahul@demo.bank') == Decimal('249000')
    assert balance(app, 'quickcash@demo.bank') == Decimal('6000')


def test_high_risk_payment_cannot_be_authorized_by_the_owner(client, app):
    analyst = login(client, 'analyst@demo.bank')
    client.put('/api/detection/rules/R6', headers=analyst, json={'weight': 90})
    rahul = login(client, 'rahul@demo.bank')
    data = send(client, rahul, 1000, upi='quickcash@fsbank').get_json()['data']
    assert data['risk_score'] == 90 and data['status'] == 'BLOCKED' and data['confirmation'] is None
    res = client.post(f"/api/transactions/{data['id']}/confirmation", headers=rahul, json={'response': 'YES'})
    assert res.status_code == 409                                     # nothing for the owner to answer
    assert balance(app, 'quickcash@demo.bank') == Decimal('5000')


def test_wrong_otp_never_authorizes_and_too_many_block(client, app):
    rahul, data = _held(client)
    client.post(f"/api/transactions/{data['id']}/confirmation", headers=rahul, json={'response': 'YES'})
    url = f"/api/transactions/{data['id']}/verification/confirm"
    codes = [client.post(url, headers=rahul, json={'otp': '000000'}).get_json()['error']['code'] for _ in range(3)]
    assert codes == ['VERIFICATION_INCORRECT', 'VERIFICATION_INCORRECT', 'VERIFICATION_FAILED']
    txn = client.get(f"/api/user/transactions/{data['id']}", headers=rahul).get_json()['data']
    assert txn['status'] == 'BLOCKED' and txn['outcome_label'] == 'OTP FAILED – PAYMENT BLOCKED'
    assert txn['confirmation']['otp']['status'] == 'FAILED'
    assert balance(app, 'rahul@demo.bank') == Decimal('250000')


def test_expired_otp_never_authorizes_and_a_new_one_can_be_sent(client, app):
    rahul, data = _held(client)
    first = client.post(f"/api/transactions/{data['id']}/confirmation", headers=rahul, json={'response': 'YES'})
    with app.app_context():
        VerificationChallenge.query.filter_by(transaction_id=data['id']).one().expires_at = now() - timedelta(seconds=1)
        db.session.commit()
        db.session.remove()
    url = f"/api/transactions/{data['id']}/verification/confirm"
    expired = client.post(url, headers=rahul, json={'otp': otp_from(first)})
    assert expired.status_code == 410 and expired.get_json()['error']['code'] == 'OTP_EXPIRED'
    assert balance(app, 'rahul@demo.bank') == Decimal('250000')

    resent = client.post(f"/api/transactions/{data['id']}/verification/start", headers=rahul)
    assert resent.status_code == 200
    assert client.post(url, headers=rahul, json={'otp': otp_from(first)}).status_code == 422   # the old code is void
    assert client.post(url, headers=rahul, json={'otp': otp_from(resent)}).get_json()['data']['outcome'] == 'authorized'


@pytest.mark.parametrize('otp', ['', '12345', 'abcdef', '1234567'])
def test_otp_format_is_validated(client, otp):
    rahul, data = _held(client)
    client.post(f"/api/transactions/{data['id']}/confirmation", headers=rahul, json={'response': 'YES'})
    res = client.post(f"/api/transactions/{data['id']}/verification/confirm", headers=rahul, json={'otp': otp})
    assert res.status_code == 422


def test_otp_cannot_be_used_before_yes_or_by_someone_else(client):
    rahul, data = _held(client)
    url = f"/api/transactions/{data['id']}/verification/confirm"
    assert client.post(url, headers=rahul, json={'otp': '123456'}).get_json()['error']['code'] == 'NO_OTP_PENDING'
    yes = client.post(f"/api/transactions/{data['id']}/confirmation", headers=rahul, json={'response': 'YES'})
    karan = login(client, 'karan@demo.bank')
    assert client.post(url, headers=karan, json={'otp': otp_from(yes)}).status_code == 404
    assert client.post(url, headers=login(client, 'frauder@demo.bank'), json={'otp': otp_from(yes)}).status_code == 403


def test_verified_otp_cannot_pay_twice(client, app):
    rahul, data = _held(client)
    yes = client.post(f"/api/transactions/{data['id']}/confirmation", headers=rahul, json={'response': 'YES'})
    url = f"/api/transactions/{data['id']}/verification/confirm"
    assert client.post(url, headers=rahul, json={'otp': otp_from(yes)}).status_code == 200
    assert client.post(url, headers=rahul, json={'otp': otp_from(yes)}).status_code == 409
    assert balance(app, 'rahul@demo.bank') == Decimal('249000')


# ── 3. NO → stop and block the receiver ─────────────────────────────────────

def test_no_blocks_the_receiver_account_in_the_database(client, app):
    rahul, data = _held(client, 2500)
    res = answer(client, rahul, data['id'], 'NO').get_json()['data']
    assert res['transaction']['status'] == 'CANCELLED' and res['receiver_block']['status'] == 'ACTIVE'
    with app.app_context():
        account = Account.query.filter_by(upi_id='quickcash@fsbank').one()
        assert account.status == 'BLOCKED'
        block = ReceiverBlock.query.one()
        assert block.transaction_id == data['id'] and block.risk_score == 50
        assert [f['code'] for f in block.risk_factors] == ['R6'] and block.blocked_at is not None
        assert block.transaction_snapshot['amount'] == 2500 and block.transaction_snapshot['sender'] == 'Rahul Sharma'
        assert 'denied' in block.reason
        flags = {(w.entity_type, w.entity_value) for w in WatchlistEntry.query.filter_by(is_active=True).all()}
        assert ('UPI', 'quickcash@fsbank') in flags and ('ACCOUNT', account.account_number) in flags
        db.session.remove()
    assert balance(app, 'rahul@demo.bank') == Decimal('250000')


def test_blocked_receiver_cannot_receive_from_anyone(client, app):
    rahul, data = _held(client)
    answer(client, rahul, data['id'], 'NO')
    karan = login(client, 'karan@demo.bank')
    for headers in (rahul, karan):
        res = send(client, headers, 100, upi='quickcash@fsbank')
        assert res.status_code == 409 and res.get_json()['error']['code'] == 'RECEIVER_BLOCKED'
    lookup = client.post('/api/user/receivers/lookup', headers=karan,
                         json={'payment_method': 'UPI', 'upi_id': 'quickcash@fsbank'})
    assert lookup.status_code == 409
    with app.app_context():
        qc = Account.query.filter_by(upi_id='quickcash@fsbank').one()
        bank = client.post('/api/transactions/send', headers=karan, json={
            'payment_method': 'BANK_TRANSFER', 'account_number': qc.account_number, 'ifsc': qc.ifsc, 'amount': 100})
        db.session.remove()
    assert bank.status_code == 409
    assert balance(app, 'quickcash@demo.bank') == Decimal('5000')


def test_held_payments_to_a_newly_blocked_receiver_cannot_be_authorized(client, app):
    rahul, first = _held(client)
    _, second = _held(client)
    answer(client, rahul, first['id'], 'NO')
    result = answer(client, rahul, second['id'], 'YES').get_json()['data']
    assert result['outcome'] == 'blocked' and 'blocked after a fraud report' in result['transaction']['final_reason']
    assert balance(app, 'quickcash@demo.bank') == Decimal('5000')


def test_blocked_account_status_is_visible_and_it_can_still_pay_out(client, app):
    rahul, data = _held(client)
    answer(client, rahul, data['id'], 'NO')
    quick = login(client, 'quickcash@demo.bank')
    dash = client.get('/api/user/dashboard', headers=quick).get_json()['data']
    assert dash['account']['status'] == 'BLOCKED'
    notes = client.get('/api/notifications', headers=quick).get_json()['data']['items']
    assert any('blocked from receiving' in n['title'] for n in notes)
    assert send(client, quick, 100, upi='priya@fsbank').status_code == 201       # receiving only is blocked


def test_analyst_can_lift_a_block_with_a_reason(client, app):
    rahul, data = _held(client)
    answer(client, rahul, data['id'], 'NO')
    analyst = login(client, 'analyst@demo.bank')
    blocks = client.get('/api/detection/receiver-blocks?status=ACTIVE', headers=analyst).get_json()['data']
    assert len(blocks) == 1 and blocks[0]['receiver']['account_status'] == 'BLOCKED'
    url = f"/api/detection/receiver-blocks/{blocks[0]['id']}/lift"
    assert client.post(url, headers=analyst, json={'reason': ''}).status_code == 422
    assert client.post(url, headers=rahul, json={'reason': 'not allowed'}).status_code == 403
    lifted = client.post(url, headers=analyst, json={'reason': 'Merchant verified by phone'}).get_json()['data']
    assert lifted['status'] == 'LIFTED' and lifted['receiver']['account_status'] == 'ACTIVE'
    assert client.post(url, headers=analyst, json={'reason': 'again please'}).status_code == 409
    with app.app_context():
        assert not WatchlistEntry.query.filter(WatchlistEntry.reason.like('Receiver blocked:%'),
                                               WatchlistEntry.is_active.is_(True)).count()
        db.session.remove()
    assert send(client, login(client, 'karan@demo.bank'), 100, upi='quickcash@fsbank').status_code == 201


# ── 4. Frauder dashboard: real records only ─────────────────────────────────

def test_frauder_records_are_real_detection_records(client, app):
    from portal.seeders.seed_transactions import seed_transactions
    with app.app_context():                                     # seeded sample history is not a record
        seed_transactions(db.session.connection())
        db.session.commit()
        db.session.remove()
    frauder = login(client, 'frauder@demo.bank')
    assert client.get('/api/frauder/records', headers=frauder).get_json()['data']['transactions'] == []

    rahul, denied = _held(client, 1500)
    _, authorized = _held(client, 700, upi='quickcash@fsbank')
    answer(client, rahul, authorized['id'], 'YES')
    answer(client, rahul, denied['id'], 'NO')
    send(client, rahul, 300, upi='priya@fsbank')                # no risk: not a detection record

    data = client.get('/api/frauder/records', headers=frauder).get_json()['data']
    rows = {r['transaction_id']: r for r in data['transactions']}
    assert set(rows) == {denied['id'], authorized['id']}
    assert rows[denied['id']]['user_response'] == 'NO' and rows[denied['id']]['risk_factors'][0]['code'] == 'R6'
    assert rows[denied['id']]['receiver_account_status'] == 'BLOCKED'
    assert rows[authorized['id']]['user_response'] == 'YES' and rows[authorized['id']]['otp']['status'] == 'VERIFIED'
    assert all(r['detected_at'] and r['risk_score'] == 50 for r in rows.values())
    assert data['summary']['user_yes'] == 1 and data['summary']['user_no'] == 1
    assert data['summary']['blocked_receivers'] == 1
    assert data['blocked_receivers'][0]['transaction']['txn_ref'] == denied['txn_ref']
    assert [f['upi_id'] for f in data['flagged_receivers']] == ['quickcash@fsbank']   # engine flag only, no seeds
    assert data['flagged_receivers'][0]['source'] == 'AUTO'
    assert client.get('/api/frauder/records', headers=rahul).status_code == 403


def test_frauder_views_do_not_echo_typed_attacker_details(client, fr):
    result = fr.transfer(1200, device='ATK-77', city='delhi', ip='49.36.12.8', target_location='Karol Bagh')
    assert result['simulated_details'] is None
    history = client.get('/api/frauder/attempts', headers=fr.headers).get_json()['data']
    assert all('simulated_details' not in row for row in history)
    ctx = client.get('/api/frauder/context', headers=fr.headers).get_json()['data']
    assert all('attacker_devices' not in v for v in ctx['victims'])
    assert client.get('/api/frauder/rule-guide', headers=fr.headers).status_code == 404


def test_frauder_reset_undoes_blocks_from_frauder_attempts_only(client, app, fr):
    attempt = fr.transfer(1000, receiver='amit')
    rahul = login(client, 'rahul@demo.bank')
    answer(client, rahul, attempt['id'], 'NO')
    genuine = send(client, rahul, 1000, upi='quickcash@fsbank').get_json()['data']
    answer(client, rahul, genuine['id'], 'NO')
    client.post('/api/frauder/reset', headers=fr.headers, json={'confirm': 'RESET'})
    with app.app_context():
        assert Account.query.filter_by(upi_id='amit@fsbank').one().status == 'ACTIVE'
        assert Account.query.filter_by(upi_id='quickcash@fsbank').one().status == 'BLOCKED'
        assert ReceiverBlock.query.count() == 1
        assert Transaction.query.filter_by(id=genuine['id']).count() == 1
        db.session.remove()


def test_frauder_transfer_without_attempt_context(client, app, fr):
    """The console sends only target, receiver, amount and scenario: the attempt
    uses the victim's home city and registered device, and is still held."""
    res = client.post('/api/frauder/transfer', headers=fr.headers, json={
        'victim_id': fr.ids['rahul'], 'receiver_id': fr.ids['quickcash'], 'amount': 2000})
    assert res.status_code == 201, res.get_json()
    data = res.get_json()['data']
    assert data['city'] == 'Mumbai' and data['device']['is_trusted'] is True and data['ip_address'] is None
    assert [t['code'] for t in data['rule_trace'] if t['status'] == 'TRIGGERED'] == ['R6']
    assert data['display_status'] == 'PROCESSING'
    assert balance(app, 'rahul@demo.bank') == Decimal('250000')


def test_frauder_transfer_uses_the_city_chosen_at_sign_in(client, app, fr):
    """Signed in from another city, the Frauder's attempts come from that city
    (still on the victim's registered device). Keeping "My home city" leaves the
    victim's home city, as above."""
    from portal.models import Location
    with app.app_context():
        hyderabad = Location.query.filter_by(city='Hyderabad').one().id
        db.session.remove()
    elsewhere = login(client, 'frauder@demo.bank', location_id=hyderabad)
    res = client.post('/api/frauder/transfer', headers=elsewhere, json={
        'victim_id': fr.ids['rahul'], 'receiver_id': fr.ids['amit'], 'amount': 1500})
    assert res.status_code == 201, res.get_json()
    data = res.get_json()['data']
    assert data['city'] == 'Hyderabad' and data['device']['is_trusted'] is True
    with app.app_context():
        assert db.session.get(Transaction, data['id']).simulated_details['city'] == 'Hyderabad'
        db.session.remove()


# ── Notifications: "Mark all read" clears the list ─────────────────────────

def test_mark_all_read_clears_the_notification_list(client, app):
    rahul = login(client, 'rahul@demo.bank')
    for amount in (100, 200):
        send(client, rahul, amount, upi='priya@fsbank')                 # two "Payment successful" notices
    _, held = _held(client)                                             # an open verification request
    yes = client.post(f"/api/transactions/{held['id']}/confirmation", headers=rahul, json={'response': 'YES'})
    before = client.get('/api/notifications', headers=rahul).get_json()['data']
    assert len(before['items']) >= 3 and all(n['category'] != 'OTP' for n in before['items'])   # OTPs not listed

    res = client.post('/api/notifications/read-all', headers=rahul)
    assert res.status_code == 200 and res.get_json()['data']['cleared'] >= 2
    after = client.get('/api/notifications', headers=rahul).get_json()['data']
    assert after['items'] == [] and after['unread'] == 0

    client.post(f"/api/transactions/{held['id']}/verification/confirm", headers=rahul, json={'otp': otp_from(yes)})
    client.post('/api/notifications/read-all', headers=rahul)
    assert client.get('/api/notifications', headers=rahul).get_json()['data']['items'] == []
    with app.app_context():                                             # cleared, not deleted
        from portal.models import Notification
        assert Notification.query.filter(Notification.cleared_at.isnot(None)).count() >= 4
        db.session.remove()


def test_open_verification_request_survives_mark_all_read(client):
    rahul, held = _held(client)
    client.post('/api/notifications/read-all', headers=rahul)
    items = client.get('/api/notifications', headers=rahul).get_json()['data']['items']
    assert [n['title'] for n in items] == ['Suspicious transaction detected']


def test_no_ends_as_cancelled_and_frauder_sees_only_the_outcome(client, app, fr):
    attempt = fr.transfer(1500, receiver='amit')
    assert attempt['outcome_label'] == 'PROCESSING' and attempt['confirmation'] is None
    answer(client, login(client, 'rahul@demo.bank'), attempt['id'], 'NO')
    result = client.get(f"/api/frauder/transactions/{attempt['id']}", headers=fr.headers).get_json()['data']
    assert result['status'] == 'CANCELLED' and result['outcome_label'] == 'CANCELLED'
    assert result['risk_explanation'] is None and result['final_reason'] is None
    second = fr.transfer(1500, receiver='priya')
    answer(client, login(client, 'rahul@demo.bank'), second['id'], 'YES')
    done = client.get(f"/api/frauder/transactions/{second['id']}", headers=fr.headers).get_json()['data']
    assert done['outcome_label'] == 'SUCCESS'
    records = client.get('/api/frauder/records', headers=fr.headers).get_json()['data']
    assert {r['status'] for r in records['transactions']} == {'SUCCESS', 'CANCELLED'}
    assert records['summary']['successful'] == 1 and records['summary']['cancelled'] == 1


def test_dashboard_shows_the_demo_otp_only_while_it_is_needed(client):
    rahul, held = _held(client)
    card = lambda: next(c for c in client.get('/api/user/dashboard', headers=rahul).get_json()['data']  # noqa: E731
                        ['pending_confirmations'] if c['id'] == held['id'])
    assert card()['demo_otp'] is None                                   # nothing sent before YES
    yes = client.post(f"/api/transactions/{held['id']}/confirmation", headers=rahul, json={'response': 'YES'})
    assert card()['demo_otp'] == otp_from(yes)
    resent = client.post(f"/api/transactions/{held['id']}/verification/start", headers=rahul)
    assert card()['demo_otp'] == otp_from(resent)                       # always the latest code
    client.post(f"/api/transactions/{held['id']}/verification/confirm", headers=rahul, json={'otp': otp_from(resent)})
    assert client.get('/api/user/dashboard', headers=rahul).get_json()['data']['pending_confirmations'] == []
