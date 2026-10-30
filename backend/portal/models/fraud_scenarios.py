from portal.extensions import db


class FraudScenario(db.Model):
    __tablename__ = 'fraud_scenarios'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    victim_email = db.Column(db.String(120), nullable=False)
    expected_rules = db.Column(db.JSON, nullable=False)
    expected_decision = db.Column(db.String(10), nullable=False)
    is_fraud = db.Column(db.Boolean, nullable=False, default=True)
    display_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    def to_dict(self):
        return {'id': self.id, 'code': self.code, 'name': self.name, 'description': self.description,
                'expected_rules': self.expected_rules, 'expected_decision': self.expected_decision,
                'is_fraud': self.is_fraud}
