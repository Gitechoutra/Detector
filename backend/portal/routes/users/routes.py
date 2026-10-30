from flask import g, request
from sqlalchemy import func, or_

from portal.extensions import db
from portal.models import Device, LoginAttempt, Notification, SecurityEvent, Transaction
from portal.helpers.payment_engine import expire_confirmations, resolve_receiver
from portal.helpers.responses import ApiError, ok
from portal.helpers.security import USER, role_required
from portal.helpers.validators import json_body, page_args, paginate
from . import bp



def _with_direction(txn, account_id):
    data = txn.to_dict('user')
    data['direction'] = 'OUT' if txn.sender_account_id == account_id else 'IN'
    return data


@bp.get('/dashboard')
@role_required(USER)
def dashboard():
    from portal.routes.transactions.routes import confirmation_card, pending_for
    expire_confirmations()
    user = g.current_user
    account = user.primary_account
    sent = Transaction.query.filter_by(sender_account_id=account.id)
    stats = dict(db.session.query(Transaction.status, func.count()).filter(
        Transaction.sender_account_id == account.id).group_by(Transaction.status).all())
    total_sent = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.sender_account_id == account.id, Transaction.status == 'COMPLETED').scalar()
    recent = (Transaction.query.filter(or_(Transaction.sender_account_id == account.id,
                                           Transaction.receiver_account_id == account.id))
              .order_by(Transaction.txn_time.desc()).limit(6).all())
    pending = sent.filter(Transaction.status == 'UNDER_REVIEW').order_by(Transaction.txn_time.desc()).all()
    security = (SecurityEvent.query.filter(SecurityEvent.user_id == user.id,
                                           SecurityEvent.severity.in_(('MEDIUM', 'HIGH')))
                .order_by(SecurityEvent.created_at.desc()).limit(5).all())
    unread = Notification.query.filter_by(user_id=user.id, is_read=False).count()
    return ok({
        'user': user.to_dict(),
        'account': account.to_dict(),
        'stats': {'completed': stats.get('COMPLETED', 0), 'under_review': stats.get('UNDER_REVIEW', 0),
                  'blocked': stats.get('BLOCKED', 0), 'expired': stats.get('EXPIRED', 0),
                  'declined': stats.get('DECLINED', 0) + stats.get('CANCELLED', 0),
                  'total_sent': float(total_sent)},
        'recent': [_with_direction(t, account.id) for t in recent],
        'pending_reviews': [t.to_dict('user') for t in pending],
        'pending_confirmations': [confirmation_card(t) for t in pending_for(user)],
        'security_alerts': [e.to_dict() for e in security],
        'unread_notifications': unread,
    })


@bp.get('/transactions')
@role_required(USER)
def transactions():
    expire_confirmations()
    account = g.current_user.primary_account
    query = Transaction.query.filter(or_(Transaction.sender_account_id == account.id,
                                         Transaction.receiver_account_id == account.id))
    if request.args.get('status'):
        query = query.filter(Transaction.status == request.args['status'])
    if request.args.get('direction') == 'OUT':
        query = query.filter(Transaction.sender_account_id == account.id)
    elif request.args.get('direction') == 'IN':
        query = query.filter(Transaction.receiver_account_id == account.id)
    page, size = page_args()
    items, meta = paginate(query.order_by(Transaction.txn_time.desc()), page, size)
    return ok({'items': [_with_direction(t, account.id) for t in items], 'meta': meta})


@bp.get('/transactions/<int:txn_id>')
@role_required(USER)
def transaction_detail(txn_id):
    account = g.current_user.primary_account
    txn = db.session.get(Transaction, txn_id)
    if txn is None or account.id not in (txn.sender_account_id, txn.receiver_account_id):
        raise ApiError('Payment not found.', 404, 'NOT_FOUND')
    return ok(_with_direction(txn, account.id))


@bp.post('/receivers/lookup')
@role_required(USER)
def lookup_receiver():
    data = json_body()
    account = resolve_receiver(data.get('payment_method'), data)
    if account.id == g.current_user.primary_account.id:
        raise ApiError('This is your own account.', 422, 'SAME_ACCOUNT')
    return ok(account.counterparty_dict())


@bp.get('/security')
@role_required(USER)
def security():
    user = g.current_user
    logins = (LoginAttempt.query.filter_by(user_id=user.id).order_by(LoginAttempt.created_at.desc())
              .limit(20).all())
    devices = Device.query.filter_by(user_id=user.id).order_by(Device.last_seen_at.desc()).all()
    events = (SecurityEvent.query.filter_by(user_id=user.id).order_by(SecurityEvent.created_at.desc())
              .limit(20).all())
    return ok({
        'current_device_id': g.device_id,
        'devices': [d.to_dict() for d in devices],
        'logins': [{'success': l.success, 'failure_reason': l.failure_reason, 'ip_address': l.ip_address,
                    'city': l.location.city if l.location else None, 'is_new_device': l.is_new_device,
                    'created_at': l.created_at.isoformat(timespec='seconds')} for l in logins],
        'events': [e.to_dict() for e in events],
    })
