from flask import g, request
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import aliased

from portal.extensions import db
from portal.models import Account, Device, LoginAttempt, Notification, SecurityEvent, Transaction, User
from portal.helpers.payment_engine import expire_confirmations, resolve_receiver
from portal.helpers.responses import ApiError, ok
from portal.helpers.security import USER, role_required
from portal.helpers import investigations
from portal.helpers.validators import date_range_args, json_body, page_args, paginate
from . import bp



def _visible_to(account_id):
    """Everything the customer sent, plus incoming payments once credited: money
    still being checked, or blocked, is never shown to the receiving side."""
    return or_(Transaction.sender_account_id == account_id,
               and_(Transaction.receiver_account_id == account_id, Transaction.status == 'COMPLETED'))


FAILED = ('DECLINED', 'CANCELLED', 'EXPIRED')
# Dashboard cards → the transactions each one opens.
VIEWS = ('all', 'successful', 'failed', 'blocked', 'pending', 'awaiting', 'sent', 'received')
SORTS = {'newest': Transaction.txn_time.desc(), 'oldest': Transaction.txn_time.asc(),
         'amount_desc': Transaction.amount.desc(), 'amount_asc': Transaction.amount.asc()}


def _view_filter(view, account_id):
    sent = Transaction.sender_account_id == account_id
    return {
        'all': None,
        'successful': Transaction.status == 'COMPLETED',
        'failed': and_(sent, Transaction.status.in_(FAILED)),
        'blocked': and_(sent, Transaction.status == 'BLOCKED'),
        'pending': and_(sent, Transaction.status.in_(('UNDER_REVIEW', 'PROCESSING'))),
        'awaiting': and_(sent, Transaction.status == 'UNDER_REVIEW', Transaction.review_stage == 'AWAITING_CUSTOMER',
                         Transaction.confirmation_status.in_(('PENDING', 'CONFIRMED'))),
        'sent': and_(sent, Transaction.status == 'COMPLETED'),
        'received': and_(Transaction.receiver_account_id == account_id, Transaction.status == 'COMPLETED'),
    }[view]


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
    received_count, total_received = db.session.query(
        func.count(Transaction.id), func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.receiver_account_id == account.id, Transaction.status == 'COMPLETED').one()
    recent = (Transaction.query.filter(_visible_to(account.id))
              .order_by(Transaction.txn_time.desc()).limit(6).all())
    pending = sent.filter(Transaction.status == 'UNDER_REVIEW').order_by(Transaction.txn_time.desc()).all()
    security = (SecurityEvent.query.filter(SecurityEvent.user_id == user.id,
                                           SecurityEvent.severity.in_(('MEDIUM', 'HIGH')))
                .order_by(SecurityEvent.created_at.desc()).limit(5).all())
    unread = Notification.query.filter_by(user_id=user.id, is_read=False).count()
    return ok({
        'user': user.to_dict(),
        'account': account.to_dict(),
        'stats': {'total': db.session.query(func.count(Transaction.id)).filter(_visible_to(account.id)).scalar(),
                  'successful': db.session.query(func.count(Transaction.id)).filter(
                      _visible_to(account.id), Transaction.status == 'COMPLETED').scalar(),
                  'failed': sum(stats.get(s, 0) for s in FAILED),
                  'pending': stats.get('UNDER_REVIEW', 0) + stats.get('PROCESSING', 0),
                  'completed': stats.get('COMPLETED', 0), 'under_review': stats.get('UNDER_REVIEW', 0),
                  'blocked': stats.get('BLOCKED', 0), 'expired': stats.get('EXPIRED', 0),
                  'declined': stats.get('DECLINED', 0) + stats.get('CANCELLED', 0),
                  'total_sent': float(total_sent),
                  'received': received_count, 'total_received': float(total_received)},
        'recent': [_with_direction(t, account.id) for t in recent],
        'pending_reviews': [t.to_dict('user') for t in pending],
        'pending_confirmations': [confirmation_card(t) for t in pending_for(user)],
        'security_alerts': [e.to_dict() for e in security],
        'unread_notifications': unread,
        'restriction': investigations.open_case_for_user(user),
    })


@bp.get('/transactions')
@role_required(USER)
def transactions():
    expire_confirmations()
    account = g.current_user.primary_account
    view = request.args.get('view') or 'all'
    if view not in VIEWS:
        raise ApiError(f'Unknown view. Use one of: {", ".join(VIEWS)}.', 422, 'VALIDATION_ERROR', {'field': 'view'})
    sort = SORTS.get(request.args.get('sort') or 'newest')
    if sort is None:
        raise ApiError('Sort by newest, oldest, amount_desc or amount_asc.', 422, 'VALIDATION_ERROR', {'field': 'sort'})
    query = Transaction.query.filter(_visible_to(account.id))
    view_filter = _view_filter(view, account.id)
    if view_filter is not None:
        query = query.filter(view_filter)
    if request.args.get('status'):
        query = query.filter(Transaction.status == request.args['status'])
    if request.args.get('direction') == 'OUT':
        query = query.filter(Transaction.sender_account_id == account.id)
    elif request.args.get('direction') == 'IN':
        query = query.filter(Transaction.receiver_account_id == account.id)
    start, end = date_range_args()
    if start:
        query = query.filter(Transaction.txn_time >= start)
    if end:
        query = query.filter(Transaction.txn_time < end)
    q = (request.args.get('q') or '').strip()[:60]
    if q:
        # Search the reference, remarks and either party's name or UPI ID.
        sender_acc, receiver_acc = aliased(Account), aliased(Account)
        sender_user, receiver_user = aliased(User), aliased(User)
        like = f'%{q}%'
        query = (query.join(sender_acc, sender_acc.id == Transaction.sender_account_id)
                 .join(receiver_acc, receiver_acc.id == Transaction.receiver_account_id)
                 .join(sender_user, sender_user.id == sender_acc.user_id)
                 .join(receiver_user, receiver_user.id == receiver_acc.user_id)
                 .filter(or_(Transaction.txn_ref.like(like), Transaction.remarks.like(like),
                             sender_user.full_name.like(like), receiver_user.full_name.like(like),
                             sender_acc.upi_id.like(like), receiver_acc.upi_id.like(like))))
    total_amount = query.with_entities(func.coalesce(func.sum(Transaction.amount), 0)).scalar()
    page, size = page_args()
    items, meta = paginate(query.order_by(sort, Transaction.id.desc()), page, size)
    return ok({'items': [_with_direction(t, account.id) for t in items], 'meta': meta,
               'summary': {'view': view, 'count': meta['total'], 'amount': float(total_amount)}})


@bp.get('/transactions/<int:txn_id>')
@role_required(USER)
def transaction_detail(txn_id):
    account = g.current_user.primary_account
    txn = db.session.get(Transaction, txn_id)
    if txn is None or not (txn.sender_account_id == account.id
                           or (txn.receiver_account_id == account.id and txn.status == 'COMPLETED')):
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
