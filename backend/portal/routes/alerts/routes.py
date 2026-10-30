from flask import g, request

from portal.extensions import db
from portal.helpers.audit import write_audit
from portal.helpers.payment_engine import _decline
from portal.helpers.responses import ApiError, ok
from portal.helpers.security import DETECTION, client_ip, role_required
from portal.helpers.validators import date_range_args, json_body, page_args, paginate, require_str
from portal.models import Alert, now
from . import bp

RESOLUTIONS = ('CONFIRMED_FRAUD', 'FALSE_POSITIVE')


@bp.get('')
@role_required(DETECTION)
def list_alerts():
    query = Alert.query
    for field in ('status', 'severity', 'alert_type'):
        if request.args.get(field):
            query = query.filter(getattr(Alert, field) == request.args[field])
    if request.args.get('source') == 'manual':
        query = query.filter(Alert.is_simulated.is_(False))
    elif request.args.get('source') == 'simulated':
        query = query.filter(Alert.is_simulated.is_(True))
    start, end = date_range_args()
    if start:
        query = query.filter(Alert.created_at >= start)
    if end:
        query = query.filter(Alert.created_at < end)
    page, size = page_args(20)
    items, meta = paginate(query.order_by(Alert.id.desc()), page, size)
    counts = dict(db.session.query(Alert.status, db.func.count()).group_by(Alert.status).all())
    return ok({'items': [a.to_dict() for a in items], 'meta': meta, 'counts': counts})


@bp.patch('/<int:alert_id>')
@role_required(DETECTION)
def update_alert(alert_id):
    alert = db.session.get(Alert, alert_id)
    if alert is None:
        raise ApiError('Alert not found.', 404, 'NOT_FOUND')
    data = json_body()
    action = (data.get('action') or '').lower()
    analyst = g.current_user
    notes = require_str(data, 'notes', 1000, 'Notes', required=False)

    if action == 'assign':
        alert.assigned_to, alert.status = analyst.id, 'INVESTIGATING'
    elif action == 'note':
        if not notes:
            raise ApiError('Write a note first.', 422, 'VALIDATION_ERROR')
    elif action == 'resolve':
        resolution = (data.get('resolution') or '').upper()
        if resolution not in RESOLUTIONS:
            raise ApiError('Resolution must be CONFIRMED_FRAUD or FALSE_POSITIVE.', 422, 'VALIDATION_ERROR')
        alert.status, alert.resolution, alert.resolved_at = 'RESOLVED', resolution, now()
        alert.assigned_to = alert.assigned_to or analyst.id
        # Confirming fraud on a payment that is still held declines it; a false
        # positive does not release money by itself (use Approve in the case view).
        if resolution == 'CONFIRMED_FRAUD' and alert.transaction and alert.transaction.status == 'UNDER_REVIEW':
            _decline(alert.transaction, 'Confirmed as fraud by the fraud team.')
    elif action == 'reopen':
        alert.status, alert.resolution, alert.resolved_at = 'OPEN', None, None
    else:
        raise ApiError('Unknown action.', 422, 'VALIDATION_ERROR')

    if notes:
        stamp = f'[{now():%d %b %H:%M}] {analyst.full_name}: {notes}'
        alert.analyst_notes = f'{alert.analyst_notes}\n{stamp}' if alert.analyst_notes else stamp
    write_audit(f'ALERT_{action.upper()}', 'alert', alert.id,
                {'resolution': alert.resolution, 'notes': notes}, actor=analyst, ip=client_ip())
    db.session.commit()
    return ok(alert.to_dict(), 'Alert updated.')
