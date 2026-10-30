from portal.extensions import db
from portal.models.utils import now, iso


class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'), nullable=False, index=True)
    full_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20))
    password_hash = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='ACTIVE')
    home_location_id = db.Column(db.Integer, db.ForeignKey('locations.id'))
    failed_login_count = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime)
    is_demo = db.Column(db.Boolean, nullable=False, default=False)
    is_simulated = db.Column(db.Boolean, nullable=False, default=False)
    last_login_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=now)
    updated_at = db.Column(db.DateTime, nullable=False, default=now, onupdate=now)

    role = db.relationship('Role', lazy='joined')
    home_location = db.relationship('Location', lazy='joined')
    accounts = db.relationship('Account', back_populates='user', lazy='selectin')

    @property
    def role_code(self):
        return self.role.code

    @property
    def primary_account(self):
        return self.accounts[0] if self.accounts else None

    def to_dict(self):
        return {
            'id': self.id,
            'full_name': self.full_name,
            'email': self.email,
            'phone': self.phone,
            'role': self.role.code,
            'role_name': self.role.name,
            'status': self.status,
            'home_city': self.home_location.city if self.home_location else None,
            'home_location_id': self.home_location_id,
            'is_simulated': self.is_simulated,
            'last_login_at': iso(self.last_login_at),
        }
