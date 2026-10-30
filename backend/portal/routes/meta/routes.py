from flask import current_app
from sqlalchemy import text

from portal.extensions import db
from portal.models import Location, RiskCategory
from portal.helpers.responses import error, ok
from . import bp



@bp.get('/health')
def health():
    try:
        db.session.execute(text('SELECT 1'))
    except Exception:
        return error('Database unavailable.', 503, 'DB_DOWN')
    return ok({'status': 'ok', 'demo_mode': current_app.config['DEMO_MODE_ENABLED']})


@bp.get('/meta/locations')
def locations():
    return ok([l.to_dict() for l in Location.query.order_by(Location.city).all()])


@bp.get('/meta/risk-categories')
def risk_categories():
    return ok([c.to_dict() for c in RiskCategory.query.order_by(RiskCategory.min_score).all()])
