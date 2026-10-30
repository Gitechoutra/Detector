from decimal import Decimal

from portal.extensions import db
from portal.models import Alert, Notification, SecurityEvent, SystemSetting

DEFAULT_SETTINGS = {
    'LOGIN_MAX_FAILURES': 5,
    'LOGIN_LOCK_MINUTES': 15,
    'OTP_EXPIRY_MINUTES': 5,
    'OTP_MAX_ATTEMPTS': 3,
    'SIM_DEFAULT_INTERVAL_SECONDS': 6,
    'MAX_TXN_AMOUNT': 1000000,
    'NEW_USER_OPENING_BALANCE': 50000,
    'CONFIRMATION_EXPIRY_MINUTES': 30,
    'CONFIRMATION_EXPIRY_ACTION': 'EXPIRE',
    'CONFIRMATION_HARD_BLOCK_RULES': '',
}


def setting(key, cast=int):
    row = db.session.get(SystemSetting, key)
    value = row.setting_value if row else DEFAULT_SETTINGS[key]
    return cast(value)


def inr(value):
    return f'₹{Decimal(value):,.2f}'


def notify(user_id, title, message, category='INFO', transaction_id=None, simulated=False):
    db.session.add(Notification(user_id=user_id, title=title, message=message, category=category,
                                transaction_id=transaction_id, is_simulated=simulated))


def security_event(user_id, event_type, description, severity='LOW', device_id=None, ip=None,
                   location_id=None, transaction_id=None, simulated=False, at=None):
    event = SecurityEvent(user_id=user_id, event_type=event_type, description=description[:255],
                          severity=severity, device_id=device_id, ip_address=ip, location_id=location_id,
                          transaction_id=transaction_id, is_simulated=simulated)
    if at is not None:
        event.created_at = at
    db.session.add(event)
    return event


def raise_alert(alert_type, severity, title, message, user_id=None, transaction_id=None, risk_score=None,
                simulated=False):
    alert = Alert(alert_type=alert_type, severity=severity, title=title[:150], message=message,
                  user_id=user_id, transaction_id=transaction_id, risk_score=risk_score,
                  is_simulated=simulated)
    db.session.add(alert)
    return alert
