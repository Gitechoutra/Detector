from flask import request

from portal.helpers import analytics
from portal.helpers.responses import ok
from portal.helpers.security import DETECTION, role_required
from portal.helpers.validators import date_range_args
from . import bp



@bp.get('/summary')
@role_required(DETECTION)
def summary():
    start, end = date_range_args()
    return ok(analytics.summary(start, end, request.args.get('source')))
