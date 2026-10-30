from datetime import timedelta

from flask import g, request
from sqlalchemy import or_

from portal.extensions import db
from portal.models import (Account, Alert, FraudRule, LoginAttempt, RiskAssessment, RiskCategory, Role,
                      SecurityEvent, Transaction, TriggeredRule, User, WatchlistEntry)
from portal.helpers import payment_engine
from portal.helpers.audit import write_audit
from portal.helpers.responses import ApiError, ok
from portal.helpers.security import DETECTION, client_ip, role_required
from portal.helpers.validators import date_range_args, json_body, page_args, paginate, parse_int, require_str
from . import bp


WATCHLIST_TYPES = ('ACCOUNT', 'UPI', 'DEVICE', 'IP')


def _filtered_transactions():
    query = Transaction.query.join(Account, Account.id == Transaction.sender_account_id)
    start, end = date_range_args()
    if start:
        query = query.filter(Transaction.txn_time >= start)
    if end:
        query = query.filter(Transaction.txn_time < end)
    if request.args.get('status'):
        query = query.filter(Transaction.status == request.args['status'])
    if request.args.get('risk_level'):
        query = query.filter(Transaction.decision == request.args['risk_level'])
    if request.args.get('user_id'):
        query = query.filter(Account.user_id == request.args.get('user_id', type=int))
    if request.args.get('source') == 'manual':
        query = query.filter(Transaction.is_simulated.is_(False))
    elif request.args.get('source') == 'simulated':
        query = query.filter(Transaction.is_simulated.is_(True))
    if request.args.get('q'):
        query = query.filter(Transaction.txn_ref.like(f"%{request.args['q'].strip()}%"))
    return query


@bp.get('/transactions')
@role_required(DETECTION)
def transactions():
    page, size = page_args(25)
    items, meta = paginate(_filtered_transactions().order_by(Transaction.id.desc()), page, size)
    return ok({'items': [t.to_dict() for t in items], 'meta': meta})


@bp.get('/live')
@role_required(DETECTION)
def live():
    """Polled every ~2 s by the monitor. Returns rows newer than after_id."""
    after_id = request.args.get('after_id', 0, type=int)
    limit = min(50, request.args.get('limit', 25, type=int))
    query = _filtered_transactions()
    if after_id:
        query = query.filter(Transaction.id > after_id)
    rows = query.order_by(Transaction.id.desc()).limit(limit).all()
    latest_alerts = Alert.query.order_by(Alert.id.desc()).limit(6).all()
    return ok({
        'transactions': [t.to_dict() for t in rows],
        'latest_id': max([t.id for t in rows], default=after_id),
        'open_alerts': Alert.query.filter(Alert.status != 'RESOLVED').count(),
        'awaiting_analyst': Transaction.query.filter_by(status='UNDER_REVIEW', review_stage='AWAITING_ANALYST').count(),
        'latest_alerts': [a.to_dict() for a in latest_alerts],
    })


@bp.get('/confirmations')
@role_required(DETECTION)
def confirmations():
    """Payments that asked their owner "Was this you?": pending ones first, then
    the latest answers and what finally happened."""
    payment_engine.expire_confirmations()
    base = Transaction.query.filter(Transaction.confirmation_status.isnot(None))
    pending = (base.filter(Transaction.confirmation_status.in_(('PENDING', 'CONFIRMED')),
                           Transaction.status == 'UNDER_REVIEW')
               .order_by(Transaction.confirmation_expires_at).all())
    answered = (base.filter(Transaction.id.notin_([t.id for t in pending] or [0]))
                .order_by(Transaction.id.desc()).limit(15).all())
    counts = dict(db.session.query(Transaction.confirmation_response, db.func.count())
                  .filter(Transaction.confirmation_response.isnot(None))
                  .group_by(Transaction.confirmation_response).all())
    return ok({'pending': [t.to_dict() for t in pending], 'recent': [t.to_dict() for t in answered],
               'counts': {'pending': len(pending), 'yes': counts.get('YES', 0), 'no': counts.get('NO', 0),
                          'expired': base.filter(Transaction.confirmation_status == 'EXPIRED').count()}})


@bp.get('/transactions/<int:txn_id>')
@role_required(DETECTION)
def investigate(txn_id):
    payment_engine.expire_confirmations()
    txn = db.session.get(Transaction, txn_id)
    if txn is None:
        raise ApiError('Transaction not found.', 404, 'NOT_FOUND')
    sender = txn.sender_account.user
    window_start = txn.txn_time - timedelta(hours=24)

    assessments = []
    for a in RiskAssessment.query.filter_by(transaction_id=txn.id).order_by(RiskAssessment.id).all():
        data = a.to_dict()
        data['hits'] = [h.to_dict() for h in TriggeredRule.query.filter_by(assessment_id=a.id).all()]
        assessments.append(data)

    history = (Transaction.query.filter(Transaction.sender_account_id == txn.sender_account_id,
                                        Transaction.id != txn.id)
               .order_by(Transaction.txn_time.desc()).limit(10).all())
    logins = (LoginAttempt.query.filter(LoginAttempt.user_id == sender.id,
                                        LoginAttempt.created_at.between(window_start, txn.txn_time))
              .order_by(LoginAttempt.created_at.desc()).limit(20).all())
    events = (SecurityEvent.query.filter(SecurityEvent.user_id == sender.id,
                                         SecurityEvent.created_at.between(window_start,
                                                                          txn.txn_time + timedelta(hours=1)))
              .order_by(SecurityEvent.created_at.desc()).limit(20).all())
    receiver = txn.receiver_account
    watch_values = [receiver.account_number, receiver.upi_id, txn.ip_address,
                    txn.device.fingerprint if txn.device else None]
    watch_hits = WatchlistEntry.query.filter(WatchlistEntry.entity_value.in_([v for v in watch_values if v])).all()

    data = txn.to_dict()
    data.update({
        'sender_profile': {**sender.to_dict(), 'balance': float(txn.sender_account.balance),
                           'account_number': txn.sender_account.account_number},
        'receiver_profile': {'name': receiver.user.full_name, 'upi_id': receiver.upi_id,
                             'account_number': receiver.account_number, 'role': receiver.user.role_code},
        'device_fingerprint': txn.device.fingerprint if txn.device else None,
        'assessments': assessments,
        'alerts': [a.to_dict() for a in Alert.query.filter_by(transaction_id=txn.id).all()],
        'sender_history': [t.to_dict() for t in history],
        'logins': [{'success': l.success, 'failure_reason': l.failure_reason, 'ip_address': l.ip_address,
                    'city': l.location.city if l.location else None, 'is_new_device': l.is_new_device,
                    'is_simulated': l.is_simulated, 'created_at': l.created_at.isoformat(timespec='seconds')}
                   for l in logins],
        'security_events': [e.to_dict() for e in events],
        'watchlist_matches': [w.to_dict() for w in watch_hits],
    })
    return ok(data)


@bp.post('/transactions/<int:txn_id>/decision')
@role_required(DETECTION)
def decide(txn_id):
    data = json_body()
    action = (data.get('action') or '').upper()
    notes = require_str(data, 'notes', 500, 'Notes', required=False)
    result = payment_engine.analyst_decision(g.current_user, txn_id, action, notes, client_ip())
    message = {'released': 'Payment approved and released.', 'declined': 'Release failed: insufficient balance.',
               'rejected': 'Payment rejected.'}[result['outcome']]
    return ok(result, message)


# ── Rules & score bands ─────────────────────────────────────────────────────

@bp.get('/rules')
@role_required(DETECTION)
def rules():
    return ok([r.to_dict() for r in FraudRule.query.order_by(FraudRule.code).all()])


@bp.put('/rules/<code>')
@role_required(DETECTION)
def update_rule(code):
    rule = FraudRule.query.filter_by(code=code.upper()).first()
    if rule is None:
        raise ApiError('Rule not found.', 404, 'NOT_FOUND')
    data = json_body()
    before = rule.to_dict()
    if 'weight' in data:
        rule.weight = parse_int(data['weight'], 'Weight', 0, 100)
    if 'is_active' in data:
        rule.is_active = bool(data['is_active'])
    if 'params' in data:
        params = data['params']
        if not isinstance(params, dict) or set(params) != set(rule.default_params):
            raise ApiError('Parameters must contain exactly: ' + ', '.join(sorted(rule.default_params)), 422,
                           'VALIDATION_ERROR')
        clean = {}
        for key, value in params.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise ApiError(f'{key} must be a non-negative number.', 422, 'VALIDATION_ERROR', {'field': key})
            clean[key] = int(value) if float(value).is_integer() else float(value)
        for lo, hi in (('start_hour', 'end_hour'),):
            if lo in clean and not 0 <= clean[lo] < clean[hi] <= 24:
                raise ApiError('Hours must satisfy 0 ≤ start < end ≤ 24.', 422, 'VALIDATION_ERROR')
        rule.params = clean
    if data.get('restore_defaults'):
        rule.weight, rule.params = rule.default_weight, rule.default_params
    rule.updated_by = g.current_user.id
    write_audit('RULE_UPDATED', 'fraud_rule', rule.code,
                {'before': {k: before[k] for k in ('weight', 'params', 'is_active')},
                 'after': {'weight': rule.weight, 'params': rule.params, 'is_active': rule.is_active}},
                actor=g.current_user, ip=client_ip())
    db.session.commit()
    return ok(rule.to_dict(), f'Rule {rule.code} updated.')


@bp.get('/risk-categories')
@role_required(DETECTION)
def risk_categories():
    return ok([c.to_dict() for c in RiskCategory.query.order_by(RiskCategory.min_score).all()])


@bp.put('/risk-categories')
@role_required(DETECTION)
def update_risk_categories():
    data = json_body()
    review_min = parse_int(data.get('review_min'), 'Review starts at', 1, 99)
    blocked_min = parse_int(data.get('blocked_min'), 'Blocked starts at', 2, 100)
    if blocked_min <= review_min:
        raise ApiError('BLOCKED must start above REVIEW.', 422, 'VALIDATION_ERROR')
    bands = {'APPROVED': (0, review_min - 1), 'REVIEW': (review_min, blocked_min - 1), 'BLOCKED': (blocked_min, 100)}
    for cat in RiskCategory.query.all():
        cat.min_score, cat.max_score = bands[cat.code]
    write_audit('RISK_BANDS_UPDATED', 'risk_categories', None, {'bands': bands}, actor=g.current_user,
                ip=client_ip())
    db.session.commit()
    return ok([c.to_dict() for c in RiskCategory.query.order_by(RiskCategory.min_score).all()],
              'Score bands updated.')


# ── Watchlist ───────────────────────────────────────────────────────────────

@bp.get('/watchlist')
@role_required(DETECTION)
def watchlist():
    query = WatchlistEntry.query
    if request.args.get('entity_type'):
        query = query.filter_by(entity_type=request.args['entity_type'])
    return ok([w.to_dict() for w in query.order_by(WatchlistEntry.created_at.desc()).all()])


@bp.post('/watchlist')
@role_required(DETECTION)
def add_watchlist():
    data = json_body()
    entity_type = (data.get('entity_type') or '').upper()
    if entity_type not in WATCHLIST_TYPES:
        raise ApiError('Type must be one of ' + ', '.join(WATCHLIST_TYPES), 422, 'VALIDATION_ERROR')
    value = require_str(data, 'entity_value', 120, 'Value')
    if entity_type == 'UPI':
        value = value.lower()
    reason = require_str(data, 'reason', 255, 'Reason')
    entry = WatchlistEntry.query.filter_by(entity_type=entity_type, entity_value=value).first()
    if entry:
        if entry.is_active:
            raise ApiError('This entity is already on the watchlist.', 409, 'DUPLICATE')
        entry.is_active, entry.reason = True, reason
    else:
        entry = WatchlistEntry(entity_type=entity_type, entity_value=value, reason=reason, source='MANUAL',
                               added_by=g.current_user.id)
        db.session.add(entry)
    write_audit('WATCHLIST_ADDED', 'watchlist', f'{entity_type}:{value}', {'reason': reason},
                actor=g.current_user, ip=client_ip())
    db.session.commit()
    return ok(entry.to_dict(), 'Added to watchlist.', 201)


@bp.patch('/watchlist/<int:entry_id>')
@role_required(DETECTION)
def toggle_watchlist(entry_id):
    entry = db.session.get(WatchlistEntry, entry_id)
    if entry is None:
        raise ApiError('Entry not found.', 404, 'NOT_FOUND')
    entry.is_active = bool(json_body().get('is_active'))
    write_audit('WATCHLIST_ACTIVATED' if entry.is_active else 'WATCHLIST_DEACTIVATED', 'watchlist', entry.id,
                {'value': entry.entity_value}, actor=g.current_user, ip=client_ip())
    db.session.commit()
    return ok(entry.to_dict(), 'Watchlist updated.')


@bp.delete('/watchlist/<int:entry_id>')
@role_required(DETECTION)
def delete_watchlist(entry_id):
    entry = db.session.get(WatchlistEntry, entry_id)
    if entry is None:
        raise ApiError('Entry not found.', 404, 'NOT_FOUND')
    if entry.source == 'SEED':
        raise ApiError('Seeded entries can be deactivated but not deleted.', 409, 'SEED_ENTRY')
    write_audit('WATCHLIST_REMOVED', 'watchlist', entry.id, {'value': entry.entity_value},
                actor=g.current_user, ip=client_ip())
    db.session.delete(entry)
    db.session.commit()
    return ok(message='Removed from watchlist.')


@bp.get('/users')
@role_required(DETECTION)
def users():
    """Senders, for the monitor's user filter."""
    rows = (User.query.join(Role).filter(Role.code == 'USER')
            .order_by(User.is_simulated, User.full_name).all())
    return ok([{'id': u.id, 'name': u.full_name, 'email': u.email, 'is_simulated': u.is_simulated} for u in rows])


@bp.get('/search')
@role_required(DETECTION)
def search():
    q = (request.args.get('q') or '').strip()
    if len(q) < 2:
        return ok([])
    rows = (Transaction.query.join(Account, Account.id == Transaction.sender_account_id).join(User)
            .filter(or_(Transaction.txn_ref.like(f'%{q}%'), User.full_name.like(f'%{q}%')))
            .order_by(Transaction.id.desc()).limit(10).all())
    return ok([t.to_dict() for t in rows])
