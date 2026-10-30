from portal.extensions import db


class RiskCategory(db.Model):
    __tablename__ = 'risk_categories'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), unique=True, nullable=False)
    label = db.Column(db.String(30), nullable=False)
    min_score = db.Column(db.Integer, nullable=False)
    max_score = db.Column(db.Integer, nullable=False)
    action = db.Column(db.String(255), nullable=False)
    color = db.Column(db.String(10), nullable=False)

    def to_dict(self):
        return {'id': self.id, 'code': self.code, 'label': self.label, 'min_score': self.min_score,
                'max_score': self.max_score, 'action': self.action, 'color': self.color}
