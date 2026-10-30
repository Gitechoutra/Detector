from portal.extensions import db
from portal.models.utils import now, money, iso, DT3


class Alert(db.Model):
    __tablename__ = 'alerts'
    __table_args__ = (db.Index('ix_alert_status_time', 'status', 'created_at'),)
    id = db.Column(db.BigInteger, primary_key=True)
    transaction_id = db.Column(db.BigInteger, db.ForeignKey('transactions.id', ondelete='CASCADE'), index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    alert_type = db.Column(db.String(25), nullable=False)
    severity = db.Column(db.String(10), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    message = db.Column(db.Text, nullable=False)
    risk_score = db.Column(db.Integer)
    status = db.Column(db.String(15), nullable=False, default='OPEN')
    resolution = db.Column(db.String(20))
    assigned_to = db.Column(db.Integer, db.ForeignKey('users.id'))
    analyst_notes = db.Column(db.Text)
    is_simulated = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(DT3, nullable=False, default=now, index=True)
    updated_at = db.Column(DT3, nullable=False, default=now, onupdate=now)
    resolved_at = db.Column(DT3)

    user = db.relationship('User', foreign_keys=[user_id], lazy='joined')
    assignee = db.relationship('User', foreign_keys=[assigned_to], lazy='joined')
    transaction = db.relationship('Transaction', lazy='joined')

    def to_dict(self):
        txn = self.transaction
        return {
            'id': self.id,
            'transaction_id': self.transaction_id,
            'txn_ref': txn.txn_ref if txn else None,
            'txn_status': txn.status if txn else None,
            'amount': money(txn.amount) if txn else None,
            'rules': [h.rule_code for h in txn.latest_hits()] if txn else [],
            'user': self.user.full_name if self.user else None,
            'user_id': self.user_id,
            'alert_type': self.alert_type,
            'severity': self.severity,
            'title': self.title,
            'message': self.message,
            'risk_score': self.risk_score,
            'status': self.status,
            'resolution': self.resolution,
            'assigned_to': self.assignee.full_name if self.assignee else None,
            'analyst_notes': self.analyst_notes,
            'is_simulated': self.is_simulated,
            'created_at': iso(self.created_at),
            'resolved_at': iso(self.resolved_at),
        }
