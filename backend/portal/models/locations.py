from portal.extensions import db


class Location(db.Model):
    __tablename__ = 'locations'
    id = db.Column(db.Integer, primary_key=True)
    city = db.Column(db.String(60), unique=True, nullable=False)
    state = db.Column(db.String(60), nullable=False)
    latitude = db.Column(db.Numeric(9, 6), nullable=False)
    longitude = db.Column(db.Numeric(9, 6), nullable=False)

    def to_dict(self):
        return {'id': self.id, 'city': self.city, 'state': self.state}
