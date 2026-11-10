import re

from flask import g, request
from flask_jwt_extended import get_jwt

from portal.helpers import payment_engine
from portal.helpers.auth import resolve_location_id
from portal.helpers.responses import ApiError, ok
from portal.helpers.security import USER, client_ip, role_required
from portal.helpers.validators import json_body, parse_amount, require_str
from portal.models import Notification, Transaction
from . import bp


def pending_for(user):
    return (Transaction.query.filter(Transaction.sender_account_id == user.primary_account.id,
                                     Transaction.status == 'UNDER_REVIEW',
                                     Transaction.review_stage == 'AWAITING_CUSTOMER',
                                     Transaction.confirmation_status.in_(('PENDING', 'CONFIRMED')))
            .order_by(Transaction.txn_time.desc()).all())


def confirmation_card(txn):
    """The owner's own payment, with the device/location it came from and why it was flagged."""
    data = txn.to_dict('user')
    sim = txn.simulated_details or {}
    data.update({
        'device_name': (sim.get('device_type') and f"{sim['device_type']} #{sim['device_id']}")
                       or (txn.device.device_name if txn.device else None),
        'ip_address': txn.ip_address,
        'target_location': sim.get('target_location'),
        'demo_otp': demo_otp(txn),
    })
    return data


def demo_otp(txn):
    """The latest OTP for a payment awaiting it, read from the simulated SMS in the
    owner's notifications (no real SMS gateway), so the demo can show it on screen."""
    if txn.confirmation_status != 'CONFIRMED' or txn.status != 'UNDER_REVIEW':
        return None
    sms = (Notification.query.filter_by(transaction_id=txn.id, category='OTP')
           .order_by(Notification.id.desc()).first())
    found = re.search(r'OTP (\d{6})', sms.message) if sms else None
    return found.group(1) if found else None


MESSAGES = {
    'COMPLETED': 'Payment successful.',
    'UNDER_REVIEW': 'Suspicious transaction detected. Did you initiate this transaction?',
    'BLOCKED': 'Payment blocked by fraud detection. No money was debited.',
}


@bp.post('/send')
@role_required(USER)
def send():
    data = json_body()
    amount = parse_amount(data.get('amount'))
    remarks = require_str(data, 'remarks', 140, 'Remarks', required=False)
    key = (request.headers.get('Idempotency-Key') or data.get('idempotency_key') or '').strip()[:64] or None
    location_id = resolve_location_id(data.get('location_id') or get_jwt().get('location_id'), g.current_user)
    txn, replayed = payment_engine.send_money(
        g.current_user, data.get('payment_method'), data, amount, remarks, key,
        device_id=g.device_id, ip=client_ip(), location_id=location_id)
    body = txn.to_dict('user')
    body['replayed'] = replayed
    message = 'Duplicate submission – returning the original payment.' if replayed else MESSAGES.get(txn.status)
    return ok(body, message, 200 if replayed else 201)


@bp.post('/<int:txn_id>/verification/start')
@role_required(USER)
def start_verification(txn_id):
    otp = payment_engine.start_verification(g.current_user, txn_id)
    return ok(otp, f'A new OTP has been sent to {", ".join(otp["sent_to"])}.')


@bp.post('/<int:txn_id>/verification/confirm')
@role_required(USER)
def confirm_verification(txn_id):
    data = json_body()
    otp = require_str(data, 'otp', 6, 'OTP')
    if not (len(otp) == 6 and otp.isdigit()):
        raise ApiError('The OTP is the 6-digit code that was sent to you.', 422, 'VALIDATION_ERROR', {'field': 'otp'})
    result = payment_engine.confirm_verification(g.current_user, txn_id, otp, ip=client_ip())
    return ok(result, result['message'])


@bp.post('/<int:txn_id>/cancel')
@role_required(USER)
def cancel(txn_id):
    txn = payment_engine.cancel_review(g.current_user, txn_id, client_ip())
    return ok(txn.to_dict('user'), 'Payment cancelled.')


@bp.post('/<int:txn_id>/report-fraud')
@role_required(USER)
def report_fraud(txn_id):
    txn = payment_engine.report_not_me(g.current_user, txn_id, client_ip())
    return ok(txn, 'Thank you. The payment was blocked and our fraud team has been alerted.')


# ── "Was this transaction initiated by you?" ────────────────────────────────

@bp.get('/confirmations')
@role_required(USER)
def pending_confirmations():
    payment_engine.expire_confirmations()
    return ok([confirmation_card(t) for t in pending_for(g.current_user)])


@bp.post('/<int:txn_id>/confirmation')
@role_required(USER)
def respond(txn_id):
    """Body: {"response": "YES" | "NO"}. The responder is the logged-in user;
    ownership, expiry and duplicates are all checked on the server."""
    result = payment_engine.respond_to_confirmation(g.current_user, txn_id, json_body().get('response'), client_ip())
    return ok(result, result['message'])
