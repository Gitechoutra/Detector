from portal.extensions import db
from portal.models.utils import now, iso


class Device(db.Model):
    __tablename__ = 'devices'
    __table_args__ = (db.UniqueConstraint('user_id', 'fingerprint', name='uq_device_user_fp'),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    fingerprint = db.Column(db.String(64), nullable=False)
    device_name = db.Column(db.String(150))
    is_trusted = db.Column(db.Boolean, nullable=False, default=False)
    first_seen_at = db.Column(db.DateTime, nullable=False, default=now)
    last_seen_at = db.Column(db.DateTime, nullable=False, default=now)
    last_ip = db.Column(db.String(45))
    last_location_id = db.Column(db.Integer, db.ForeignKey('locations.id'))

    def to_dict(self):
        return {
            'id': self.id,
            'device_name': self.device_name,
            'fingerprint': self.fingerprint[:8] + '…',
            'is_trusted': self.is_trusted,
            'first_seen_at': iso(self.first_seen_at),
            'last_seen_at': iso(self.last_seen_at),
            'last_ip': self.last_ip,
        }
