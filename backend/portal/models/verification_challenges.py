from portal.extensions import db
from portal.models.utils import now


class VerificationChallenge(db.Model):
    __tablename__ = 'verification_challenges'
    id = db.Column(db.BigInteger, primary_key=True)
    transaction_id = db.Column(db.BigInteger, db.ForeignKey('transactions.id', ondelete='CASCADE'),
                               nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    otp_hash = db.Column(db.String(255), nullable=False)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    max_attempts = db.Column(db.Integer, nullable=False, default=3)
    status = db.Column(db.String(10), nullable=False, default='PENDING')
    expires_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=now)
    verified_at = db.Column(db.DateTime)
