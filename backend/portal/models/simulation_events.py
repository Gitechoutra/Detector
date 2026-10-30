from portal.extensions import db
from portal.models.utils import now, money, iso, DT3


class SimulationEvent(db.Model):
    __tablename__ = 'simulation_events'
    id = db.Column(db.BigInteger, primary_key=True)
    run_id = db.Column(db.Integer, db.ForeignKey('simulation_runs.id', ondelete='CASCADE'), nullable=False, index=True)
    scenario_id = db.Column(db.Integer, db.ForeignKey('fraud_scenarios.id'), nullable=False)
    transaction_id = db.Column(db.BigInteger, db.ForeignKey('transactions.id', ondelete='SET NULL'))
    detected = db.Column(db.Boolean, nullable=False)
    risk_score = db.Column(db.Integer)
    decision = db.Column(db.String(10), nullable=False)
    triggered_rules = db.Column(db.JSON, nullable=False)
    expected_rules = db.Column(db.JSON, nullable=False)
    steps = db.Column(db.JSON, nullable=False)
    attempt_ids = db.Column(db.JSON)
    created_at = db.Column(DT3, nullable=False, default=now)

    scenario = db.relationship('FraudScenario', lazy='joined')
    transaction = db.relationship('Transaction', lazy='joined')

    def attempts(self):
        """Every payment the scenario attempted, with its *current* status: a
        held payment may since have been verified, approved or rejected."""
        from portal.models.transactions import Transaction
        ids = self.attempt_ids or []
        rows = {t.id: t for t in Transaction.query.filter(Transaction.id.in_(ids)).all()} if ids else {}
        return [rows[i] for i in ids if i in rows]

    def to_dict(self):
        attempts = self.attempts()
        final = self.transaction
        return {
            'id': self.id,
            'run_id': self.run_id,
            'scenario_code': self.scenario.code,
            'scenario_name': self.scenario.name,
            'is_fraud': self.scenario.is_fraud,
            'transaction_id': self.transaction_id,
            'txn_ref': final.txn_ref if final else None,
            'amount': money(final.amount) if final else None,
            'sender': final.sender_account.user.full_name if final else None,
            'receiver': final.receiver_account.user.full_name if final else None,
            'status': final.status if final else None,
            'explanation': final.risk_explanation if final else None,
            'detected': self.detected,
            'risk_score': self.risk_score,
            'decision': self.decision,
            'triggered_rules': self.triggered_rules,
            'expected_rules': self.expected_rules,
            'steps': self.steps,
            'attempts': [{
                'transaction_id': t.id, 'txn_ref': t.txn_ref, 'sender': t.sender_account.user.full_name,
                'receiver': t.receiver_account.user.full_name, 'amount': money(t.amount),
                'decision': t.decision, 'status': t.status, 'risk_score': t.risk_score,
                'rules': [h.rule_code for h in t.latest_hits()], 'money_moved': t.status == 'COMPLETED',
            } for t in attempts],
            'money_transferred': sum(money(t.amount) for t in attempts if t.status == 'COMPLETED'),
            'money_prevented': sum(money(t.amount) for t in attempts if t.status in ('BLOCKED', 'DECLINED', 'CANCELLED')),
            'money_pending': sum(money(t.amount) for t in attempts if t.status == 'UNDER_REVIEW'),
            'created_at': iso(self.created_at),
        }
