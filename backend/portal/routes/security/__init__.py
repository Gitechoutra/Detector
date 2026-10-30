from flask import Blueprint

bp = Blueprint('security', __name__, url_prefix='/api/security')

from . import routes  # noqa: E402,F401  (registers the views on bp)
