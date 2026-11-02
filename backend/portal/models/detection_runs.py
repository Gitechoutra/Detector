from portal.extensions import db
from portal.models.utils import now, iso, DT3


class DetectionRun(db.Model):
    """One run of the Detection Engine: the nine rules replayed over stored
    transactions. The scanned transactions themselves are never changed."""
    __tablename__ = 'detection_runs'
    id = db.Column(db.Integer, primary_key=True)
    run_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    scope = db.Column(db.JSON)                 # filters used: account, days, include_simulated
    txns_scanned = db.Column(db.Integer, nullable=False, default=0)
    txns_flagged = db.Column(db.Integer, nullable=False, default=0)
    summary = db.Column(db.JSON)               # counts per band, per rule, per account
    results = db.Column(db.JSON)               # one entry per scanned transaction
    duration_ms = db.Column(db.Numeric(10, 2))
    created_at = db.Column(DT3, nullable=False, default=now, index=True)

    runner = db.relationship('User', lazy='joined')

    def to_dict(self, with_results=False):
        data = {
            'id': self.id,
            'run_by': self.runner.full_name if self.runner else None,
            'scope': self.scope,
            'txns_scanned': self.txns_scanned,
            'txns_flagged': self.txns_flagged,
            'summary': self.summary,
            'duration_ms': float(self.duration_ms) if self.duration_ms is not None else None,
            'created_at': iso(self.created_at),
        }
        if with_results:
            data['results'] = self.results or []
        return data
