"""Payment pipeline: ingest → persist → evaluate → score → decide → alert.

Persist, evaluate, score, decide and the balance movement all happen inside one
DB transaction that is committed once.

No rule triggered  → the normal flow: the payment completes at once
                     (except Frauder attempts: never made by the owner, always held).
Any rule triggered → the payment is held (USER_CONFIRMATION_PENDING) and its owner
is asked "Did you initiate this transaction?". Nothing is debited until then.
  YES → the payment is re-validated (accounts, balance, absolute restrictions)
        and, if it can be processed, completed (SUCCESSFUL).
  NO  → BLOCKED at once; no money moves.
  No answer in time → EXPIRED; never authorized.
The risk score and triggered rules are recorded either way, for investigation."""
import ipaddress
import secrets
import time
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

from sqlalchemy import bindparam, text
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from portal.extensions import db
from portal.models import (Account, Alert, Device, Notification, Transaction, VerificationChallenge,
                           WatchlistEntry, now)
from portal.helpers.audit import write_audit
from portal.helpers.responses import ApiError
from portal.helpers import fraud_engine
from portal.helpers.helpers import inr, notify, raise_alert, security_event, setting

METHODS = ('UPI', 'QR', 'BANK_TRANSFER')


# ── Receiver resolution ─────────────────────────────────────────────────────

def parse_qr_payload(payload):
    """Accepts upi://pay?pa=<upi>&pn=<name>&tr=<token> (what the receiver's QR encodes)."""
    try:
        parsed = urlparse(payload.strip())
        params = parse_qs(parsed.query)
    except (AttributeError, ValueError):
        params = {}
    if parsed.scheme != 'upi' or 'pa' not in params:
        raise ApiError('This QR code is not a valid payment QR.', 422, 'INVALID_QR')
    return params['pa'][0], (params.get('tr') or [None])[0]


def resolve_receiver(method, data):
    if method == 'UPI':
        upi = (data.get('upi_id') or '').strip().lower()
        if not upi:
            raise ApiError('Enter the receiver UPI ID.', 422, 'VALIDATION_ERROR', {'field': 'upi_id'})
        account = Account.query.filter_by(upi_id=upi).first()
    elif method == 'QR':
        upi, token = parse_qr_payload(data.get('qr_payload') or '')
        account = Account.query.filter_by(upi_id=upi.lower()).first()
        if account and token and token != account.qr_token:
            raise ApiError('This QR code has been replaced or is not genuine.', 422, 'INVALID_QR')
    elif method == 'BANK_TRANSFER':
        number = (data.get('account_number') or '').strip()
        ifsc = (data.get('ifsc') or '').strip().upper()
        if not number or not ifsc:
            raise ApiError('Enter the account number and IFSC.', 422, 'VALIDATION_ERROR')
        account = Account.query.filter_by(account_number=number).first()
        if account and account.ifsc != ifsc:
            raise ApiError('IFSC does not match this account number.', 422, 'VALIDATION_ERROR',
                           {'field': 'ifsc'})
    else:
        raise ApiError('Choose UPI, QR Code or Bank Transfer.', 422, 'VALIDATION_ERROR',
                       {'field': 'payment_method'})
    if account is None:
        raise ApiError('No account found with these receiver details.', 404, 'RECEIVER_NOT_FOUND')
    if account.status != 'ACTIVE':
        raise ApiError('The receiver account cannot accept payments right now.', 409, 'RECEIVER_INACTIVE')
    return account


# ── Locking & settlement ────────────────────────────────────────────────────

def _lock_accounts(*account_ids):
    """Row-locks accounts in id order (consistent order prevents deadlocks)."""
    ids = sorted(set(account_ids))
    db.session.execute(text('SELECT id FROM accounts WHERE id IN :ids ORDER BY id FOR UPDATE')
                       .bindparams(bindparam('ids', expanding=True)), {'ids': ids})
    return {a.id: a for a in Account.query.filter(Account.id.in_(ids)).populate_existing().all()}


# Plain-language reason per rule, used to explain REVIEW and BLOCKED decisions.
RULE_PHRASES = {
    'R1': "the amount is far above this customer's usual payments",
    'R2': 'too many payments were made from the account within a few minutes',
    'R3': 'the payment came from a city too far from the previous one to travel in time',
    'R4': 'a high-value transfer was initiated from an unrecognized device',
    'R5': 'a high-value payment was made at an unusual hour',
    'R6': 'a party to the payment is on the fraud watchlist',
    'R7': 'repeated payments just below the reporting threshold suggest structuring',
    'R8': 'a long-dormant account suddenly made a large payment',
    'R9': 'it followed suspicious login activity on the account',
}


def _phrases(codes):
    phrases = [RULE_PHRASES[c] for c in codes if c in RULE_PHRASES]
    return phrases[0] if len(phrases) == 1 else ', '.join(phrases[:-1]) + ' and ' + phrases[-1]


def explain(result, held=False):
    """e.g. "Held for the account owner's authorization because a high-value transfer
    was initiated from an unrecognized device. Risk score 20 (approve band)." """
    if not result['hits'] or (result['decision'] == 'APPROVED' and not held):
        return None
    reason = _phrases([h['code'] for h in result['hits']])
    if held:
        text = (f"Held for the account owner's authorization because {reason}. Risk score {result['score']} "
                f"({result['decision'].lower()} band). No money moves until the owner answers YES.")
    elif result['decision'] == 'BLOCKED':
        text = (f'Transaction blocked because {reason}. The risk score of {result["score"]} exceeded the '
                f'blocking threshold of {fraud_engine.band_floor("BLOCKED")}.')
    else:
        text = (f'Transaction held for review because {reason}. The risk score of {result["score"]} reached the '
                f'review threshold of {fraud_engine.band_floor("REVIEW")}; no money moves until it is verified.')
    return text[:500]


def _settle(txn, at=None, reason=None):
    """Moves the money exactly once. Caller holds the DB transaction."""
    at = at or now()
    # Lock the payment row first: whoever holds it decides whether money moves,
    # so a duplicate release can never debit twice.
    db.session.flush()
    db.session.execute(text('SELECT id FROM transactions WHERE id = :id FOR UPDATE'), {'id': txn.id})
    db.session.refresh(txn, ['status'])
    if txn.status == 'COMPLETED':
        return False
    accounts = _lock_accounts(txn.sender_account_id, txn.receiver_account_id)
    sender, receiver = accounts[txn.sender_account_id], accounts[txn.receiver_account_id]
    if sender.balance < txn.amount:
        _decline(txn, 'Insufficient balance at the time of release.')
        return False
    sender.balance -= txn.amount
    receiver.balance += txn.amount
    for account in (sender, receiver):
        if account.last_txn_at is None or account.last_txn_at < txn.txn_time:
            account.last_txn_at = txn.txn_time
    txn.status, txn.review_stage, txn.completed_at = 'COMPLETED', None, at
    txn.final_reason = reason or 'Successful – none of the nine fraud rules was triggered.'
    notify(sender.user_id, 'Payment successful',
           f'{inr(txn.amount)} sent to {receiver.user.full_name} ({txn.txn_ref}).', 'SUCCESS', txn.id,
           txn.is_simulated)
    notify(receiver.user_id, 'Money received',
           f'{inr(txn.amount)} credited from {sender.user.full_name} ({txn.txn_ref}).', 'SUCCESS', txn.id,
           txn.is_simulated)
    return True


def _decline(txn, reason, status='DECLINED'):
    txn.status, txn.review_stage, txn.decline_reason = status, None, reason[:500]
    txn.final_reason = reason[:500]
    notify(txn.sender_account.user_id, 'Payment declined',
           f'{inr(txn.amount)} to {txn.receiver_account.user.full_name} was declined: {reason}', 'DANGER', txn.id,
           txn.is_simulated)


def _block(txn, result, explanation=None):
    # The receiver is not told: incoming payments appear for them only once approved.
    txn.status, txn.review_stage = 'BLOCKED', None
    txn.risk_explanation = explanation or explain(result)
    txn.decline_reason = txn.final_reason = txn.risk_explanation
    notify(txn.sender_account.user_id, 'Payment blocked for your security',
           f'{inr(txn.amount)} to {txn.receiver_account.user.full_name}: {txn.risk_explanation} '
           f'No money has left your account.', 'DANGER', txn.id, txn.is_simulated)


def _resolve_open_alerts(txn, resolution, actor=None, note=None):
    for alert in Alert.query.filter(Alert.transaction_id == txn.id, Alert.status != 'RESOLVED').all():
        alert.status, alert.resolution, alert.resolved_at = 'RESOLVED', resolution, now()
        if actor:
            alert.assigned_to = alert.assigned_to or actor.id
        if note:
            alert.analyst_notes = ((alert.analyst_notes + '\n') if alert.analyst_notes else '') + note


def _auto_watchlist(txn, result):
    """After an account-takeover block, stop the attacker's untrusted device and
    public IP from being reused. Customer-owned trusted devices are never listed."""
    if 'R9' not in {h['code'] for h in result['hits']}:
        return
    entries = []
    device = db.session.get(Device, txn.device_id) if txn.device_id else None
    if device and not device.is_trusted:
        entries.append(('DEVICE', device.fingerprint))
    try:
        if txn.ip_address and ipaddress.ip_address(txn.ip_address).is_global:
            entries.append(('IP', txn.ip_address))
    except ValueError:
        pass
    for entity_type, value in entries:
        if not WatchlistEntry.query.filter_by(entity_type=entity_type, entity_value=value).first():
            db.session.add(WatchlistEntry(entity_type=entity_type, entity_value=value, source='AUTO',
                                          reason=f'Auto-added after account-takeover block of {txn.txn_ref}'))


def _apply_decision(txn, result, owner_must_confirm=False):
    sender_user = txn.sender_account.user
    receiver_user = txn.receiver_account.user
    codes = [h['code'] for h in result['hits']]
    rules = ', '.join(f"{h['code']} {h['name']}" for h in result['hits']) or 'none'
    if not codes and not owner_must_confirm:
        _settle(txn)        # no rule triggered: the normal payment flow
        return
    hard = sorted(hard_block_rules() & set(codes))
    if hard:
        # An absolute restriction (configured, none by default): blocked, no question asked.
        _block(txn, result, (f'Transaction blocked because {_phrases(hard)}. {", ".join(hard)} is configured as an '
                             f'absolute security restriction. Risk score {result["score"]}.')[:500])
        raise_alert('TRANSACTION_BLOCKED', 'HIGH',
                    f'Blocked: {inr(txn.amount)} {sender_user.full_name} → {receiver_user.full_name}',
                    f'Risk score {result["score"]}. Rules fired: {rules}. {txn.risk_explanation}',
                    user_id=sender_user.id, transaction_id=txn.id, risk_score=result['score'],
                    simulated=txn.is_simulated)
        _auto_watchlist(txn, result)
        return

    # Any triggered rule, whatever the score: hold it and ask the owner.
    txn.status = 'UNDER_REVIEW'
    txn.risk_explanation = explain(result, held=True) or (
        "Held for the account owner's authorization: no fraud rule was triggered (risk score 0), but the payment "
        "was not made from the owner's own banking session. No money moves until the owner answers YES.")
    # Accounts that cannot log in (legacy sim.* accounts) go straight to an analyst.
    txn.review_stage = 'AWAITING_ANALYST' if sender_user.is_simulated else 'AWAITING_CUSTOMER'
    if txn.review_stage == 'AWAITING_CUSTOMER':
        _open_confirmation(txn)
        notify(sender_user.id, SECURITY_TITLE,
               f'A transaction is being attempted from your account. Please confirm whether you initiated this '
               f'transaction. {inr(txn.amount)} to {receiver_user.full_name} ({txn.txn_ref}) – rules {", ".join(codes) or "none"}, '
               f'risk score {result["score"]}. Nothing has been debited.',
               'WARNING', txn.id, txn.is_simulated)
    raise_alert('TRANSACTION_REVIEW', 'HIGH' if result['decision'] == 'BLOCKED' else 'MEDIUM',
                f'Awaiting owner: {inr(txn.amount)} {sender_user.full_name} → {receiver_user.full_name}',
                f'Risk score {result["score"]} ({result["decision"]} band). Rules fired: {rules}. '
                f'{txn.risk_explanation}',
                user_id=sender_user.id, transaction_id=txn.id, risk_score=result['score'],
                simulated=txn.is_simulated)


def _to_millis(at):
    """txn_time is DATETIME(3) and MySQL rounds extra digits on insert. Truncate
    first so the stored value equals the in-memory one the rules anchor on."""
    return at.replace(microsecond=at.microsecond // 1000 * 1000)


def _new_ref():
    return 'TXN' + now().strftime('%y%m%d%H%M%S') + secrets.token_hex(3).upper()[:5]


def send_money(sender_user, method, receiver_data, amount, remarks=None, idempotency_key=None,
               device_id=None, ip=None, location_id=None, *, simulated=False, run_id=None,
               scenario_code=None, fraud_label=None, txn_time=None, simulated_details=None,
               owner_must_confirm=False):
    """Returns (transaction, replayed). Raises ApiError for invalid requests;
    a valid request always ends in a committed transaction with a decision."""
    started = time.perf_counter()
    if method not in METHODS:
        raise ApiError('Choose UPI, QR Code or Bank Transfer.', 422, 'VALIDATION_ERROR')
    sender = sender_user.primary_account
    if sender is None:
        raise ApiError('You do not have an account to pay from.', 409, 'NO_ACCOUNT')

    if idempotency_key:
        existing = Transaction.query.filter_by(sender_account_id=sender.id,
                                               idempotency_key=idempotency_key).first()
        if existing:
            return existing, True

    if sender_user.status != 'ACTIVE':
        raise ApiError('Your account is locked. Payments are disabled.', 423, 'ACCOUNT_LOCKED')
    if sender.status != 'ACTIVE':
        raise ApiError('Your account is frozen. Contact the bank.', 409, 'ACCOUNT_FROZEN')
    receiver = resolve_receiver(method, receiver_data)
    if receiver.id == sender.id:
        raise ApiError('You cannot send money to your own account.', 422, 'SAME_ACCOUNT')
    if amount > setting('MAX_TXN_AMOUNT'):
        raise ApiError(f"Maximum amount per transaction is {inr(setting('MAX_TXN_AMOUNT'))}.", 422,
                       'VALIDATION_ERROR')

    try:
        locked = _lock_accounts(sender.id, receiver.id)
        if locked[sender.id].balance < amount:
            db.session.rollback()
            raise ApiError(f'Insufficient balance. Available: {inr(locked[sender.id].balance)}.', 422,
                           'INSUFFICIENT_BALANCE')

        txn = Transaction(
            txn_ref=_new_ref(), idempotency_key=idempotency_key, sender_account_id=sender.id,
            receiver_account_id=receiver.id, amount=amount, payment_method=method,
            remarks=(remarks or None), status='PROCESSING', device_id=device_id, ip_address=ip,
            location_id=location_id, is_simulated=simulated, simulation_run_id=run_id,
            scenario_code=scenario_code, is_fraud_label=fraud_label, txn_time=_to_millis(txn_time or now()),
            simulated_details=simulated_details)
        db.session.add(txn)
        db.session.flush()

        result = fraud_engine.evaluate(txn)
        _apply_decision(txn, result, owner_must_confirm)
        txn.decided_at = now()
        txn.latency_ms = round((time.perf_counter() - started) * 1000, 2)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existing = Transaction.query.filter_by(sender_account_id=sender.id,
                                               idempotency_key=idempotency_key).first()
        if idempotency_key and existing:
            return existing, True
        raise
    except ApiError:
        raise
    except Exception:
        db.session.rollback()
        raise
    return txn, False


# ── Customer step-up verification for REVIEW payments ───────────────────────

def _own_review_txn(user, txn_id):
    txn = db.session.get(Transaction, txn_id)
    if txn is None or txn.sender_account.user_id != user.id:
        raise ApiError('Payment not found.', 404, 'NOT_FOUND')
    if txn.status != 'UNDER_REVIEW':
        raise ApiError(f'This payment is {txn.status.replace("_", " ").lower()} and cannot be verified.',
                       409, 'NOT_UNDER_REVIEW')
    if txn.review_stage != 'AWAITING_CUSTOMER':
        raise ApiError('You have already verified this payment. It is now with our fraud team.',
                       409, 'AWAITING_ANALYST')
    if txn.confirmation_expires_at and txn.confirmation_expires_at < now():
        _expire(txn)
        db.session.commit()
        raise ApiError(f'Too late: {txn.final_reason}', 410, 'CONFIRMATION_EXPIRED')
    return txn


def start_verification(user, txn_id):
    """OTP step-up, kept only for payments confirmed under the earlier OTP flow."""
    txn = _own_review_txn(user, txn_id)
    if txn.confirmation_status == 'PENDING':
        raise ApiError('Answer the security verification instead: YES, I initiated it, or NO.', 409,
                       'USE_CONFIRMATION')
    for old in VerificationChallenge.query.filter_by(transaction_id=txn.id, status='PENDING').all():
        old.status = 'EXPIRED'
    otp = f'{secrets.randbelow(1_000_000):06d}'
    minutes = setting('OTP_EXPIRY_MINUTES')
    challenge = VerificationChallenge(transaction_id=txn.id, user_id=user.id,
                                      otp_hash=generate_password_hash(otp),
                                      max_attempts=setting('OTP_MAX_ATTEMPTS'),
                                      expires_at=now() + timedelta(minutes=minutes))
    db.session.add(challenge)
    sms = (f'FraudShield Bank: OTP {otp} to verify payment of {inr(txn.amount)} to '
           f'{txn.receiver_account.user.full_name}. Valid {minutes} min. Never share this OTP.')
    notify(user.id, 'Simulated SMS – verification OTP', sms, 'OTP', txn.id, txn.is_simulated)
    db.session.commit()
    return {'challenge_id': challenge.id, 'expires_at': challenge.expires_at.isoformat(timespec='seconds'),
            'max_attempts': challenge.max_attempts, 'simulated_sms': sms}


def confirm_verification(user, txn_id, otp, password, ip=None):
    txn = _own_review_txn(user, txn_id)
    challenge = (VerificationChallenge.query.filter_by(transaction_id=txn.id, status='PENDING')
                 .order_by(VerificationChallenge.id.desc()).first())
    if challenge is None:
        raise ApiError('Request a new OTP first.', 409, 'NO_CHALLENGE')
    if challenge.expires_at < now():
        challenge.status = 'EXPIRED'
        db.session.commit()
        raise ApiError('This OTP has expired. Request a new one.', 410, 'OTP_EXPIRED')

    otp_ok = bool(otp) and check_password_hash(challenge.otp_hash, otp)
    password_ok = bool(password) and check_password_hash(user.password_hash, password)
    if not (otp_ok and password_ok):
        challenge.attempts += 1
        what = 'OTP' if not otp_ok else 'password'
        security_event(user.id, 'OTP_FAILED', f'Wrong {what} while verifying {txn.txn_ref}', 'MEDIUM',
                       device_id=txn.device_id, ip=ip, transaction_id=txn.id)
        if challenge.attempts >= challenge.max_attempts:
            challenge.status = 'FAILED'
            _decline(txn, 'Verification failed too many times.')
            _resolve_open_alerts(txn, 'CONFIRMED_FRAUD', note='Auto: customer step-up verification failed.')
            raise_alert('SECURITY', 'HIGH', f'Step-up failed: {user.full_name}',
                        f'{challenge.attempts} wrong OTP/password entries for {txn.txn_ref}. Payment declined.',
                        user_id=user.id, transaction_id=txn.id, risk_score=txn.risk_score)
            write_audit('STEP_UP_FAILED', 'transaction', txn.id, {'attempts': challenge.attempts},
                        actor=user, ip=ip)
            db.session.commit()
            raise ApiError('Verification failed too many times. The payment has been declined.', 403,
                           'VERIFICATION_FAILED')
        db.session.commit()
        left = challenge.max_attempts - challenge.attempts
        raise ApiError(f'Incorrect {what}. {left} attempt(s) left.', 422, 'VERIFICATION_INCORRECT')

    # Verified: re-run every rule. Only identity rules (R4, R9) are mitigated,
    # and they are recorded as such; any behavioural rule still counts in full.
    challenge.status, challenge.verified_at = 'VERIFIED', now()
    txn.step_up_verified = True
    security_event(user.id, 'STEP_UP_VERIFIED', f'Customer verified {txn.txn_ref} with OTP + password',
                   'LOW', device_id=txn.device_id, ip=ip, transaction_id=txn.id)
    db.session.flush()

    result = fraud_engine.evaluate(txn, 'RE_EVALUATION', step_up_verified=True,
                                   notes='Re-evaluated after customer step-up verification')
    hard = sorted(hard_block_rules() & {h['code'] for h in result['hits']})
    if result['decision'] != 'BLOCKED' and not hard and txn.device_id:
        # The customer proved ownership on this device, so future payments from it are trusted.
        db.session.get(Device, txn.device_id).is_trusted = True
    if hard and result['decision'] != 'BLOCKED':
        phrases = ' and '.join(RULE_PHRASES[c] for c in hard if c in RULE_PHRASES)
        _block(txn, result, (f'Transaction blocked because {phrases}. This is a hard-block condition '
                             f'({", ".join(hard)}), so the account owner\'s confirmation cannot override it. '
                             f'Risk score after re-evaluation: {result["score"]}.')[:500])
        outcome = 'blocked'
    elif result['decision'] == 'APPROVED':
        released = _settle(txn, reason=(
            f'Approved after the account owner confirmed the payment (YES + OTP + password) and the '
            f're-evaluation scored {result["score"]}, below the review threshold of '
            f'{fraud_engine.band_floor("REVIEW")}.'))
        if released:
            _resolve_open_alerts(txn, 'FALSE_POSITIVE', note='Auto: customer verified; re-evaluation approved.')
        outcome = 'released' if released else 'declined'
    elif result['decision'] == 'REVIEW':
        txn.review_stage = 'AWAITING_ANALYST'
        txn.risk_explanation = explain(result)
        txn.final_reason = (f'The account owner confirmed the payment, but it still scores {result["score"]} after '
                            f're-evaluation, so a fraud analyst must decide. Nothing has been debited.')
        notify(user.id, 'Verified – pending fraud team review',
               f'Thank you. {inr(txn.amount)} still scores {result["score"]} after verification, so a fraud '
               f'analyst will review it. It has not been debited.', 'WARNING', txn.id, txn.is_simulated)
        outcome = 'escalated'
    else:
        _block(txn, result)
        outcome = 'blocked'
    write_audit('STEP_UP_VERIFIED', 'transaction', txn.id,
                {'new_score': result['score'], 'decision': result['decision'], 'outcome': outcome},
                actor=user, ip=ip)
    db.session.commit()
    return {'outcome': outcome, 'risk_score': result['score'], 'decision': result['decision'],
            'mitigations': result['mitigations'], 'hits': result['hits'], 'transaction': txn.to_dict('user')}


def cancel_review(user, txn_id, ip=None):
    txn = db.session.get(Transaction, txn_id)
    if txn is None or txn.sender_account.user_id != user.id:
        raise ApiError('Payment not found.', 404, 'NOT_FOUND')
    if txn.status != 'UNDER_REVIEW':
        raise ApiError('Only payments on hold can be cancelled.', 409, 'NOT_UNDER_REVIEW')
    if txn.confirmation_status == 'PENDING':
        raise ApiError('Answer the security verification instead: YES authorizes it, NO blocks it.', 409,
                       'USE_CONFIRMATION')
    txn.status, txn.review_stage, txn.decline_reason = 'CANCELLED', None, 'Cancelled by customer.'
    txn.final_reason = 'Cancelled by the account owner.'
    if txn.confirmation_status == 'PENDING':
        txn.confirmation_status = 'CLOSED'
    _resolve_open_alerts(txn, 'FALSE_POSITIVE', note='Customer cancelled the held payment.')
    write_audit('PAYMENT_CANCELLED', 'transaction', txn.id, {}, actor=user, ip=ip)
    db.session.commit()
    return txn


def report_not_me(user, txn_id, ip=None):
    """Older "No, not me" endpoint: the same as answering NO."""
    return respond_to_confirmation(user, txn_id, 'NO', ip)['transaction']


# ── Account-owner confirmation: "Was this transaction initiated by you?" ─────

SECURITY_TITLE = 'Security Verification Required'
DENIED_REASON = 'Account owner denied initiating this transaction.'


def hard_block_rules():
    """Rules treated as an absolute restriction (setting, empty by default):
    such a payment is blocked outright and a YES cannot authorize it."""
    raw = setting('CONFIRMATION_HARD_BLOCK_RULES', str) or ''
    return {code.strip().upper() for code in raw.split(',') if code.strip()}


def _open_confirmation(txn):
    txn.confirmation_status = 'PENDING'
    txn.confirmation_expires_at = now() + timedelta(minutes=setting('CONFIRMATION_EXPIRY_MINUTES'))


def _lock_txn(txn_id):
    """Row-locks the payment and reloads it, so concurrent answers queue up and
    only the first one finds the request still PENDING."""
    db.session.execute(text('SELECT id FROM transactions WHERE id = :id FOR UPDATE'), {'id': txn_id})
    return db.session.get(Transaction, txn_id, populate_existing=True)


def _close_security_notice(txn):
    """The request leaves the notification centre once answered or expired."""
    Notification.query.filter_by(transaction_id=txn.id, title=SECURITY_TITLE, is_read=False).update(
        {'is_read': True}, synchronize_session=False)


def _expire(txn):
    """No answer in time. Never authorized: EXPIRED (default), BLOCKED, or handed to the fraud team (HOLD)."""
    minutes = setting('CONFIRMATION_EXPIRY_MINUTES')
    owner = txn.sender_account.user
    txn.confirmation_status = 'EXPIRED'
    _close_security_notice(txn)
    for challenge in VerificationChallenge.query.filter_by(transaction_id=txn.id, status='PENDING').all():
        challenge.status = 'EXPIRED'
    action = (setting('CONFIRMATION_EXPIRY_ACTION', str) or 'EXPIRE').strip().upper()
    if action == 'HOLD':
        txn.review_stage = 'AWAITING_ANALYST'
        txn.final_reason = (f'The account owner did not confirm this payment within {minutes} minutes, so it was '
                            f'passed to the fraud team. Nothing has been debited.')
        notify(owner.id, 'Unconfirmed payment passed to our fraud team',
               f'{inr(txn.amount)} to {txn.receiver_account.user.full_name} ({txn.txn_ref}): {txn.final_reason}',
               'WARNING', txn.id, txn.is_simulated)
    else:
        status = 'BLOCKED' if action == 'BLOCK' else 'EXPIRED'
        reason = (f'{"Blocked" if status == "BLOCKED" else "Expired"}: the account owner did not respond within '
                  f'{minutes} minutes, so the transaction was not authorized. No money has been transferred.')
        txn.status, txn.review_stage, txn.decline_reason, txn.final_reason = status, None, reason, reason
        notify(owner.id, 'Unanswered payment not authorized',
               f'{inr(txn.amount)} to {txn.receiver_account.user.full_name} ({txn.txn_ref}): {reason}',
               'DANGER', txn.id, txn.is_simulated)
        action = status
    write_audit('CONFIRMATION_EXPIRED', 'transaction', txn.id, {'minutes': minutes, 'action': action})


def expire_confirmations():
    """Applies the expiry policy to overdue requests. Called whenever
    confirmations are listed or answered – there is no background thread."""
    overdue = [row.id for row in db.session.query(Transaction.id).filter(
        Transaction.status == 'UNDER_REVIEW', Transaction.review_stage == 'AWAITING_CUSTOMER',
        Transaction.confirmation_expires_at < now()).all()]
    for txn_id in overdue:
        txn = _lock_txn(txn_id)
        if (txn.status == 'UNDER_REVIEW' and txn.review_stage == 'AWAITING_CUSTOMER'
                and txn.confirmation_expires_at < now()):
            _expire(txn)
    if overdue:
        db.session.commit()
    return len(overdue)


def respond_to_confirmation(user, txn_id, response, ip=None):
    """The owner's YES/NO. Who is answering comes from the login session, never
    from the request body, and the row lock makes each answer count once."""
    response = (response or '').strip().upper()
    if response not in ('YES', 'NO'):
        raise ApiError('Answer YES or NO.', 422, 'VALIDATION_ERROR', {'field': 'response'})
    txn = _lock_txn(txn_id)
    if txn is None or txn.sender_account.user_id != user.id:
        raise ApiError('Payment not found.', 404, 'NOT_FOUND')
    if txn.confirmation_status is None:
        raise ApiError('This payment has no security confirmation to answer.', 409, 'NO_CONFIRMATION')
    if txn.confirmation_status == 'EXPIRED':
        raise ApiError(f'This confirmation has expired. {txn.final_reason or ""}'.strip(), 410,
                       'CONFIRMATION_EXPIRED')
    if txn.confirmation_status != 'PENDING' or txn.status != 'UNDER_REVIEW':
        answered = f'You already answered {txn.confirmation_response}. ' if txn.confirmation_response else ''
        raise ApiError(f'{answered}This payment is {txn.outcome_label().lower()} and can no longer be answered.',
                       409, 'ALREADY_RESPONDED')
    if txn.confirmation_expires_at < now():
        _expire(txn)
        db.session.commit()
        raise ApiError(f'Too late: {txn.final_reason}', 410, 'CONFIRMATION_EXPIRED')

    txn.confirmation_response, txn.confirmation_responded_at = response, now()
    _close_security_notice(txn)
    if response == 'NO':
        return _deny(user, txn, ip)

    txn.confirmation_status = 'CONFIRMED'
    security_event(user.id, 'PAYMENT_CONFIRMED', f'Owner answered YES: authorized {txn.txn_ref}',
                   'LOW', device_id=txn.device_id, ip=ip, transaction_id=txn.id, simulated=txn.is_simulated)
    write_audit('CONFIRMATION_YES', 'transaction', txn.id, {'risk_score': txn.risk_score}, actor=user, ip=ip)
    return _authorize(user, txn, ip)


def _restriction(txn, sender, receiver):
    """Why an authorized payment still cannot be processed, or None."""
    if sender.user.status != 'ACTIVE' or sender.status != 'ACTIVE':
        return 'the sender account is locked or frozen'
    if receiver.status != 'ACTIVE' or receiver.user.status != 'ACTIVE':
        return 'the receiver account can no longer accept payments'
    if sender.balance < txn.amount:
        return f'the available balance ({inr(sender.balance)}) is lower than the amount ({inr(txn.amount)})'
    hard = sorted(hard_block_rules() & {h.rule_code for h in txn.latest_hits()})
    if hard:
        return f'{_phrases(hard)}, which is an absolute security restriction ({", ".join(hard)})'
    return None


def _authorize(user, txn, ip):
    """YES is the owner's authorization, not a bypass: the payment is re-validated
    under row locks first, then completed exactly once. The recorded risk score and
    triggered rules are kept as they were for investigation."""
    accounts = _lock_accounts(txn.sender_account_id, txn.receiver_account_id)
    problem = _restriction(txn, accounts[txn.sender_account_id], accounts[txn.receiver_account_id])
    rules = ', '.join(h.rule_code for h in txn.latest_hits())
    if problem:
        reason = (f'You authorized this payment, but it was blocked because {problem}. '
                  f'No money has been transferred.')[:500]
        txn.status, txn.review_stage, txn.decline_reason, txn.final_reason = 'BLOCKED', None, reason, reason
        raise_alert('TRANSACTION_BLOCKED', 'HIGH', f'Authorized but blocked: {txn.txn_ref}', reason,
                    user_id=user.id, transaction_id=txn.id, risk_score=txn.risk_score, simulated=txn.is_simulated)
        notify(user.id, 'Payment could not be processed', f'{inr(txn.amount)} ({txn.txn_ref}): {reason}',
               'DANGER', txn.id, txn.is_simulated)
        outcome = 'blocked'
        message = reason
    else:
        _settle(txn, reason=(f'Transaction successfully authorized by the account owner (YES). Triggered rules '
                             f'{rules}, risk score {txn.risk_score} – kept for investigation.'))
        _resolve_open_alerts(txn, 'FALSE_POSITIVE', note='Account owner authorized the payment (YES).')
        outcome = 'authorized'
        message = 'Transaction successfully authorized. The amount has been transferred to the Receiver.'
    write_audit('PAYMENT_AUTHORIZED' if outcome == 'authorized' else 'AUTHORIZED_BUT_BLOCKED', 'transaction',
                txn.id, {'risk_score': txn.risk_score, 'rules': rules}, actor=user, ip=ip)
    db.session.commit()
    return {'response': 'YES', 'outcome': outcome, 'message': message, 'transaction': txn.to_dict('user')}


def _deny(user, txn, ip):
    txn.confirmation_status = 'DENIED'
    txn.status, txn.review_stage, txn.decline_reason, txn.final_reason = (
        'BLOCKED', None, DENIED_REASON, DENIED_REASON)
    for challenge in VerificationChallenge.query.filter_by(transaction_id=txn.id, status='PENDING').all():
        challenge.status = 'EXPIRED'
    _resolve_open_alerts(txn, 'CONFIRMED_FRAUD', note='Account owner answered NO: "I did not initiate this payment."')
    # Block the attacker: their untrusted device and public IP go on the watchlist (R6 from now on).
    entries = []
    device = db.session.get(Device, txn.device_id) if txn.device_id else None
    if device and not device.is_trusted:
        entries.append(('DEVICE', device.fingerprint))
    try:
        if txn.ip_address and ipaddress.ip_address(txn.ip_address).is_global:
            entries.append(('IP', txn.ip_address))
    except ValueError:
        pass
    for entity_type, value in entries:
        if not WatchlistEntry.query.filter_by(entity_type=entity_type, entity_value=value).first():
            db.session.add(WatchlistEntry(entity_type=entity_type, entity_value=value, source='AUTO',
                                          reason=f'Account owner denied {txn.txn_ref}'))
    receiver = txn.receiver_account.user.full_name
    rules = ', '.join(h.rule_code for h in txn.latest_hits()) or 'none'
    security_event(user.id, 'FRAUD_REPORTED', f'Owner answered NO: did not initiate {txn.txn_ref}', 'HIGH',
                   device_id=txn.device_id, ip=ip, transaction_id=txn.id, simulated=txn.is_simulated)
    raise_alert('USER_DENIED', 'HIGH', f'User denied payment: {user.full_name}',
                f'{user.full_name} answered NO – they did not initiate {txn.txn_ref} ({inr(txn.amount)} to '
                f'{receiver}; rules {rules}, risk score {txn.risk_score}). Blocked, no money moved. '
                f'Possible account takeover: review the device and logins.',
                user_id=user.id, transaction_id=txn.id, risk_score=txn.risk_score, simulated=txn.is_simulated)
    notify(user.id, 'Payment blocked – you said it was not you',
           f'{inr(txn.amount)} to {receiver} ({txn.txn_ref}) was blocked. No money left your account. '
           f'If someone knows your password, change it now.', 'DANGER', txn.id, txn.is_simulated)
    write_audit('CONFIRMATION_NO', 'transaction', txn.id, {}, actor=user, ip=ip)
    db.session.commit()
    return {'response': 'NO', 'outcome': 'blocked',
            'message': ('Transaction blocked successfully. You reported that this transaction was not initiated '
                        'by you. No money has been transferred.'),
            'transaction': txn.to_dict('user')}


# ── Analyst decision for REVIEW payments ────────────────────────────────────

def analyst_decision(analyst, txn_id, action, notes=None, ip=None):
    txn = db.session.get(Transaction, txn_id)
    if txn is None:
        raise ApiError('Transaction not found.', 404, 'NOT_FOUND')
    if txn.status != 'UNDER_REVIEW':
        raise ApiError('Only transactions under review can be decided.', 409, 'NOT_UNDER_REVIEW')
    if txn.confirmation_status == 'PENDING':
        raise ApiError("This payment is waiting for the account owner's YES/NO. Only the owner can decide it.",
                       409, 'AWAITING_OWNER')
    note = f'{analyst.full_name}: {notes}' if notes else None

    if action == 'REJECT':
        _decline(txn, 'Rejected by the fraud team after review.')
        _resolve_open_alerts(txn, 'CONFIRMED_FRAUD', analyst, note)
        write_audit('REVIEW_REJECTED', 'transaction', txn.id, {'notes': notes}, actor=analyst, ip=ip)
        db.session.commit()
        return {'outcome': 'rejected', 'transaction': txn.to_dict()}

    if action != 'APPROVE':
        raise ApiError('Action must be APPROVE or REJECT.', 422, 'VALIDATION_ERROR')
    # An analyst can release a REVIEW payment, but never one that now scores BLOCKED.
    result = fraud_engine.evaluate(txn, 'ANALYST', step_up_verified=txn.step_up_verified,
                                   assessed_by=analyst, notes='Re-evaluated before analyst approval')
    if result['decision'] == 'BLOCKED':
        _block(txn, result)
        _resolve_open_alerts(txn, 'CONFIRMED_FRAUD', analyst, 'Auto: re-evaluation scored BLOCKED.')
        write_audit('REVIEW_APPROVAL_REFUSED', 'transaction', txn.id, {'score': result['score']},
                    actor=analyst, ip=ip)
        db.session.commit()
        raise ApiError(f'Re-evaluation now scores {result["score"]} (BLOCKED). The payment has been blocked '
                       f'and cannot be approved.', 409, 'REEVALUATION_BLOCKED')
    released = _settle(txn, reason=f'Approved by fraud analyst {analyst.full_name} after review '
                                   f'(re-evaluation score {result["score"]}).')
    if released:
        _resolve_open_alerts(txn, 'FALSE_POSITIVE', analyst, note)
    write_audit('REVIEW_APPROVED', 'transaction', txn.id,
                {'score': result['score'], 'released': released, 'notes': notes}, actor=analyst, ip=ip)
    db.session.commit()
    return {'outcome': 'released' if released else 'declined', 'transaction': txn.to_dict()}
