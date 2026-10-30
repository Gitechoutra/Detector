from portal.extensions import db
from portal.models.utils import now, money, iso, DT3


class RiskAssessment(db.Model):
    __tablename__ = 'risk_assessments'
    id = db.Column(db.BigInteger, primary_key=True)
    transaction_id = db.Column(db.BigInteger, db.ForeignKey('transactions.id', ondelete='CASCADE'),
                               nullable=False, index=True)
    assessment_type = db.Column(db.String(20), nullable=False)
    risk_score = db.Column(db.Integer, nullable=False)
    decision = db.Column(db.String(10), nullable=False)
    rules_evaluated = db.Column(db.Integer, nullable=False)
    rules_triggered = db.Column(db.Integer, nullable=False)
    mitigations = db.Column(db.JSON)
    rule_trace = db.Column(db.JSON)
    latency_ms = db.Column(db.Numeric(10, 2))
    assessed_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    notes = db.Column(db.String(255))
    created_at = db.Column(DT3, nullable=False, default=now)

    def to_dict(self):
        return {
            'id': self.id,
            'assessment_type': self.assessment_type,
            'risk_score': self.risk_score,
            'decision': self.decision,
            'rules_evaluated': self.rules_evaluated,
            'rules_triggered': self.rules_triggered,
            'mitigations': self.mitigations or [],
            'rule_trace': self.rule_trace or [],
            'latency_ms': money(self.latency_ms),
            'notes': self.notes,
            'created_at': iso(self.created_at),
        }
