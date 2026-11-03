from portal.extensions import db
from portal.models.utils import now, iso, DT3

# Case statuses. The first two are open (the account stays restricted); the rest are final.
OPEN_STATUSES = ('TEMPORARILY_BLOCKED', 'UNDER_INVESTIGATION')
FINAL_STATUSES = ('PERMANENTLY_BLOCKED', 'APPROVED', 'RESOLVED')
CASE_TYPES = {
    'HIGH_RISK_PAYMENT': 'High-risk payment – sender restricted',
    'RECEIVER_REPORTED': 'Receiver of a payment the account owner denied',
}


def mask_account(number):
    return f'•••• {number[-4:]}' if number else None


class InvestigationCase(db.Model):
    """A fraud investigation opened automatically when the engine restricts an
    account. One case per (account, fraud event); a detective closes it by
    approving the account or blocking it permanently."""
    __tablename__ = 'investigation_cases'
    __table_args__ = (db.UniqueConstraint('account_id', 'transaction_id', 'case_type', name='uq_case_event'),
                      db.Index('ix_case_status_opened', 'status', 'opened_at'))
    id = db.Column(db.Integer, primary_key=True)
    case_ref = db.Column(db.String(20), unique=True, nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=False, index=True)
    transaction_id = db.Column(db.BigInteger, db.ForeignKey('transactions.id', ondelete='SET NULL'))
    case_type = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='TEMPORARILY_BLOCKED')
    detection_reason = db.Column(db.String(500), nullable=False)
    risk_score = db.Column(db.Integer)
    risk_factors = db.Column(db.JSON)            # [{code, name, weight, reason}]
    transaction_snapshot = db.Column(db.JSON)    # kept even if the transaction row is later removed
    account_status_at_open = db.Column(db.String(20))
    assigned_to = db.Column(db.Integer, db.ForeignKey('users.id'))
    decision = db.Column(db.String(20))           # PERMANENT_BLOCK / APPROVE
    decision_reason = db.Column(db.String(500))
    decided_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    opened_at = db.Column(DT3, nullable=False, default=now)
    review_started_at = db.Column(DT3)
    decided_at = db.Column(DT3)

    account = db.relationship('Account', lazy='joined')
    transaction = db.relationship('Transaction', lazy='joined')
    assignee = db.relationship('User', foreign_keys=[assigned_to], lazy='joined')
    decider = db.relationship('User', foreign_keys=[decided_by], lazy='joined')

    @property
    def is_open(self):
        return self.status in OPEN_STATUSES

    def to_dict(self):
        snap = self.transaction_snapshot or {}
        return {
            'id': self.id, 'case_ref': self.case_ref, 'case_type': self.case_type,
            'case_type_label': CASE_TYPES.get(self.case_type, self.case_type),
            'status': self.status, 'is_open': self.is_open,
            'account': {'id': self.account_id, 'masked_number': mask_account(self.account.account_number),
                        'upi_id': self.account.upi_id, 'status': self.account.status},
            'customer': {'id': self.account.user_id, 'name': self.account.user.full_name},
            'transaction': {'id': self.transaction_id, 'txn_ref': snap.get('txn_ref'), 'amount': snap.get('amount'),
                            'txn_time': snap.get('txn_time'), 'payment_method': snap.get('payment_method'),
                            'sender': snap.get('sender'), 'receiver': snap.get('receiver'),
                            'status': self.transaction.status if self.transaction else None},
            'detection_reason': self.detection_reason, 'risk_score': self.risk_score,
            'risk_factors': self.risk_factors or [],
            'account_status_at_open': self.account_status_at_open,
            'assigned_to': self.assignee.full_name if self.assignee else None,
            'decision': self.decision, 'decision_reason': self.decision_reason,
            'decided_by': self.decider.full_name if self.decider else None,
            'opened_at': iso(self.opened_at), 'review_started_at': iso(self.review_started_at),
            'decided_at': iso(self.decided_at),
        }


class InvestigationAction(db.Model):
    """Append-only history of every action on a case. Database triggers reject
    UPDATE and DELETE (see migration 0013), so a decision can never change silently."""
    __tablename__ = 'investigation_actions'
    id = db.Column(db.BigInteger, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey('investigation_cases.id'), nullable=False, index=True)
    detective_id = db.Column(db.Integer, db.ForeignKey('users.id'))       # NULL = done by the system
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=False)
    action = db.Column(db.String(30), nullable=False)
    previous_case_status = db.Column(db.String(20))
    new_case_status = db.Column(db.String(20), nullable=False)
    previous_account_status = db.Column(db.String(20))
    new_account_status = db.Column(db.String(20))
    reason = db.Column(db.String(500))
    created_at = db.Column(DT3, nullable=False, default=now)

    detective = db.relationship('User', lazy='joined')
    case = db.relationship('InvestigationCase', lazy='joined')

    def to_dict(self):
        return {
            'id': self.id, 'case_id': self.case_id, 'case_ref': self.case.case_ref if self.case else None,
            'detective_id': self.detective_id,
            'detective': self.detective.full_name if self.detective else 'System',
            'account_id': self.account_id, 'action': self.action,
            'previous_case_status': self.previous_case_status, 'new_case_status': self.new_case_status,
            'previous_account_status': self.previous_account_status, 'new_account_status': self.new_account_status,
            'reason': self.reason, 'created_at': iso(self.created_at),
        }
