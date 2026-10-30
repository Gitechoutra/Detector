from flask import Blueprint

bp = Blueprint('transactions', __name__, url_prefix='/api/transactions')

from . import routes  # noqa: E402,F401  (registers the views on bp)
