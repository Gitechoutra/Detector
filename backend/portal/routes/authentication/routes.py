from datetime import datetime

from flask import g
from flask_jwt_extended import get_jwt

from portal.helpers import auth
from portal.helpers.audit import write_audit
from portal.extensions import db
from portal.helpers.responses import ApiError, ok
from portal.helpers.security import client_ip, role_required
from portal.helpers.validators import json_body, require_str
from portal.models import RevokedToken, now
from . import bp


@bp.post('/register')
def register():
    """Public sign-up for customers (one User account sends and receives), followed by a normal login
    so the new device and location are recorded like any other sign-in."""
    try:
        data = json_body()
        full_name = require_str(data, 'full_name', 100, 'Full name')
        email = require_str(data, 'email', 120, 'Email')
        phone = require_str(data, 'phone', 20, 'Mobile number', required=False)
        password = require_str(data, 'password', 128, 'Password')
        fingerprint = require_str(data, 'device_id', 64, 'Device ID')
        device_name = require_str(data, 'device_name', 150, required=False)
        role = (data.get('role') or '').upper()
        user = auth.register(full_name, email, phone, password, role, data.get('location_id'), client_ip())
        result = auth.login(user.email, password, fingerprint, device_name, client_ip())
    except ApiError as e:
        return e.response()
    result['account'] = user.primary_account.to_dict()
    return ok(result, 'Account created.', 201)


@bp.post('/login')
def login():
    try:
        data = json_body()
        email = require_str(data, 'email', 120, 'Email')
        password = require_str(data, 'password', 128, 'Password')
        fingerprint = require_str(data, 'device_id', 64, 'Device ID')
        device_name = require_str(data, 'device_name', 150, required=False)
        result = auth.login(email, password, fingerprint, device_name, client_ip(),
                                    data.get('location_id'))
    except ApiError as e:
        return e.response()
    return ok(result, 'Logged in successfully.')


@bp.get('/me')
@role_required()
def me():
    return ok({'user': g.current_user.to_dict(), 'dashboard': auth.DASHBOARDS[g.current_user.role_code]})


@bp.post('/logout')
@role_required()
def logout():
    """Ends this session: the token is revoked, so it no longer works even before it expires."""
    claims = get_jwt()
    RevokedToken.query.filter(RevokedToken.expires_at < now()).delete(synchronize_session=False)
    if db.session.get(RevokedToken, claims['jti']) is None:
        db.session.add(RevokedToken(jti=claims['jti'], user_id=g.current_user.id,
                                    expires_at=datetime.fromtimestamp(claims['exp'])))
    write_audit('LOGOUT', 'user', g.current_user.id, {}, actor=g.current_user, ip=client_ip())
    db.session.commit()
    return ok(message='Logged out.')
