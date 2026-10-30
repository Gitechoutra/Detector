"""Tamper-evident audit trail.

Each row stores the SHA-256 of its own content chained to the previous row's
hash, so editing or deleting any historical row breaks the chain from that
point on. Database triggers (see migrations) also reject UPDATE and DELETE on
audit_logs outright."""
import hashlib
import json

from sqlalchemy import text

from portal.extensions import db
from portal.models import AuditLog, now

GENESIS_HASH = '0' * 64


def _digest(prev_hash, actor_user_id, action, entity_type, entity_id, details, created_at):
    payload = json.dumps({
        'prev': prev_hash,
        'actor': actor_user_id,
        'action': action,
        'entity_type': entity_type,
        'entity_id': entity_id,
        'details': details,
        'at': created_at.isoformat(timespec='microseconds'),
    }, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def write_audit(action, entity_type=None, entity_id=None, details=None, actor=None, ip=None):
    """Adds an audit row to the current DB transaction (the caller commits)."""
    details = json.loads(json.dumps(details or {}, default=str))
    entity_id = str(entity_id) if entity_id is not None else None
    # FOR UPDATE serialises writers so two rows can never chain to the same parent.
    prev = db.session.execute(
        text('SELECT row_hash FROM audit_logs ORDER BY id DESC LIMIT 1 FOR UPDATE')).scalar()
    prev = prev or GENESIS_HASH
    created_at = now()
    actor_id = actor.id if actor else None
    db.session.add(AuditLog(
        actor_user_id=actor_id,
        actor_role=actor.role_code if actor else 'SYSTEM',
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
        ip_address=ip,
        prev_hash=prev,
        row_hash=_digest(prev, actor_id, action, entity_type, entity_id, details, created_at),
        created_at=created_at,
    ))


def verify_chain():
    prev = GENESIS_HASH
    checked = 0
    for row in AuditLog.query.order_by(AuditLog.id).yield_per(500):
        expected = _digest(prev, row.actor_user_id, row.action, row.entity_type, row.entity_id,
                           row.details, row.created_at)
        if row.prev_hash != prev or row.row_hash != expected:
            return {'valid': False, 'checked': checked, 'broken_at_id': row.id}
        prev = row.row_hash
        checked += 1
    return {'valid': True, 'checked': checked, 'broken_at_id': None}
