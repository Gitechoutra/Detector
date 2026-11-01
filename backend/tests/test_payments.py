from decimal import Decimal

import pytest

from portal.extensions import db
from portal.models import Account, Alert, Notification, SystemSetting, Transaction, User
from portal.helpers import payment_engine

from .conftest import balance, login, send

# Written for the owner-confirmation policy (DECISION_MODE=OWNER_CONFIRM);
# the automatic policy is covered by test_auto_decisions.py.
pytestmark = pytest.mark.usefixtures('owner_confirm')


def _otp_from_sms(client, headers, txn_id):
    res = client.post(f'/api/transactions/{txn_id}/verification/start', headers=headers)
    assert res.status_code == 200, res.get_json()
    sms = res.get_json()['data']['simulated_sms']
    return sms.split('OTP ')[1][:6]


def test_normal_payment_is_approved_and_credited(client, app):
    headers = login(client, 'rahul@demo.bank')
    res = send(client, headers, 500)
    assert res.status_code == 201
    data = res.get_json()['data']
    assert data['status'] == 'COMPLETED' and data['risk_score'] == 0
    assert balance(app, 'rahul@demo.bank') == Decimal('249500')
    assert balance(app, 'priya@demo.bank') == Decimal('25500')

    priya = login(client, 'priya@demo.bank')
    incoming = client.get('/api/receiver/payments', headers=priya).get_json()['data']['items']
    assert incoming[0]['credited'] is True and incoming[0]['amount'] == 500
    notes = client.get('/api/notifications', headers=priya).get_json()['data']['items']
    assert any('credited' in n['message'] for n in notes)


def test_watchlisted_receiver_goes_to_review_without_moving_money(client, app):
    headers = login(client, 'rahul@demo.bank')
    data = send(client, headers, 10000, upi='quickcash@fsbank').get_json()['data']
    assert data['status'] == 'UNDER_REVIEW' and data['decision'] == 'REVIEW' and data['risk_score'] == 50
    assert [r['code'] for r in data['rules']] == ['R6']
    assert balance(app, 'rahul@demo.bank') == Decimal('250000')
    assert balance(app, 'quickcash@demo.bank') == Decimal('5000')
    with app.app_context():
        assert Alert.query.filter_by(transaction_id=data['id'], severity='MEDIUM').count() == 1
        db.session.remove()
    qc = login(client, 'quickcash@demo.bank')
    # The receiver sees incoming payments only once approved – never a held one.
    assert client.get('/api/receiver/payments', headers=qc).get_json()['data']['items'] == []
    stats = client.get('/api/receiver/dashboard', headers=qc).get_json()['data']['stats']
    assert stats == {'credited': 0, 'total_received': 0.0}


def test_insufficient_balance_is_rejected_without_a_record(client, app):
    headers = login(client, 'rahul@demo.bank')
    res = send(client, headers, 300000)
    assert res.status_code == 422 and res.get_json()['error']['code'] == 'INSUFFICIENT_BALANCE'
    with app.app_context():
        assert Transaction.query.count() == 0
        db.session.remove()


@pytest.mark.parametrize('body,code', [
    ({'payment_method': 'UPI', 'upi_id': 'rahul@fsbank', 'amount': 10}, 'SAME_ACCOUNT'),
    ({'payment_method': 'UPI', 'upi_id': 'nobody@fsbank', 'amount': 10}, 'RECEIVER_NOT_FOUND'),
    ({'payment_method': 'UPI', 'upi_id': 'priya@fsbank', 'amount': -5}, 'VALIDATION_ERROR'),
    ({'payment_method': 'UPI', 'upi_id': 'priya@fsbank', 'amount': '10.555'}, 'VALIDATION_ERROR'),
    ({'payment_method': 'CASH', 'amount': 10}, 'VALIDATION_ERROR'),
])
def test_invalid_payments_are_rejected(client, body, code):
    headers = login(client, 'rahul@demo.bank')
    res = client.post('/api/transactions/send', json=body, headers=headers)
    assert res.status_code in (404, 422) and res.get_json()['error']['code'] == code


def test_idempotent_resubmission_creates_one_payment(client, app):
    headers = login(client, 'rahul@demo.bank')
    first = send(client, headers, 700, key='form-123')
    second = send(client, headers, 700, key='form-123')
    assert first.status_code == 201 and second.status_code == 200
    assert second.get_json()['data']['replayed'] is True
    assert first.get_json()['data']['id'] == second.get_json()['data']['id']
    assert balance(app, 'rahul@demo.bank') == Decimal('249300')


def test_qr_and_bank_transfer_methods(client, app):
    headers = login(client, 'rahul@demo.bank')
    priya = login(client, 'priya@demo.bank')
    qr = client.get('/api/receiver/dashboard', headers=priya).get_json()['data']['account']
    res = client.post('/api/transactions/send', headers=headers,
                      json={'payment_method': 'QR', 'qr_payload': qr['qr_payload'], 'amount': 250})
    assert res.status_code == 201 and res.get_json()['data']['status'] == 'COMPLETED'

    tampered = qr['qr_payload'].rsplit('tr=', 1)[0] + 'tr=forged'
    res = client.post('/api/transactions/send', headers=headers,
                      json={'payment_method': 'QR', 'qr_payload': tampered, 'amount': 250})
    assert res.status_code == 422 and res.get_json()['error']['code'] == 'INVALID_QR'

    res = client.post('/api/transactions/send', headers=headers, json={
        'payment_method': 'BANK_TRANSFER', 'account_number': qr['account_number'], 'ifsc': qr['ifsc'],
        'amount': 300})
    assert res.status_code == 201
    res = client.post('/api/transactions/send', headers=headers, json={
        'payment_method': 'BANK_TRANSFER', 'account_number': qr['account_number'], 'ifsc': 'FSBK0999999',
        'amount': 300})
    assert res.status_code == 422
    assert balance(app, 'priya@demo.bank') == Decimal('25550')


def _answer(client, headers, txn_id, response):
    return client.post(f'/api/transactions/{txn_id}/confirmation', headers=headers, json={'response': response})


def _hand_to_analyst(app, client, headers, txn_id):
    """No answer in time under the HOLD policy: the payment goes to the fraud team."""
    with app.app_context():
        db.session.get(SystemSetting, 'CONFIRMATION_EXPIRY_ACTION').setting_value = 'HOLD'
        txn = db.session.get(Transaction, txn_id)
        txn.confirmation_expires_at = txn.confirmation_expires_at.replace(year=2000)
        db.session.commit()
        db.session.remove()
    client.get('/api/user/dashboard', headers=headers)


def test_yes_authorizes_a_held_payment_whatever_the_score(client, app):
    login(client, 'rahul@demo.bank', device='usual-phone')
    headers = login(client, 'rahul@demo.bank', device='new-laptop')      # untrusted device
    data = send(client, headers, 30000).get_json()['data']
    assert data['status'] == 'UNDER_REVIEW' and data['display_status'] == 'USER_CONFIRMATION_PENDING'
    assert {r['code'] for r in data['rules']} == {'R4', 'R9'} and data['risk_score'] == 65
    assert balance(app, 'rahul@demo.bank') == Decimal('250000')

    res = _answer(client, headers, data['id'], 'YES')
    body = res.get_json()
    assert res.status_code == 200 and body['data']['outcome'] == 'authorized'
    assert body['message'] == 'Transaction successfully authorized. The amount has been transferred to the Receiver.'
    txn = body['data']['transaction']
    assert txn['display_status'] == 'SUCCESSFUL' and txn['outcome_label'] == 'USER AUTHORIZED – PAYMENT SUCCESSFUL'
    assert txn['risk_score'] == 65 and {r['code'] for r in txn['rules']} == {'R4', 'R9'}   # kept for investigation
    assert balance(app, 'rahul@demo.bank') == Decimal('220000')
    assert balance(app, 'priya@demo.bank') == Decimal('55000')


def test_otp_step_up_is_not_used_for_a_pending_confirmation(client):
    headers = login(client, 'rahul@demo.bank')
    data = send(client, headers, 10000, upi='quickcash@fsbank').get_json()['data']
    res = client.post(f"/api/transactions/{data['id']}/verification/start", headers=headers)
    assert res.status_code == 409 and res.get_json()['error']['code'] == 'USE_CONFIRMATION'


def test_yes_with_insufficient_balance_is_not_processed(client, app):
    headers = login(client, 'rahul@demo.bank')
    data = send(client, headers, 10000, upi='quickcash@fsbank').get_json()['data']
    with app.app_context():
        Account.query.filter_by(upi_id='rahul@fsbank').first().balance = Decimal('5000')
        db.session.commit()
        db.session.remove()
    result = _answer(client, headers, data['id'], 'YES').get_json()['data']
    assert result['outcome'] == 'blocked' and result['transaction']['status'] == 'BLOCKED'
    assert 'lower than the amount' in result['transaction']['final_reason']
    assert balance(app, 'rahul@demo.bank') == Decimal('5000')
    assert balance(app, 'quickcash@demo.bank') == Decimal('5000')


def test_yes_on_a_frozen_receiver_is_not_processed(client, app):
    headers = login(client, 'rahul@demo.bank')
    data = send(client, headers, 10000, upi='quickcash@fsbank').get_json()['data']
    with app.app_context():
        Account.query.filter_by(upi_id='quickcash@fsbank').first().status = 'FROZEN'
        db.session.commit()
        db.session.remove()
    result = _answer(client, headers, data['id'], 'YES').get_json()['data']
    assert result['outcome'] == 'blocked' and 'can no longer accept payments' in result['transaction']['final_reason']
    assert balance(app, 'rahul@demo.bank') == Decimal('250000')


def test_absolute_restriction_rule_blocks_without_asking(client, app):
    with app.app_context():
        db.session.get(SystemSetting, 'CONFIRMATION_HARD_BLOCK_RULES').setting_value = 'R6'
        db.session.commit()
        db.session.remove()
    headers = login(client, 'rahul@demo.bank')
    data = send(client, headers, 10000, upi='quickcash@fsbank').get_json()['data']
    assert data['status'] == 'BLOCKED' and data['confirmation'] is None
    assert 'absolute security restriction' in data['final_reason']
    assert _answer(client, headers, data['id'], 'YES').status_code == 409
    assert balance(app, 'quickcash@demo.bank') == Decimal('5000')


def test_high_score_still_waits_for_the_owner(client, app):
    analyst = login(client, 'analyst@demo.bank')
    client.put('/api/detection/rules/R6', headers=analyst, json={'weight': 80})
    headers = login(client, 'rahul@demo.bank')
    data = send(client, headers, 10000, upi='quickcash@fsbank').get_json()['data']
    assert data['risk_score'] == 80 and data['decision'] == 'BLOCKED'          # the band is still recorded
    assert data['display_status'] == 'USER_CONFIRMATION_PENDING'
    res = client.post(f"/api/detection/transactions/{data['id']}/decision", headers=analyst,
                      json={'action': 'APPROVE'})
    assert res.status_code == 409 and res.get_json()['error']['code'] == 'AWAITING_OWNER'
    assert balance(app, 'quickcash@demo.bank') == Decimal('5000')


def test_wrong_otp_three_times_declines_legacy_step_up(client, app):
    """The OTP flow is kept for payments confirmed under the earlier workflow."""
    headers = login(client, 'rahul@demo.bank')
    data = send(client, headers, 10000, upi='quickcash@fsbank').get_json()['data']
    with app.app_context():
        db.session.get(Transaction, data['id']).confirmation_status = 'CONFIRMED'
        db.session.commit()
        db.session.remove()
    _otp_from_sms(client, headers, data['id'])
    codes = []
    for _ in range(3):
        res = client.post(f"/api/transactions/{data['id']}/verification/confirm", headers=headers,
                          json={'otp': '000000', 'password': 'Rahul@123'})
        codes.append(res.get_json()['error']['code'])
    assert codes == ['VERIFICATION_INCORRECT', 'VERIFICATION_INCORRECT', 'VERIFICATION_FAILED']
    with app.app_context():
        assert db.session.get(Transaction, data['id']).status == 'DECLINED'
        db.session.remove()
    assert balance(app, 'rahul@demo.bank') == Decimal('250000')


def test_analyst_cannot_approve_when_reevaluation_blocks(client, app):
    headers = login(client, 'rahul@demo.bank')
    data = send(client, headers, 10000, upi='quickcash@fsbank').get_json()['data']
    _hand_to_analyst(app, client, headers, data['id'])
    analyst = login(client, 'analyst@demo.bank')
    client.put('/api/detection/rules/R6', headers=analyst, json={'weight': 90})
    res = client.post(f"/api/detection/transactions/{data['id']}/decision", headers=analyst,
                      json={'action': 'APPROVE'})
    assert res.status_code == 409 and res.get_json()['error']['code'] == 'REEVALUATION_BLOCKED'
    with app.app_context():
        assert db.session.get(Transaction, data['id']).status == 'BLOCKED'
        db.session.remove()


def test_analyst_reject_confirms_fraud(client, app):
    headers = login(client, 'rahul@demo.bank')
    data = send(client, headers, 10000, upi='quickcash@fsbank').get_json()['data']
    _hand_to_analyst(app, client, headers, data['id'])
    analyst = login(client, 'analyst@demo.bank')
    res = client.post(f"/api/detection/transactions/{data['id']}/decision", headers=analyst,
                      json={'action': 'REJECT', 'notes': 'Mule account'})
    assert res.status_code == 200
    with app.app_context():
        assert db.session.get(Transaction, data['id']).status == 'DECLINED'
        assert Alert.query.filter_by(transaction_id=data['id']).first().resolution == 'CONFIRMED_FRAUD'
        db.session.remove()


def test_pending_confirmation_cannot_be_cancelled_only_answered(client):
    headers = login(client, 'rahul@demo.bank')
    data = send(client, headers, 10000, upi='quickcash@fsbank').get_json()['data']
    res = client.post(f"/api/transactions/{data['id']}/cancel", headers=headers)
    assert res.status_code == 409 and res.get_json()['error']['code'] == 'USE_CONFIRMATION'


def test_failure_mid_pipeline_rolls_everything_back(client, app, monkeypatch):
    headers = login(client, 'rahul@demo.bank')

    def explode(*args, **kwargs):
        raise RuntimeError('rule engine crashed')

    monkeypatch.setattr(payment_engine.fraud_engine, 'evaluate', explode)
    res = send(client, headers, 900)
    assert res.status_code == 500
    with app.app_context():
        assert Transaction.query.count() == 0
        db.session.remove()
    assert balance(app, 'rahul@demo.bank') == Decimal('250000')


def test_balances_and_statuses_stay_consistent(client, app):
    headers = login(client, 'rahul@demo.bank')
    for amount, upi in ((500, 'priya@fsbank'), (10000, 'quickcash@fsbank'), (800, 'amit@fsbank')):
        send(client, headers, amount, upi=upi)
    with app.app_context():
        total = sum(Decimal(a.balance) for a in Account.query.all())
        opening = sum(Decimal(a.opening_balance) for a in Account.query.all())
        assert total == opening  # money is moved, never created or lost
        completed = sum(Decimal(t.amount) for t in Transaction.query.filter_by(status='COMPLETED'))
        rahul = User.query.filter_by(email='rahul@demo.bank').first().primary_account
        assert Decimal(rahul.opening_balance) - Decimal(rahul.balance) == completed == Decimal('1300')
        assert Notification.query.count() > 0
        db.session.remove()
