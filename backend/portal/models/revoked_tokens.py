from portal.extensions import db
from portal.models.utils import now, DT3


class RevokedToken(db.Model):
    """A login token ended by logout. JWTs are otherwise valid until they expire,
    so every request checks this list. Rows past their expiry are pruned."""
    __tablename__ = 'revoked_tokens'
    jti = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    expires_at = db.Column(DT3, nullable=False, index=True)
    revoked_at = db.Column(DT3, nullable=False, default=now)
