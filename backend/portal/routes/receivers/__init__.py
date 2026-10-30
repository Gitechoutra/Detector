from flask import Blueprint

bp = Blueprint('receiver', __name__, url_prefix='/api/receiver')

from . import routes  # noqa: E402,F401  (registers the views on bp)
