from flask import g
from sqlalchemy import func

from portal.extensions import db
from portal.models import Notification, Transaction
from portal.helpers.responses import ok
from portal.helpers.security import RECEIVER, role_required
from portal.helpers.validators import page_args, paginate
from . import bp



def _credited(account):
    """Incoming payments appear for the receiver only once approved and credited."""
    return Transaction.query.filter_by(receiver_account_id=account.id, status='COMPLETED')


def _incoming(txn):
    data = txn.to_dict('user')
    data['credited'] = txn.status == 'COMPLETED'
    return data


@bp.get('/dashboard')
@role_required(RECEIVER)
def dashboard():
    account = g.current_user.primary_account
    credited, received = db.session.query(func.count(Transaction.id),
                                          func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.receiver_account_id == account.id, Transaction.status == 'COMPLETED').one()
    recent = _credited(account).order_by(Transaction.txn_time.desc()).limit(6).all()
    return ok({
        'user': g.current_user.to_dict(),
        'account': account.to_dict(),
        'stats': {'credited': credited, 'total_received': float(received)},
        'recent': [_incoming(t) for t in recent],
        'unread_notifications': Notification.query.filter_by(user_id=g.current_user.id, is_read=False).count(),
    })


@bp.get('/payments')
@role_required(RECEIVER)
def payments():
    account = g.current_user.primary_account
    query = _credited(account)
    page, size = page_args()
    items, meta = paginate(query.order_by(Transaction.txn_time.desc()), page, size)
    return ok({'items': [_incoming(t) for t in items], 'meta': meta})
