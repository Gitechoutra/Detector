"""Manual Frauder console. Every endpoint is one deliberate action by the
presenter; nothing here runs on a timer or generates activity on its own."""
from flask import g, request

from portal.helpers import demo, frauder, payment_engine
from portal.helpers.responses import ApiError, ok
from portal.helpers.security import DETECTION, FRAUDER, role_required
from portal.helpers.validators import json_body
from . import bp

OUTCOME_MESSAGES = {
    'UNDER_REVIEW': 'USER CONFIRMATION PENDING: no money moved. The account owner has been asked to confirm '
                    'whether they initiated this transaction.',
    'BLOCKED': 'Blocked: no money moved.',
}


@bp.get('/context')
@role_required(FRAUDER)
def context():
    return ok(frauder.context())


@bp.get('/rule-guide')
@role_required(FRAUDER)
def rule_guide():
    return ok(frauder.rule_guide())


@bp.get('/attempts')
@role_required(FRAUDER)
def attempts():
    return ok(frauder.attempts())


@bp.post('/login-attempt')
@role_required(FRAUDER)
def login_attempt():
    data = json_body()
    result = frauder.login_attempt(g.current_user, data)
    return ok(result, result['message'])


@bp.post('/otp-attempt')
@role_required(FRAUDER)
def otp_attempt():
    result = frauder.otp_attempt(g.current_user, json_body())
    return ok(result, result['message'])


@bp.post('/transfer')
@role_required(FRAUDER)
def transfer():
    key = (request.headers.get('Idempotency-Key') or '').strip()[:64] or None
    result, replayed = frauder.transfer(g.current_user, json_body(), key)
    result['replayed'] = replayed
    message = 'Duplicate submission – showing the original result.' if replayed else OUTCOME_MESSAGES.get(result['status'])
    return ok(result, message, 200 if replayed else 201)


@bp.get('/transactions/<int:txn_id>')
@role_required(FRAUDER)
def transaction(txn_id):
    from portal.extensions import db
    from portal.models import Transaction
    txn = db.session.get(Transaction, txn_id)
    if txn is None or txn.scenario_code != frauder.SCENARIO_CODE:
        raise ApiError('Attempt not found.', 404, 'NOT_FOUND')
    payment_engine.expire_confirmations()
    return ok(frauder.detection_result(txn))


@bp.post('/reset')
@role_required(FRAUDER, DETECTION)
def reset():
    if json_body().get('confirm') != 'RESET':
        raise ApiError('Send {"confirm": "RESET"} to reset the fraud attempts.', 422, 'CONFIRMATION_REQUIRED')
    counts = demo.reset_simulation(actor=g.current_user)
    return ok({'cleared': counts}, 'Fraud attempts reset. Money moved by Frauder transfers was reversed; '
                                   'genuine payments are untouched.')
