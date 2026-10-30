from functools import wraps

from flask import current_app, g, request
from flask_jwt_extended import get_jwt, get_jwt_identity, verify_jwt_in_request

from portal.extensions import db
from portal.models import User
from portal.helpers.responses import ApiError, error

USER, RECEIVER, DETECTION, FRAUDER = 'USER', 'RECEIVER', 'DETECTION', 'FRAUDER'


def role_required(*roles):
    """JWT-protect a view and restrict it to the given role codes.
    The role is re-read from the database so a stale token cannot keep old rights."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()
            user = db.session.get(User, int(get_jwt_identity()))
            if user is None or user.status == 'SUSPENDED':
                return error('Your account is not available.', 401, 'ACCOUNT_UNAVAILABLE')
            if roles and user.role_code not in roles:
                return error('You do not have permission to access this.', 403, 'FORBIDDEN')
            g.current_user = user
            g.device_id = get_jwt().get('device_id')
            try:
                return fn(*args, **kwargs)
            except ApiError as e:
                db.session.rollback()
                return e.response()
        return wrapper
    return decorator


def demo_mode_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_app.config.get('DEMO_MODE_ENABLED'):
            return error('Demo Mode is disabled on this server.', 403, 'DEMO_DISABLED')
        try:
            return fn(*args, **kwargs)
        except ApiError as e:
            db.session.rollback()
            return e.response()
    return wrapper


def client_ip():
    forwarded = request.headers.get('X-Forwarded-For', '')
    return (forwarded.split(',')[0].strip() if forwarded else request.remote_addr) or '0.0.0.0'
