from flask import Blueprint

bp = Blueprint('user', __name__, url_prefix='/api/user')

from . import routes  # noqa: E402,F401  (registers the views on bp)
