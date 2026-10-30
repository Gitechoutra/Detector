from flask import Blueprint

bp = Blueprint('detection', __name__, url_prefix='/api/detection')

from . import routes  # noqa: E402,F401  (registers the views on bp)
