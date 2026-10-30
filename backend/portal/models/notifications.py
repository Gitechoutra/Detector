from portal.extensions import db
from portal.models.utils import now, iso, DT3


class Notification(db.Model):
    __tablename__ = 'notifications'
    __table_args__ = (db.Index('ix_notif_user_read', 'user_id', 'is_read', 'created_at'),)
    id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    message = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(10), nullable=False, default='INFO')
    transaction_id = db.Column(db.BigInteger, db.ForeignKey('transactions.id', ondelete='SET NULL'))
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    is_simulated = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(DT3, nullable=False, default=now)

    def to_dict(self):
        return {'id': self.id, 'title': self.title, 'message': self.message, 'category': self.category,
                'transaction_id': self.transaction_id, 'is_read': self.is_read,
                'created_at': iso(self.created_at)}
