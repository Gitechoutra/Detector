from portal.extensions import db
from portal.models.utils import now, DT3


class TriggeredRule(db.Model):
    __tablename__ = 'triggered_rules'
    __table_args__ = (db.Index('ix_hit_rule_time', 'rule_id', 'created_at'),)
    id = db.Column(db.BigInteger, primary_key=True)
    transaction_id = db.Column(db.BigInteger, db.ForeignKey('transactions.id', ondelete='CASCADE'),
                               nullable=False, index=True)
    assessment_id = db.Column(db.BigInteger, db.ForeignKey('risk_assessments.id', ondelete='CASCADE'),
                              nullable=False)
    rule_id = db.Column(db.Integer, db.ForeignKey('fraud_rules.id'), nullable=False)
    rule_code = db.Column(db.String(5), nullable=False)
    weight_applied = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(255), nullable=False)
    evidence = db.Column(db.JSON)
    created_at = db.Column(DT3, nullable=False, default=now)

    rule = db.relationship('FraudRule', lazy='joined')

    def to_dict(self):
        return {
            'code': self.rule_code,
            'name': self.rule.name,
            'weight': self.weight_applied,
            'reason': self.reason,
            'evidence': self.evidence,
        }
