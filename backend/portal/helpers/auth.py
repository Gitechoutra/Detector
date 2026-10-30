import re
import secrets
from datetime import timedelta
from decimal import Decimal

from flask_jwt_extended import create_access_token
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash

from portal.extensions import db
from portal.models import Account, Device, Location, LoginAttempt, Role, User, now
from portal.helpers.audit import write_audit
from portal.helpers.responses import ApiError
from portal.helpers.helpers import notify, raise_alert, security_event, setting

DASHBOARDS = {'USER': '/user', 'RECEIVER': '/receiver', 'DETECTION': '/detection', 'FRAUDER': '/frauder'}


def resolve_location_id(location_id, user):
    if location_id:
        if db.session.get(Location, int(location_id)):
            return int(location_id)
        raise ApiError('Unknown location.', 422, 'VALIDATION_ERROR', {'field': 'location_id'})
    return user.home_location_id if user else None


def upsert_device(user, fingerprint, device_name, ip, location_id, at=None, trust_first=True):
    """Returns (device, is_new). A customer's first device is trusted: it is the
    device they enrolled with. Every later new device starts untrusted. The
    Frauder console passes trust_first=False so an attacker's device is never trusted,
    even on an account that has no devices yet."""
    at = at or now()
    device = Device.query.filter_by(user_id=user.id, fingerprint=fingerprint).first()
    if device:
        device.last_seen_at, device.last_ip, device.last_location_id = at, ip, location_id
        if device_name:
            device.device_name = device_name[:150]
        return device, False
    has_trusted = db.session.query(Device.id).filter_by(user_id=user.id, is_trusted=True).first() is not None
    trusted = trust_first and not has_trusted
    device = Device(user_id=user.id, fingerprint=fingerprint, device_name=(device_name or 'Unknown device')[:150],
                    is_trusted=trusted, first_seen_at=at, last_seen_at=at, last_ip=ip,
                    last_location_id=location_id)
    db.session.add(device)
    db.session.flush()
    return device, not trusted


def _clear_expired_lock(user, at):
    if user.status == 'LOCKED' and user.locked_until and user.locked_until <= at:
        user.status, user.locked_until, user.failed_login_count = 'ACTIVE', None, 0


def register_attempt(user, email, success, fingerprint, device_name, ip, location_id,
                     failure_reason=None, simulated=False, at=None, trust_first=True):
    """Records one login attempt and every security consequence of it.
    Shared by the real login endpoint and the Frauder console."""
    at = at or now()
    attempt = LoginAttempt(user_id=user.id if user else None, email=email, success=success,
                           failure_reason=failure_reason, fingerprint=fingerprint, ip_address=ip,
                           location_id=location_id, is_simulated=simulated, created_at=at)
    if user is None:
        db.session.add(attempt)
        return None

    if not success:
        user.failed_login_count += 1
        max_fail = setting('LOGIN_MAX_FAILURES')
        db.session.add(attempt)
        security_event(user.id, 'LOGIN_FAILED',
                       f'Failed login ({failure_reason or "bad password"}) from {ip}',
                       'MEDIUM' if user.failed_login_count >= 3 else 'LOW',
                       ip=ip, location_id=location_id, simulated=simulated, at=at)
        if user.failed_login_count >= max_fail and user.status == 'ACTIVE':
            minutes = setting('LOGIN_LOCK_MINUTES')
            user.status, user.locked_until = 'LOCKED', at + timedelta(minutes=minutes)
            security_event(user.id, 'ACCOUNT_LOCKED',
                           f'Locked for {minutes} min after {user.failed_login_count} failed logins',
                           'HIGH', ip=ip, location_id=location_id, simulated=simulated, at=at)
            raise_alert('SECURITY', 'HIGH', f'Account locked: {user.full_name}',
                        f'{user.failed_login_count} consecutive failed logins, last from {ip}. '
                        f'Possible brute-force / unauthorised access attempt.',
                        user_id=user.id, simulated=simulated)
            notify(user.id, 'Account temporarily locked',
                   f'We locked your account for {minutes} minutes after repeated failed logins. '
                   f'If this was not you, your password may be at risk.', 'DANGER', simulated=simulated)
            write_audit('ACCOUNT_LOCKED', 'user', user.id, {'failed_logins': user.failed_login_count,
                                                           'ip': ip, 'simulated': simulated})
        return None

    device, is_new = upsert_device(user, fingerprint, device_name, ip, location_id, at, trust_first)
    attempt.device_id, attempt.is_new_device = device.id, is_new
    db.session.add(attempt)
    prior_failures = user.failed_login_count
    user.failed_login_count, user.last_login_at = 0, at

    unusual_city = None
    if location_id and user.home_location_id and location_id != user.home_location_id:
        unusual_city = db.session.get(Location, location_id).city
        security_event(user.id, 'UNUSUAL_LOCATION_LOGIN', f'Login from {unusual_city}', 'MEDIUM',
                       device_id=device.id, ip=ip, location_id=location_id, simulated=simulated, at=at)
    if is_new:
        security_event(user.id, 'NEW_DEVICE_LOGIN', f'Login from new device "{device.device_name}" ({ip})',
                       'MEDIUM', device_id=device.id, ip=ip, location_id=location_id, simulated=simulated, at=at)
        notify(user.id, 'New device signed in',
               f'Your account was accessed from "{device.device_name}"'
               f'{" in " + unusual_city if unusual_city else ""}. If this was not you, contact the bank.',
               'WARNING', simulated=simulated)
        if prior_failures >= 3 or unusual_city:
            reasons = []
            if prior_failures >= 3:
                reasons.append(f'{prior_failures} failed attempts before success')
            if unusual_city:
                reasons.append(f'location {unusual_city}')
            raise_alert('SECURITY', 'MEDIUM', f'Suspicious login: {user.full_name}',
                        'New-device login with ' + ' and '.join(reasons) + '. Watch for transfers.',
                        user_id=user.id, simulated=simulated)
    else:
        security_event(user.id, 'LOGIN_SUCCESS', f'Login from {device.device_name}', 'LOW',
                       device_id=device.id, ip=ip, location_id=location_id, simulated=simulated, at=at)
    return device


def login(email, password, fingerprint, device_name, ip, location_id=None):
    at = now()
    user = User.query.filter(func.lower(User.email) == email.lower()).first()
    if user is None or user.is_simulated:
        register_attempt(None, email, False, fingerprint, device_name, ip, location_id, 'UNKNOWN_USER')
        db.session.commit()
        raise ApiError('Invalid email or password.', 401, 'INVALID_CREDENTIALS')

    location_id = resolve_location_id(location_id, user)
    _clear_expired_lock(user, at)
    if user.status == 'LOCKED':
        register_attempt(user, email, False, fingerprint, device_name, ip, location_id, 'ACCOUNT_LOCKED')
        db.session.commit()
        raise ApiError(f'Account locked after repeated failed logins. Try again after '
                       f'{user.locked_until:%H:%M}.', 423, 'ACCOUNT_LOCKED')
    if user.status != 'ACTIVE':
        raise ApiError('This account is suspended.', 403, 'ACCOUNT_SUSPENDED')

    if not check_password_hash(user.password_hash, password):
        register_attempt(user, email, False, fingerprint, device_name, ip, location_id, 'BAD_PASSWORD')
        remaining = max(0, setting('LOGIN_MAX_FAILURES') - user.failed_login_count)
        db.session.commit()
        if user.status == 'LOCKED':
            raise ApiError(f'Too many failed attempts. Account locked until {user.locked_until:%H:%M}.',
                           423, 'ACCOUNT_LOCKED')
        raise ApiError(f'Invalid email or password. {remaining} attempt(s) left before the account is locked.',
                       401, 'INVALID_CREDENTIALS')

    device = register_attempt(user, email, True, fingerprint, device_name, ip, location_id)
    write_audit('LOGIN', 'user', user.id, {'device_id': device.id, 'new_device': not device.is_trusted},
                actor=user, ip=ip)
    db.session.commit()

    token = create_access_token(identity=str(user.id), additional_claims={
        'role': user.role_code, 'device_id': device.id, 'location_id': location_id})
    return {'token': token, 'user': user.to_dict(), 'dashboard': DASHBOARDS[user.role_code],
            'device': device.to_dict()}


# ── Self-registration (customers only) ──────────────────────────────────────

# Staff roles (DETECTION, FRAUDER) are never self-service: they are seeded.
SELF_REGISTER_ROLES = ('USER', 'RECEIVER')
BRANCH_IFSC = 'FSBK0000001'
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _check_password(password):
    if len(password) < 8 or not re.search(r'[A-Za-z]', password) or not re.search(r'\d', password):
        raise ApiError('Password must be at least 8 characters and contain letters and numbers.', 422,
                       'VALIDATION_ERROR', {'field': 'password'})


def _unique_account_number():
    while True:
        number = '5010' + f'{secrets.randbelow(10 ** 8):08d}'
        if not Account.query.filter_by(account_number=number).first():
            return number


def _unique_upi(email):
    base = re.sub(r'[^a-z0-9.]', '', email.split('@')[0].lower())[:30] or 'user'
    candidate, n = f'{base}@fsbank', 1
    while Account.query.filter_by(upi_id=candidate).first():
        n += 1
        candidate = f'{base}{n}@fsbank'
    return candidate


def register(full_name, email, phone, password, role_code, location_id, ip):
    """Creates a customer and their bank account. The caller logs them in."""
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise ApiError('Enter a valid email address.', 422, 'VALIDATION_ERROR', {'field': 'email'})
    if role_code not in SELF_REGISTER_ROLES:
        raise ApiError('You can open a User (send money) or Receiver (receive money) account.', 422,
                       'VALIDATION_ERROR', {'field': 'role'})
    if phone and not re.fullmatch(r'[6-9]\d{9}', phone):
        raise ApiError('Enter a valid 10-digit mobile number.', 422, 'VALIDATION_ERROR', {'field': 'phone'})
    _check_password(password)
    if User.query.filter(func.lower(User.email) == email).first():
        raise ApiError('An account with this email already exists. Please sign in.', 409, 'EMAIL_TAKEN',
                       {'field': 'email'})
    if not db.session.get(Location, int(location_id or 0)):
        raise ApiError('Choose your home city.', 422, 'VALIDATION_ERROR', {'field': 'location_id'})

    user = User(role_id=Role.query.filter_by(code=role_code).first().id, full_name=full_name, email=email,
                phone=phone, password_hash=generate_password_hash(password), home_location_id=int(location_id))
    db.session.add(user)
    db.session.flush()
    # Simulated bank: senders get a welcome balance so they can try payments straight away.
    opening = Decimal(setting('NEW_USER_OPENING_BALANCE')) if role_code == 'USER' else Decimal('0')
    account = Account(user_id=user.id, account_number=_unique_account_number(), ifsc=BRANCH_IFSC,
                      upi_id=_unique_upi(email), qr_token=secrets.token_hex(8), balance=opening,
                      opening_balance=opening)
    db.session.add(account)
    notify(user.id, 'Welcome to FraudShield Bank',
           f'Your account {account.account_number} is open. UPI ID: {account.upi_id}.'
           + (f' A simulated welcome balance of ₹{opening:,.0f} has been added.' if opening else ''), 'SUCCESS')
    write_audit('USER_REGISTERED', 'user', user.id, {'role': role_code, 'upi_id': account.upi_id}, ip=ip)
    db.session.commit()
    return user
