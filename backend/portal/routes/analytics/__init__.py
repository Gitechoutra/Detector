from flask import Blueprint

bp = Blueprint('analytics', __name__, url_prefix='/api/analytics')

from . import routes  # noqa: E402,F401  (registers the views on bp)
