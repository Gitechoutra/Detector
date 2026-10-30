from portal.extensions import db
from portal.models.utils import now, iso


class SimulationRun(db.Model):
    __tablename__ = 'simulation_runs'
    id = db.Column(db.Integer, primary_key=True)
    started_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    mode = db.Column(db.String(10), nullable=False)
    status = db.Column(db.String(12), nullable=False, default='RUNNING')
    interval_seconds = db.Column(db.Integer)
    scenarios_executed = db.Column(db.Integer, nullable=False, default=0)
    started_at = db.Column(db.DateTime, nullable=False, default=now)
    ended_at = db.Column(db.DateTime)
    request_key = db.Column(db.String(64), unique=True)

    def to_dict(self):
        return {'id': self.id, 'mode': self.mode, 'status': self.status,
                'interval_seconds': self.interval_seconds, 'scenarios_executed': self.scenarios_executed,
                'started_at': iso(self.started_at), 'ended_at': iso(self.ended_at)}
