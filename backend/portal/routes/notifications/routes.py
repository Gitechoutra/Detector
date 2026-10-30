from flask import g, request

from portal.extensions import db
from portal.helpers.payment_engine import SECURITY_TITLE, expire_confirmations
from portal.helpers.responses import ApiError, ok
from portal.helpers.security import role_required
from portal.helpers.validators import page_args, paginate
from portal.models import Notification
from . import bp


@bp.get('')
@role_required()
def notifications():
    expire_confirmations()
    query = Notification.query.filter_by(user_id=g.current_user.id)
    if request.args.get('unread') == '1':
        query = query.filter_by(is_read=False)
    page, size = page_args(20, 50)
    items, meta = paginate(query.order_by(Notification.id.desc()), page, size)
    unread = Notification.query.filter_by(user_id=g.current_user.id, is_read=False).count()
    return ok({'items': [n.to_dict() for n in items], 'meta': meta, 'unread': unread})


@bp.post('/<int:notification_id>/read')
@role_required()
def read_notification(notification_id):
    note = db.session.get(Notification, notification_id)
    if note is None or note.user_id != g.current_user.id:
        raise ApiError('Notification not found.', 404, 'NOT_FOUND')
    if note.title != SECURITY_TITLE:      # stays open until the owner answers YES/NO or it expires
        note.is_read = True
    db.session.commit()
    return ok(note.to_dict())


@bp.post('/read-all')
@role_required()
def read_all():
    Notification.query.filter(Notification.user_id == g.current_user.id, Notification.is_read.is_(False),
                              Notification.title != SECURITY_TITLE).update({'is_read': True})
    db.session.commit()
    return ok(message='All notifications marked as read.')
