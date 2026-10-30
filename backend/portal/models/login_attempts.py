from portal.extensions import db
from portal.models.utils import now, DT3


class LoginAttempt(db.Model):
    __tablename__ = 'login_attempts'
    __table_args__ = (db.Index('ix_login_user_time', 'user_id', 'created_at'),)
    id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    email = db.Column(db.String(120), nullable=False)
    success = db.Column(db.Boolean, nullable=False)
    failure_reason = db.Column(db.String(50))
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'))
    fingerprint = db.Column(db.String(64))
    ip_address = db.Column(db.String(45))
    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'))
    is_new_device = db.Column(db.Boolean, nullable=False, default=False)
    is_simulated = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(DT3, nullable=False, default=now, index=True)

    location = db.relationship('Location', lazy='joined')
