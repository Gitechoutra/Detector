from portal.extensions import db
from portal.models.utils import now, money, iso, DT3


class ReceiverBlock(db.Model):
    """A receiver account blocked because the payer's account owner answered NO
    ("I did not initiate this transaction"). While a block is ACTIVE the account's
    status is BLOCKED and it cannot receive money."""
    __tablename__ = 'receiver_blocks'
    __table_args__ = (db.Index('ix_receiver_block_account_status', 'account_id', 'status'),)
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=False)
    transaction_id = db.Column(db.BigInteger, db.ForeignKey('transactions.id'), nullable=False, index=True)
    reported_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reason = db.Column(db.String(255), nullable=False)
    risk_score = db.Column(db.Integer)
    risk_factors = db.Column(db.JSON)          # [{code, name, weight, reason}]
    transaction_snapshot = db.Column(db.JSON)  # ref, amount, sender, time, method at the moment of the block
    status = db.Column(db.String(10), nullable=False, default='ACTIVE')   # ACTIVE / LIFTED
    blocked_at = db.Column(DT3, nullable=False, default=now)
    lifted_at = db.Column(DT3)
    lifted_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    lift_reason = db.Column(db.String(255))

    account = db.relationship('Account', lazy='joined')
    reporter = db.relationship('User', foreign_keys=[reported_by], lazy='joined')
    lifter = db.relationship('User', foreign_keys=[lifted_by], lazy='joined')

    def to_dict(self):
        return {
            'id': self.id,
            'account_id': self.account_id,
            'receiver': {'name': self.account.user.full_name, 'upi_id': self.account.upi_id,
                         'account_number': self.account.account_number, 'account_status': self.account.status},
            'transaction_id': self.transaction_id,
            'reported_by': self.reporter.full_name if self.reporter else None,
            'reason': self.reason,
            'risk_score': self.risk_score,
            'risk_factors': self.risk_factors or [],
            'transaction': self.transaction_snapshot,
            'status': self.status,
            'blocked_at': iso(self.blocked_at),
            'lifted_at': iso(self.lifted_at),
            'lifted_by': self.lifter.full_name if self.lifter else None,
            'lift_reason': self.lift_reason,
        }


def snapshot(txn):
    return {'txn_ref': txn.txn_ref, 'amount': money(txn.amount), 'payment_method': txn.payment_method,
            'sender': txn.sender_account.user.full_name, 'sender_upi': txn.sender_account.upi_id,
            'txn_time': iso(txn.txn_time), 'is_simulated': txn.is_simulated}
