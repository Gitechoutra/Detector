from portal.extensions import db
from portal.models.utils import now, iso


class FraudRule(db.Model):
    __tablename__ = 'fraud_rules'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(5), unique=True, nullable=False)
    name = db.Column(db.String(80), nullable=False)
    description = db.Column(db.Text, nullable=False)
    sql_technique = db.Column(db.String(150), nullable=False)
    weight = db.Column(db.Integer, nullable=False)
    params = db.Column(db.JSON, nullable=False)
    default_weight = db.Column(db.Integer, nullable=False)
    default_params = db.Column(db.JSON, nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    updated_at = db.Column(db.DateTime, nullable=False, default=now, onupdate=now)
    created_at = db.Column(db.DateTime, nullable=False, default=now)

    def to_dict(self):
        return {
            'id': self.id,
            'code': self.code,
            'name': self.name,
            'description': self.description,
            'sql_technique': self.sql_technique,
            'weight': self.weight,
            'params': self.params,
            'default_weight': self.default_weight,
            'default_params': self.default_params,
            'is_active': self.is_active,
            'updated_at': iso(self.updated_at),
        }
