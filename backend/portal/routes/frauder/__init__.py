from flask import Blueprint

bp = Blueprint('frauder', __name__, url_prefix='/api/frauder')

from . import routes  # noqa: E402,F401  (registers the views on bp)
