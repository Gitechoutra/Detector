from portal.extensions import db
from portal.models.utils import iso, DT6


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    id = db.Column(db.BigInteger, primary_key=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    actor_role = db.Column(db.String(20))
    action = db.Column(db.String(60), nullable=False)
    entity_type = db.Column(db.String(40))
    entity_id = db.Column(db.String(40))
    details = db.Column(db.JSON)
    ip_address = db.Column(db.String(45))
    prev_hash = db.Column(db.CHAR(64), nullable=False)
    row_hash = db.Column(db.CHAR(64), nullable=False)
    created_at = db.Column(DT6, nullable=False, index=True)

    actor = db.relationship('User', lazy='joined')

    def to_dict(self):
        return {'id': self.id, 'actor': self.actor.full_name if self.actor else 'System',
                'actor_role': self.actor_role, 'action': self.action, 'entity_type': self.entity_type,
                'entity_id': self.entity_id, 'details': self.details, 'ip_address': self.ip_address,
                'row_hash': self.row_hash, 'created_at': iso(self.created_at)}
