from portal.extensions import db
from portal.models.utils import now, money, iso, DT3


class Transaction(db.Model):
    __tablename__ = 'transactions'
    __table_args__ = (
        db.UniqueConstraint('sender_account_id', 'idempotency_key', name='uq_txn_idempotency'),
        db.Index('ix_txn_sender_time', 'sender_account_id', 'txn_time'),
        db.Index('ix_txn_receiver_time', 'receiver_account_id', 'txn_time'),
        db.Index('ix_txn_status', 'status'),
        db.Index('ix_txn_time', 'txn_time'),
        db.Index('ix_txn_confirmation', 'confirmation_status', 'confirmation_expires_at'),
    )
    id = db.Column(db.BigInteger, primary_key=True)
    txn_ref = db.Column(db.String(24), unique=True, nullable=False)
    idempotency_key = db.Column(db.String(64))
    sender_account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=False)
    receiver_account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=False)
    amount = db.Column(db.Numeric(15, 2), nullable=False)
    payment_method = db.Column(db.String(15), nullable=False)
    remarks = db.Column(db.String(140))
    status = db.Column(db.String(15), nullable=False, default='PROCESSING')
    review_stage = db.Column(db.String(20))
    risk_score = db.Column(db.Integer)
    decision = db.Column(db.String(10))
    decline_reason = db.Column(db.String(500))
    risk_explanation = db.Column(db.String(500))
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'))
    ip_address = db.Column(db.String(45))
    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'))
    step_up_verified = db.Column(db.Boolean, nullable=False, default=False)
    is_simulated = db.Column(db.Boolean, nullable=False, default=False)
    simulation_run_id = db.Column(db.Integer, db.ForeignKey('simulation_runs.id'))
    scenario_code = db.Column(db.String(40))
    is_fraud_label = db.Column(db.Boolean)
    txn_time = db.Column(DT3, nullable=False)
    decided_at = db.Column(DT3)
    completed_at = db.Column(DT3)
    latency_ms = db.Column(db.Numeric(10, 2))
    # The account owner's answer to "Was this transaction initiated by you?".
    confirmation_status = db.Column(db.String(12))      # PENDING / CONFIRMED / DENIED / EXPIRED / CLOSED
    confirmation_response = db.Column(db.String(3))     # YES / NO
    confirmation_responded_at = db.Column(DT3)
    confirmation_expires_at = db.Column(DT3)
    final_reason = db.Column(db.String(500))
    # Attacker-supplied values typed into the Frauder console. SIMULATED, never verified.
    simulated_details = db.Column(db.JSON)
    created_at = db.Column(DT3, nullable=False, default=now)

    sender_account = db.relationship('Account', foreign_keys=[sender_account_id], lazy='joined')
    receiver_account = db.relationship('Account', foreign_keys=[receiver_account_id], lazy='joined')
    device = db.relationship('Device', lazy='joined')
    location = db.relationship('Location', lazy='joined')
    triggered_rules = db.relationship('TriggeredRule', lazy='selectin',
                                      order_by='TriggeredRule.id', viewonly=True)

    def latest_hits(self):
        """Rule hits from the most recent assessment only."""
        if not self.triggered_rules:
            return []
        last = max(h.assessment_id for h in self.triggered_rules)
        return [h for h in self.triggered_rules if h.assessment_id == last]

    def confirmation_dict(self):
        if self.confirmation_status is None:
            return None
        return {'status': self.confirmation_status, 'response': self.confirmation_response,
                'responded_at': iso(self.confirmation_responded_at),
                'expires_at': iso(self.confirmation_expires_at)}

    def outcome_label(self):
        """One label shared by the User, Receiver, Frauder and Detection screens."""
        response, status = self.confirmation_response, self.status
        if status == 'COMPLETED':
            return 'USER AUTHORIZED – PAYMENT SUCCESSFUL' if response == 'YES' else 'SUCCESSFUL'
        if status == 'BLOCKED':
            if response == 'NO':
                return 'USER DENIED – PAYMENT BLOCKED'
            if self.confirmation_status == 'EXPIRED':
                return 'NO RESPONSE – BLOCKED'
            if response == 'YES':
                return 'USER AUTHORIZED – STILL BLOCKED'
            return 'BLOCKED'
        if status == 'EXPIRED':
            return 'EXPIRED – NOT AUTHORIZED'
        if status == 'UNDER_REVIEW':
            if self.review_stage == 'AWAITING_ANALYST':
                return 'WITH FRAUD TEAM'
            return 'USER AUTHORIZED – VERIFYING' if response == 'YES' else 'USER CONFIRMATION PENDING'
        return status

    def display_status(self):
        """The status names shown to people. COMPLETED / UNDER_REVIEW stay the stored values."""
        if self.status == 'COMPLETED':
            return 'SUCCESSFUL'
        if self.status == 'UNDER_REVIEW' and self.confirmation_status == 'PENDING':
            return 'USER_CONFIRMATION_PENDING'
        return self.status

    def to_dict(self, view='detection'):
        data = {
            'id': self.id,
            'txn_ref': self.txn_ref,
            'amount': money(self.amount),
            'payment_method': self.payment_method,
            'remarks': self.remarks,
            'status': self.status,
            'review_stage': self.review_stage,
            'risk_score': self.risk_score,
            'decision': self.decision,
            'decline_reason': self.decline_reason,
            'risk_explanation': self.risk_explanation,
            'money_moved': self.status == 'COMPLETED',
            'is_simulated': self.is_simulated,
            'step_up_verified': self.step_up_verified,
            'txn_time': iso(self.txn_time),
            'completed_at': iso(self.completed_at),
            'final_reason': self.final_reason,
            'outcome_label': self.outcome_label(),
            'display_status': self.display_status(),
            'confirmation': self.confirmation_dict(),
            'city': self.location.city if self.location else None,
            'sender': self.sender_account.counterparty_dict(),
            'receiver': self.receiver_account.counterparty_dict(),
        }
        hits = self.latest_hits()
        if view == 'detection':
            data.update({
                'sender_user_id': self.sender_account.user_id,
                'device': self.device.to_dict() if self.device else None,
                'ip_address': self.ip_address,
                'scenario_code': self.scenario_code,
                'simulated_details': self.simulated_details,
                'latency_ms': money(self.latency_ms),
                'rules': [h.to_dict() for h in hits],
            })
        else:
            # Customers see which checks flagged the payment, not the weights/evidence.
            data['rules'] = [{'code': h.rule_code, 'name': h.rule.name, 'reason': h.reason} for h in hits]
        return data
