from portal.extensions import db
from portal.models.utils import now


class Role(db.Model):
    __tablename__ = 'roles'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(50), nullable=False)
    description = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, nullable=False, default=now)
