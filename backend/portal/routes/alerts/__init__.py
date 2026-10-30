from flask import Blueprint

bp = Blueprint('alerts', __name__, url_prefix='/api/alerts')

from . import routes  # noqa: E402,F401  (registers the views on bp)
