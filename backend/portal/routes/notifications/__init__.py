from flask import Blueprint

bp = Blueprint('notifications', __name__, url_prefix='/api/notifications')

from . import routes  # noqa: E402,F401  (registers the views on bp)
