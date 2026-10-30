from portal.extensions import db
from portal.models.utils import now, iso, DT3


class SecurityEvent(db.Model):
    __tablename__ = 'security_events'
    __table_args__ = (db.Index('ix_secevent_user_type_time', 'user_id', 'event_type', 'created_at'),)
    id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    event_type = db.Column(db.String(40), nullable=False)
    severity = db.Column(db.String(10), nullable=False, default='LOW')
    description = db.Column(db.String(255), nullable=False)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'))
    ip_address = db.Column(db.String(45))
    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'))
    transaction_id = db.Column(db.BigInteger, db.ForeignKey('transactions.id', ondelete='SET NULL'))
    is_simulated = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(DT3, nullable=False, default=now, index=True)

    user = db.relationship('User', lazy='joined')
    location = db.relationship('Location', lazy='joined')

    def to_dict(self):
        return {
            'id': self.id,
            'user': self.user.full_name if self.user else None,
            'user_id': self.user_id,
            'event_type': self.event_type,
            'severity': self.severity,
            'description': self.description,
            'ip_address': self.ip_address,
            'city': self.location.city if self.location else None,
            'transaction_id': self.transaction_id,
            'is_simulated': self.is_simulated,
            'created_at': iso(self.created_at),
        }
