from portal.extensions import db
from portal.models.utils import now, iso


class WatchlistEntry(db.Model):
    __tablename__ = 'watchlist'
    __table_args__ = (db.UniqueConstraint('entity_type', 'entity_value', name='uq_watchlist_entity'),)
    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(15), nullable=False)
    entity_value = db.Column(db.String(120), nullable=False)
    reason = db.Column(db.String(255), nullable=False)
    source = db.Column(db.String(10), nullable=False, default='MANUAL')
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    added_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, nullable=False, default=now)

    def to_dict(self):
        return {'id': self.id, 'entity_type': self.entity_type, 'entity_value': self.entity_value,
                'reason': self.reason, 'source': self.source, 'is_active': self.is_active,
                'created_at': iso(self.created_at)}
