from flask import Blueprint

bp = Blueprint('meta', __name__, url_prefix='/api')

from . import routes  # noqa: E402,F401  (registers the views on bp)
