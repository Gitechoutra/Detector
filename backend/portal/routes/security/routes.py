from flask import request

from portal.models import AuditLog, LoginAttempt, SecurityEvent, User
from portal.helpers.audit import verify_chain
from portal.helpers.responses import ok
from portal.helpers.security import DETECTION, role_required
from portal.helpers.validators import date_range_args, page_args, paginate
from . import bp



def _common(query, model, time_col):
    start, end = date_range_args()
    if start:
        query = query.filter(time_col >= start)
    if end:
        query = query.filter(time_col < end)
    if request.args.get('user_id'):
        query = query.filter(model.user_id == request.args.get('user_id', type=int))
    if request.args.get('source') == 'manual':
        query = query.filter(model.is_simulated.is_(False))
    elif request.args.get('source') == 'simulated':
        query = query.filter(model.is_simulated.is_(True))
    return query


@bp.get('/events')
@role_required(DETECTION)
def events():
    query = _common(SecurityEvent.query, SecurityEvent, SecurityEvent.created_at)
    if request.args.get('event_type'):
        query = query.filter(SecurityEvent.event_type == request.args['event_type'])
    if request.args.get('severity'):
        query = query.filter(SecurityEvent.severity == request.args['severity'])
    page, size = page_args(25)
    items, meta = paginate(query.order_by(SecurityEvent.id.desc()), page, size)
    return ok({'items': [e.to_dict() for e in items], 'meta': meta})


@bp.get('/login-attempts')
@role_required(DETECTION)
def login_attempts():
    query = _common(LoginAttempt.query, LoginAttempt, LoginAttempt.created_at)
    if request.args.get('success') in ('0', '1'):
        query = query.filter(LoginAttempt.success.is_(request.args['success'] == '1'))
    page, size = page_args(25)
    items, meta = paginate(query.order_by(LoginAttempt.id.desc()), page, size)
    names = {u.id: u.full_name for u in User.query.filter(User.id.in_({i.user_id for i in items if i.user_id}))}
    return ok({'items': [{
        'id': l.id, 'user': names.get(l.user_id), 'email': l.email, 'success': l.success,
        'failure_reason': l.failure_reason, 'ip_address': l.ip_address,
        'city': l.location.city if l.location else None, 'is_new_device': l.is_new_device,
        'is_simulated': l.is_simulated, 'created_at': l.created_at.isoformat(timespec='seconds'),
    } for l in items], 'meta': meta})


@bp.get('/audit-logs')
@role_required(DETECTION)
def audit_logs():
    query = AuditLog.query
    if request.args.get('action'):
        query = query.filter(AuditLog.action == request.args['action'])
    page, size = page_args(25)
    items, meta = paginate(query.order_by(AuditLog.id.desc()), page, size)
    return ok({'items': [a.to_dict() for a in items], 'meta': meta})


@bp.get('/audit/verify')
@role_required(DETECTION)
def verify_audit():
    return ok(verify_chain())
