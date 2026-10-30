from portal.extensions import db
from portal.models.utils import now, money, iso, DT3


class Account(db.Model):
    __tablename__ = 'accounts'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    account_number = db.Column(db.String(20), unique=True, nullable=False)
    ifsc = db.Column(db.String(11), nullable=False)
    upi_id = db.Column(db.String(60), unique=True, nullable=False)
    qr_token = db.Column(db.String(40), unique=True, nullable=False)
    account_type = db.Column(db.String(20), nullable=False, default='SAVINGS')
    balance = db.Column(db.Numeric(15, 2), nullable=False, default=0)
    opening_balance = db.Column(db.Numeric(15, 2), nullable=False, default=0)
    status = db.Column(db.String(20), nullable=False, default='ACTIVE')
    last_txn_at = db.Column(DT3)
    created_at = db.Column(db.DateTime, nullable=False, default=now)

    user = db.relationship('User', back_populates='accounts', lazy='joined')

    @property
    def qr_payload(self):
        return f'upi://pay?pa={self.upi_id}&pn={self.user.full_name}&tr={self.qr_token}'

    def to_dict(self):
        return {
            'id': self.id,
            'account_number': self.account_number,
            'ifsc': self.ifsc,
            'upi_id': self.upi_id,
            'qr_payload': self.qr_payload,
            'account_type': self.account_type,
            'balance': money(self.balance),
            'status': self.status,
            'holder_name': self.user.full_name,
            'last_txn_at': iso(self.last_txn_at),
        }

    def counterparty_dict(self):
        """What the other side of a payment may see: no balance."""
        return {
            'account_id': self.id,
            'name': self.user.full_name,
            'upi_id': self.upi_id,
            'account_number': '•••• ' + self.account_number[-4:],
            'ifsc': self.ifsc,
        }
