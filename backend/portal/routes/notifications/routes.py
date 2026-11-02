from flask import g, request

from portal.extensions import db
from portal.helpers.payment_engine import SECURITY_TITLES, expire_confirmations
from portal.helpers.responses import ApiError, ok
from portal.helpers.security import role_required
from portal.helpers.validators import page_args, paginate
from portal.models import Account, Notification, Transaction, now
from . import bp


@bp.get('')
@role_required()
def notifications():
    expire_confirmations()
    # OTP messages are not listed: the code is shown on the verification card instead.
    visible = Notification.query.filter(Notification.user_id == g.current_user.id, Notification.cleared_at.is_(None),
                                        Notification.category != 'OTP')
    query = visible.filter_by(is_read=False) if request.args.get('unread') == '1' else visible
    page, size = page_args(20, 50)
    items, meta = paginate(query.order_by(Notification.id.desc()), page, size)
    unread = visible.filter_by(is_read=False).count()
    return ok({'items': [n.to_dict() for n in items], 'meta': meta, 'unread': unread})


@bp.post('/<int:notification_id>/read')
@role_required()
def read_notification(notification_id):
    note = db.session.get(Notification, notification_id)
    if note is None or note.user_id != g.current_user.id:
        raise ApiError('Notification not found.', 404, 'NOT_FOUND')
    if note.title not in SECURITY_TITLES:      # stays open until the owner answers YES/NO or it expires
        note.is_read = True
    db.session.commit()
    return ok(note.to_dict())


@bp.post('/read-all')
@role_required()
def read_all():
    """Marks everything read and clears it from the list. Kept until done: a
    verification request not yet answered, and the OTP of one answered YES."""
    open_txns = (Transaction.query.join(Account, Account.id == Transaction.sender_account_id)
                 .filter(Account.user_id == g.current_user.id, Transaction.status == 'UNDER_REVIEW',
                         Transaction.review_stage == 'AWAITING_CUSTOMER',
                         Transaction.confirmation_status.in_(('PENDING', 'CONFIRMED'))).all())
    unanswered = [t.id for t in open_txns if t.confirmation_status == 'PENDING'] or [0]
    awaiting_otp = [t.id for t in open_txns if t.confirmation_status == 'CONFIRMED'] or [0]
    keep = db.or_(db.and_(Notification.transaction_id.in_(unanswered), Notification.title.in_(SECURITY_TITLES)),
                  db.and_(Notification.transaction_id.in_(awaiting_otp), Notification.category == 'OTP'))
    cleared = Notification.query.filter(Notification.user_id == g.current_user.id, Notification.cleared_at.is_(None),
                                        db.not_(keep)).update({'is_read': True, 'cleared_at': now()},
                                                              synchronize_session=False)
    db.session.commit()
    return ok({'cleared': cleared}, 'All notifications marked as read and cleared.')
