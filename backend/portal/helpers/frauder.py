"""Manual Frauder console: a presenter plays the attacker on designated demo
accounts. Every action is initiated by hand; nothing runs on its own.

What the Frauder can do is deliberately narrow:
- act only on the designated demo victims and pay only the designated demo receivers;
- record login attempts ("wrong password" / "stolen password") without ever
  seeing or setting a password;
- type the attacker's city, location, device type, device ID and IP address
  by hand. These are SIMULATED inputs: they feed the fraud rules and are stored
  with the attempt, but are never written to the victim's profile and never
  treated as a verified identity or location. Nothing is filled in for the
  presenter – no random IPs, no default city, no geolocation;
- submit transfers, which go through the normal payment pipeline.

It cannot touch balances, approve anything or switch rules off: the outcome is
always whatever the SQL rule engine (and then the account owner's YES/NO
confirmation) decides."""
import ipaddress
import re
from datetime import datetime, timedelta
from decimal import ROUND_UP, Decimal

from sqlalchemy import func

from portal.extensions import db
from portal.helpers.audit import write_audit
from portal.helpers.auth import _clear_expired_lock, register_attempt
from portal.helpers.helpers import security_event, setting
from portal.helpers.payment_engine import expire_confirmations, hard_block_rules, send_money
from portal.helpers.responses import ApiError
from portal.helpers.validators import parse_amount
from portal.models import (Alert, Device, FraudRule, Location, LoginAttempt, RiskAssessment, SecurityEvent,
                           Transaction, User, WatchlistEntry, money, now)

VICTIMS = ('rahul@demo.bank', 'suresh@demo.bank', 'karan@demo.bank')
RECEIVERS = ('priya@demo.bank', 'amit@demo.bank', 'quickcash@demo.bank')
SCENARIO_CODE = 'FRAUDER_MANUAL'
# Typed device IDs are stored under this prefix, so an attacker value can
# never collide with (or claim) a genuine customer device.
ATTACKER_PREFIX = 'sim-atk-'
DEVICE_ID_RE = re.compile(r'^[A-Za-z0-9._:-]{3,40}$')
DEVICE_TYPES = ('Android phone', 'iPhone', 'Windows PC', 'MacBook', 'Linux PC', 'Tablet')   # suggestions only
SCENARIOS = (
    ('R1', 'R1 · High transaction amount'),
    ('R2', 'R2 · Transaction velocity'),
    ('R3', 'R3 · Impossible travel'),
    ('R4', 'R4 · New device + high amount'),
    ('R5', 'R5 · Odd-hour transaction'),
    ('R6', 'R6 · Watch-listed receiver'),
    ('R7', 'R7 · Structuring below the reporting limit'),
    ('R8', 'R8 · Dormant account reactivation'),
    ('R9', 'R9 · Suspicious login / account takeover'),
    ('ATO', 'Account takeover – combined attack'),
    ('CUSTOM', 'Custom attempt'),
)


# ── Lookups & guards ────────────────────────────────────────────────────────

def _victim(victim_id):
    user = db.session.get(User, int(victim_id)) if str(victim_id).isdigit() else None
    if user is None or user.email not in VICTIMS:
        raise ApiError('Choose one of the designated demo victim accounts.', 422, 'NOT_A_DEMO_VICTIM',
                       {'field': 'victim_id'})
    return user


def _receiver(receiver_id, victim):
    user = db.session.get(User, int(receiver_id)) if str(receiver_id).isdigit() else None
    if user is None or user.email not in RECEIVERS or user.id == victim.id:
        raise ApiError('Choose one of the designated demo receivers.', 422, 'NOT_A_DEMO_RECEIVER',
                       {'field': 'receiver_id'})
    return user


def _invalid(field, message):
    return ApiError(message, 422, 'VALIDATION_ERROR', {'field': field})


def _attacker_details(data, for_login=False):
    """Validates the values the presenter typed and returns them as the
    SIMULATED record stored with the attempt."""
    city_name = (data.get('city') or '').strip()
    if not city_name:
        raise _invalid('city', 'Enter the target city.')
    location = Location.query.filter(func.lower(Location.city) == city_name.lower()).first()
    if location is None:
        cities = ', '.join(l.city for l in Location.query.order_by(Location.city).all())
        raise _invalid('city', f'Unknown city "{city_name}". The travel rule needs its coordinates – use one of: '
                               f'{cities}.')

    registered = bool(data.get('use_registered_device')) and not for_login
    device_type = (data.get('device_type') or '').strip()
    device_id = (data.get('device_id') or '').strip()
    if not registered:
        if not device_type or len(device_type) > 60:
            raise _invalid('device_type', 'Enter the device type (up to 60 characters), e.g. Android phone.')
        if not DEVICE_ID_RE.match(device_id):
            raise _invalid('device_id', 'Device ID: 3–40 letters, digits or . _ : - (e.g. ATK-PHONE-01).')

    try:
        ip = str(ipaddress.ip_address((data.get('ip_address') or '').strip()))
    except ValueError:
        raise _invalid('ip_address', 'Enter a valid IPv4 or IPv6 address, e.g. 203.0.113.25.')

    target_location = (data.get('target_location') or '').strip()
    if len(target_location) > 120:
        raise _invalid('target_location', 'Target location can be at most 120 characters.')
    scenario = (data.get('scenario') or '').strip().upper() or None
    if scenario and scenario not in dict(SCENARIOS):
        raise _invalid('scenario', 'Choose a fraud scenario from the list.')

    return {
        'source': 'SIMULATED', 'verified': False,
        'city': location.city, 'location_id': location.id, 'target_location': target_location or None,
        'use_registered_device': registered,
        'device_type': None if registered else device_type, 'device_id': None if registered else device_id,
        'ip_address': ip, 'scenario': scenario, 'scenario_name': dict(SCENARIOS).get(scenario),
    }


def _registered_device(victim):
    """The victim's own trusted device (remote-access scam)."""
    device = (Device.query.filter_by(user_id=victim.id, is_trusted=True)
              .order_by(Device.last_seen_at.desc()).first())
    if device is None:
        raise _invalid('use_registered_device', f'{victim.full_name} has no registered device yet – sign in once as '
                                                f'{victim.full_name.split()[0]}, or enter an attacker device instead.')
    return device


def _attacker_device(victim, details):
    """Finds or creates the attacker device for the typed device ID. It is
    always untrusted unless the owner later verifies a payment made from it."""
    fingerprint = ATTACKER_PREFIX + details['device_id']
    device = Device.query.filter_by(user_id=victim.id, fingerprint=fingerprint).first()
    if device is None:
        device = Device(user_id=victim.id, fingerprint=fingerprint, is_trusted=False)
        db.session.add(device)
    device.device_name = details['device_type'][:150]
    device.last_ip, device.last_location_id, device.last_seen_at = (details['ip_address'], details['location_id'],
                                                                    now())
    db.session.flush()
    return device


def _demo_time(value):
    """'HH:MM' → today at that time (yesterday if it is still in the future).
    Only the time of day is simulated, so R5 can be shown without waiting for night."""
    if not value:
        return None
    try:
        t = datetime.strptime(value.strip(), '%H:%M').time()
    except ValueError:
        raise _invalid('demo_time', 'Demo time must be HH:MM, e.g. 02:30.')
    at = datetime.combine(now().date(), t)
    return at - timedelta(days=1) if at > now() else at


def _stored(details):
    """What is saved with the attempt (the location id is internal)."""
    return {k: v for k, v in details.items() if k != 'location_id'}


# ── Read models ─────────────────────────────────────────────────────────────

def _history(account_id, days=90):
    row = (db.session.query(func.count(Transaction.id), func.avg(Transaction.amount))
           .filter(Transaction.sender_account_id == account_id, Transaction.status == 'COMPLETED',
                   Transaction.txn_time >= now() - timedelta(days=days)).one())
    return row[0], (Decimal(row[1]) if row[1] is not None else None)


def _idle_days(account):
    last = account.last_txn_at or account.created_at
    return (now() - last).days


def _victim_dict(user):
    _clear_expired_lock(user, now())
    account = user.primary_account
    count, avg = _history(account.id)
    own = Device.query.filter_by(user_id=user.id, is_trusted=True).order_by(Device.last_seen_at.desc()).first()
    attacker = (Device.query.filter(Device.user_id == user.id, Device.fingerprint.like(ATTACKER_PREFIX + '%'))
                .order_by(Device.id.desc()).limit(8).all())
    return {
        'id': user.id, 'name': user.full_name, 'upi_id': account.upi_id, 'balance': money(account.balance),
        'home_city': user.home_location.city if user.home_location else None, 'status': user.status,
        'failed_login_count': user.failed_login_count,
        'locked_until': user.locked_until.isoformat(timespec='minutes') if user.locked_until else None,
        'own_device': own.device_name if own else None,
        # Device IDs the presenter typed before, shown for reference only.
        'attacker_devices': [{'device_id': d.fingerprint[len(ATTACKER_PREFIX):], 'name': d.device_name,
                              'is_trusted': d.is_trusted} for d in attacker],
        'payments_90d': count, 'average_90d': money(avg), 'idle_days': _idle_days(account),
        'is_dormant_demo': user.email == 'suresh@demo.bank',
    }


def context():
    expire_confirmations()
    victims = User.query.filter(User.email.in_(VICTIMS)).all()
    receivers = User.query.filter(User.email.in_(RECEIVERS)).all()
    listed = {w.entity_value for w in WatchlistEntry.query.filter_by(is_active=True).all()}
    order = {e: i for i, e in enumerate(VICTIMS + RECEIVERS)}
    return {
        'victims': [_victim_dict(u) for u in sorted(victims, key=lambda u: order[u.email])],
        'receivers': [{'id': u.id, 'name': u.full_name, 'upi_id': u.primary_account.upi_id,
                       'balance': money(u.primary_account.balance),
                       'watchlisted': u.primary_account.upi_id in listed or u.primary_account.account_number in listed}
                      for u in sorted(receivers, key=lambda u: order[u.email])],
        # Suggestions for the free-text fields; nothing is pre-selected.
        'cities': [l.city for l in Location.query.order_by(Location.city).all()],
        'device_types': list(DEVICE_TYPES),
        'scenarios': [{'code': c, 'name': n} for c, n in SCENARIOS],
        'policy': {'confirmation_expiry_minutes': setting('CONFIRMATION_EXPIRY_MINUTES'),
                   'expiry_action': setting('CONFIRMATION_EXPIRY_ACTION', str).upper(),
                   'hard_block_rules': sorted(hard_block_rules())},
    }


def detection_result(txn, balances_before=None):
    """Everything the presenter needs to explain one decision."""
    initial = (RiskAssessment.query.filter_by(transaction_id=txn.id).order_by(RiskAssessment.id).first())
    latest = (RiskAssessment.query.filter_by(transaction_id=txn.id).order_by(RiskAssessment.id.desc()).first())
    data = txn.to_dict()
    data.update({
        'sender_name': txn.sender_account.user.full_name,
        'receiver_name': txn.receiver_account.user.full_name,
        'rule_trace': (latest or initial).rule_trace or [] if (latest or initial) else [],
        'rules_evaluated': initial.rules_evaluated if initial else None,
        'evaluation_ms': float(initial.latency_ms) if initial and initial.latency_ms is not None else None,
        'timeline': _timeline(txn),
        'balances': {
            'sender': {'name': txn.sender_account.user.full_name, 'after': money(txn.sender_account.balance),
                       'before': (balances_before or {}).get('sender')},
            'receiver': {'name': txn.receiver_account.user.full_name, 'after': money(txn.receiver_account.balance),
                         'before': (balances_before or {}).get('receiver')},
        },
    })
    return data


def _timeline(txn):
    victim_id = txn.sender_account.user_id
    owner = txn.sender_account.user.full_name.split()[0]
    since = txn.created_at - timedelta(minutes=30)
    items = []
    for la in (LoginAttempt.query.filter(LoginAttempt.user_id == victim_id, LoginAttempt.is_simulated.is_(True),
                                         LoginAttempt.created_at.between(since, txn.created_at))
               .order_by(LoginAttempt.created_at).all()):
        city = la.location.city if la.location else '?'
        items.append({'at': la.created_at, 'kind': 'activity',
                      'label': 'Login with stolen password' if la.success else 'Wrong password attempt',
                      'detail': f"device {_device_label(la.fingerprint)} · {la.ip_address} · {city}"
                                + (' · new device' if la.is_new_device else '')})
    for se in (SecurityEvent.query.filter(SecurityEvent.user_id == victim_id, SecurityEvent.event_type == 'OTP_FAILED',
                                          SecurityEvent.is_simulated.is_(True),
                                          SecurityEvent.created_at.between(since, txn.created_at)).all()):
        items.append({'at': se.created_at, 'kind': 'activity', 'label': 'Wrong OTP entered', 'detail': se.description})
    items.sort(key=lambda i: i['at'])

    sim = txn.simulated_details or {}
    city = txn.location.city if txn.location else '?'
    device = txn.device.device_name if txn.device else 'unknown device'
    if sim.get('use_registered_device'):
        device = f'{owner}’s registered device'
    elif sim.get('device_id'):
        device = f"{sim.get('device_type')} #{sim['device_id']}"
    items.append({'at': txn.created_at, 'kind': 'submit', 'label': 'Transaction submitted',
                  'detail': f"₹{money(txn.amount):,.2f} to {txn.receiver_account.user.full_name} from {device}, "
                            f"IP {txn.ip_address or '?'}, {city}" + (f" (demo clock {txn.txn_time:%H:%M})"
                            if abs((txn.txn_time - txn.created_at).total_seconds()) > 60 else '')})

    assessments = RiskAssessment.query.filter_by(transaction_id=txn.id).order_by(RiskAssessment.id).all()
    if assessments:
        first = assessments[0]
        fired = [t for t in (first.rule_trace or []) if t['status'] == 'TRIGGERED']
        items += [
            {'at': first.created_at, 'kind': 'engine', 'label': 'Fraud rules evaluated',
             'detail': f'{first.rules_evaluated} SQL rules in {first.latency_ms} ms'},
            {'at': first.created_at, 'kind': 'engine', 'label': 'Rules triggered',
             'detail': ', '.join(t['code'] for t in fired) or 'none'},
            {'at': first.created_at, 'kind': 'engine', 'label': 'Risk score calculated',
             'detail': f'min(100, {" + ".join(str(t["weight"]) for t in fired) or "0"}) = {first.risk_score}'},
            {'at': first.created_at, 'kind': 'decision', 'label': 'Risk band (recorded)',
             'detail': f'{first.decision} – ' + ('the account owner decides (YES/NO)' if fired else 'no rule triggered: normal payment')},
        ]
    if txn.confirmation_status:
        items.append({'at': txn.decided_at or txn.created_at, 'kind': 'confirm',
                      'label': f'Confirmation requested from {owner}',
                      'detail': f'“Security Verification Required – did you initiate this transaction?” – answer by '
                                f'{txn.confirmation_expires_at:%H:%M}' if txn.confirmation_expires_at else ''})
        if txn.confirmation_responded_at:
            items.append({'at': txn.confirmation_responded_at, 'kind': 'confirm',
                          'label': f'{owner} answered {txn.confirmation_response}',
                          'detail': 'Not me → blocked immediately' if txn.confirmation_response == 'NO'
                          else 'Yes, I initiated it → re-validated and authorized'})
        if txn.confirmation_status == 'EXPIRED':
            items.append({'at': txn.confirmation_expires_at, 'kind': 'confirm', 'label': 'Confirmation expired',
                          'detail': 'No answer in time – EXPIRED, never authorized automatically'})
    for later in assessments[1:]:
        items.append({'at': later.created_at, 'kind': 'engine', 'label': 'Re-evaluated',
                      'detail': f'{later.assessment_type.replace("_", " ").lower()}: score {later.risk_score} → '
                                f'{later.decision}'})
    for alert in Alert.query.filter_by(transaction_id=txn.id).order_by(Alert.id).all():
        items.append({'at': alert.created_at, 'kind': 'alert', 'label': 'Security alert created',
                      'detail': f'{alert.severity} – {alert.title}'})
    items.sort(key=lambda i: i['at'] or txn.created_at)

    end = txn.completed_at or txn.confirmation_responded_at or txn.decided_at or txn.created_at
    items.append({'at': max(end, items[-1]['at'] or end), 'kind': 'money',
                  'label': ('Money transferred' if txn.status == 'COMPLETED'
                            else 'Waiting – no money moved yet' if txn.status == 'UNDER_REVIEW' else 'Money not moved'),
                  'detail': txn.final_reason or {
                      'COMPLETED': 'Sender debited and receiver credited in one database transaction.',
                      'UNDER_REVIEW': f'Held until {owner} answers YES (authorize) or NO (block).',
                  }.get(txn.status, 'Neither balance changed.')})
    return [{**i, 'at': i['at'].isoformat(timespec='seconds') if i['at'] else None} for i in items]


def _device_label(fingerprint):
    return fingerprint[len(ATTACKER_PREFIX):] if fingerprint and fingerprint.startswith(ATTACKER_PREFIX) else '?'


def attempts(limit=40):
    expire_confirmations()
    victims = [u.id for u in User.query.filter(User.email.in_(VICTIMS)).all()]
    rows = []
    for la in (LoginAttempt.query.filter(LoginAttempt.user_id.in_(victims), LoginAttempt.is_simulated.is_(True))
               .order_by(LoginAttempt.id.desc()).limit(limit).all()):
        rows.append({'type': 'LOGIN', 'at': la.created_at, 'victim': db.session.get(User, la.user_id).full_name,
                     'summary': ('Logged in with stolen password' if la.success else
                                 f"Wrong password ({(la.failure_reason or '').replace('_', ' ').lower()})"),
                     'detail': f"device {_device_label(la.fingerprint)} · {la.ip_address} · "
                               f"{la.location.city if la.location else '?'}" + (' · new device' if la.is_new_device else ''),
                     'outcome': 'SUCCESS' if la.success else 'FAILED'})
    for se in (SecurityEvent.query.filter(SecurityEvent.user_id.in_(victims), SecurityEvent.is_simulated.is_(True),
                                          SecurityEvent.event_type == 'OTP_FAILED')
               .order_by(SecurityEvent.id.desc()).limit(limit).all()):
        rows.append({'type': 'OTP', 'at': se.created_at, 'victim': se.user.full_name, 'summary': 'Wrong OTP entered',
                     'detail': se.ip_address or '', 'outcome': 'FAILED'})
    for t in (Transaction.query.filter(Transaction.scenario_code == SCENARIO_CODE)
              .order_by(Transaction.id.desc()).limit(limit).all()):
        sim = t.simulated_details or {}
        device = ('registered device' if sim.get('use_registered_device')
                  else f"{sim.get('device_type')} #{sim.get('device_id')}" if sim.get('device_id') else '?')
        rows.append({'type': 'TRANSFER', 'at': t.created_at, 'victim': t.sender_account.user.full_name,
                     'transaction_id': t.id, 'txn_ref': t.txn_ref,
                     'summary': f"₹{money(t.amount):,.0f} → {t.receiver_account.user.full_name}",
                     'detail': f"{sim.get('city') or (t.location.city if t.location else '?')} · {device} · "
                               f"{t.ip_address or '?'}",
                     'scenario': sim.get('scenario_name'), 'simulated_details': sim or None,
                     'rules': [h.rule_code for h in t.latest_hits()], 'risk_score': t.risk_score,
                     'outcome': t.status, 'outcome_label': t.outcome_label(), 'confirmation': t.confirmation_dict(),
                     'money_moved': t.status == 'COMPLETED'})
    rows.sort(key=lambda r: r['at'], reverse=True)
    return [{**r, 'at': r['at'].isoformat(timespec='seconds')} for r in rows[:limit]]


# ── Actions ────────────────────────────────────────────────────────────────

def login_attempt(frauder, data):
    victim = _victim(data.get('victim_id'))
    outcome = (data.get('outcome') or '').upper()
    if outcome not in ('WRONG_PASSWORD', 'STOLEN_PASSWORD'):
        raise ApiError('Choose "wrong password" or "stolen password".', 422, 'VALIDATION_ERROR')
    details = _attacker_details(data, for_login=True)
    _clear_expired_lock(victim, now())
    fingerprint, name = ATTACKER_PREFIX + details['device_id'], details['device_type']
    ip, location_id = details['ip_address'], details['location_id']

    if victim.status == 'LOCKED':
        register_attempt(victim, victim.email, False, fingerprint, name, ip, location_id,
                         failure_reason='ACCOUNT_LOCKED', simulated=True)
        result = {'success': False, 'message': f'Login refused: the account is locked until '
                                               f'{victim.locked_until:%H:%M} after repeated failures.'}
    elif outcome == 'WRONG_PASSWORD':
        register_attempt(victim, victim.email, False, fingerprint, name, ip, location_id,
                         failure_reason='BAD_PASSWORD', simulated=True)
        result = {'success': False, 'message': (
            f'Wrong password – {victim.failed_login_count} consecutive failure(s).' if victim.status == 'ACTIVE' else
            f'Wrong password – the account is now LOCKED after {victim.failed_login_count} failures.')}
    else:
        device = register_attempt(victim, victim.email, True, fingerprint, name, ip, location_id, simulated=True,
                                  trust_first=False)
        result = {'success': True, 'device_id': details['device_id'],
                  'message': f'Signed in to {victim.full_name}’s account from {name} #{details["device_id"]} '
                             f'({ip}, {details["city"]}). The bank recorded a {"new-device " if not device.is_trusted else ""}login.'}
    write_audit('FRAUDER_LOGIN_ATTEMPT', 'user', victim.id,
                {'outcome': outcome, 'success': result['success'], 'simulated_inputs': _stored(details)},
                actor=frauder)
    db.session.commit()
    result['victim'] = _victim_dict(victim)
    return result


def otp_attempt(frauder, data):
    victim = _victim(data.get('victim_id'))
    ip = None
    if (data.get('ip_address') or '').strip():
        try:
            ip = str(ipaddress.ip_address(data['ip_address'].strip()))
        except ValueError:
            raise _invalid('ip_address', 'Enter a valid IPv4 or IPv6 address, e.g. 203.0.113.25.')
    security_event(victim.id, 'OTP_FAILED', 'Wrong OTP entered during a suspicious session', 'MEDIUM',
                   ip=ip, simulated=True)
    write_audit('FRAUDER_OTP_ATTEMPT', 'user', victim.id, {'ip': ip}, actor=frauder)
    db.session.commit()
    count = SecurityEvent.query.filter(SecurityEvent.user_id == victim.id, SecurityEvent.event_type == 'OTP_FAILED',
                                       SecurityEvent.created_at >= now() - timedelta(hours=1)).count()
    return {'message': f'Wrong OTP recorded ({count} in the last hour).', 'otp_failures_last_hour': count}


def transfer(frauder, data, idempotency_key):
    victim = _victim(data.get('victim_id'))
    receiver = _receiver(data.get('receiver_id'), victim)
    details = _attacker_details(data)
    txn_time = _demo_time(data.get('demo_time'))
    if txn_time:
        details['demo_time'] = txn_time.strftime('%H:%M')
    amount = parse_amount(data.get('amount'))

    if idempotency_key:
        existing = Transaction.query.filter_by(sender_account_id=victim.primary_account.id,
                                               idempotency_key=idempotency_key).first()
        if existing:
            return detection_result(existing), True

    device = _registered_device(victim) if details['use_registered_device'] else _attacker_device(victim, details)
    before = {'sender': money(victim.primary_account.balance), 'receiver': money(receiver.primary_account.balance)}
    db.session.commit()   # persist a newly created attacker device before the payment transaction
    txn, replayed = send_money(victim, 'UPI', {'upi_id': receiver.primary_account.upi_id}, amount,
                               remarks='Frauder attempt', idempotency_key=idempotency_key,
                               device_id=device.id, ip=details['ip_address'], location_id=details['location_id'],
                               simulated=True, scenario_code=SCENARIO_CODE, fraud_label=True, txn_time=txn_time,
                               simulated_details=_stored(details), owner_must_confirm=True)
    write_audit('FRAUDER_TRANSFER_ATTEMPT', 'transaction', txn.id,
                {'amount': str(amount), 'decision': txn.decision, 'score': txn.risk_score,
                 'simulated_inputs': _stored(details)}, actor=frauder)
    db.session.commit()
    return detection_result(txn, before), replayed


# ── Guidance for the nine rules (text only – nothing is filled in) ──────────

def _inr(value):
    return f'₹{Decimal(value):,.0f}'


def rule_guide():
    """Hints built from the *configured* thresholds and the victims' real
    history. They only say what to type; the presenter enters every value
    and the engine decides."""
    p = {r.code: r.params for r in FraudRule.query.all()}
    w = {r.code: r.weight for r in FraudRule.query.all()}
    active = {r.code: r.is_active for r in FraudRule.query.all()}
    rahul = User.query.filter_by(email='rahul@demo.bank').first()
    suresh = User.query.filter_by(email='suresh@demo.bank').first()
    quickcash = User.query.filter_by(email='quickcash@demo.bank').first()
    home = rahul.home_location.city if rahul.home_location else 'his home city'
    hard = hard_block_rules()

    count, avg = _history(rahul.primary_account.id, p['R1']['lookback_days'])
    if count >= p['R1']['min_history_txns']:
        limit = avg * Decimal(str(p['R1']['multiplier']))
        r1_amount = (limit * Decimal('1.2')).quantize(Decimal('1000'), rounding=ROUND_UP)
        r1_hint = (f"Rahul’s average over his last {count} payments is {_inr(avg)}, so R1 fires above "
                   f"{p['R1']['multiplier']}× that = {_inr(limit)}. Send about {_inr(r1_amount)} and tick "
                   f"“Use victim’s registered device” so R4 stays quiet.")
    else:
        r1_hint = (f"Rahul has only {count} completed payment(s) in {p['R1']['lookback_days']} days, so R1 uses the "
                   f"no-history limit of {_inr(p['R1']['no_history_threshold'])}. Send more than that, or first make "
                   f"{p['R1']['min_history_txns']} small genuine payments as Rahul.")
    r7 = p['R7']
    r7_low = Decimal(str(r7['reporting_threshold'])) * (100 - Decimal(str(r7['band_percent']))) / 100

    guide = [
        {'code': 'R1', 'title': 'High transaction amount', 'hint': r1_hint},
        {'code': 'R2', 'title': 'Transaction velocity',
         'hint': f"Keep the same details and press Attempt Transaction {p['R2']['max_txns'] + 1} times with a small "
                 f"amount (e.g. ₹200) within {p['R2']['window_minutes']} minutes. The "
                 f"{p['R2']['max_txns'] + 1}th triggers R2."},
        {'code': 'R3', 'title': 'Impossible travel',
         'hint': f"Send ₹500 with city {home}, then within {p['R3']['window_minutes']} minutes type a city at least "
                 f"{p['R3']['min_distance_km']} km away (e.g. Delhi) and send again."},
        {'code': 'R4', 'title': 'New device + high amount',
         'hint': f"Type a device ID never used before (e.g. ATK-PHONE-01) and send more than "
                 f"{_inr(p['R4']['amount_threshold'])}."},
        {'code': 'R5', 'title': 'Odd-hour transaction',
         'hint': f"Tick “Use demo clock”, enter a time between {p['R5']['start_hour']:02d}:00 and "
                 f"{p['R5']['end_hour']:02d}:00 (e.g. 02:30) and send more than {_inr(p['R5']['amount_threshold'])}."},
        {'code': 'R6', 'title': 'Watch-listed counterparty',
         'hint': f"Choose {quickcash.full_name} ({quickcash.primary_account.upi_id}) as the receiver – it is on the "
                 f"watchlist." + (" R6 is a hard-block rule: even if the owner answers YES, the payment stays "
                                  "blocked." if 'R6' in hard else '')},
        {'code': 'R7', 'title': 'Transaction structuring',
         'hint': f"Send {r7['min_count']} payments between {_inr(r7_low)} and "
                 f"{_inr(Decimal(str(r7['reporting_threshold'])) - 1)} within {r7['window_hours']} hours – just under "
                 f"the {_inr(r7['reporting_threshold'])} reporting threshold."},
        {'code': 'R8', 'title': 'Dormant account reactivation',
         'hint': f"Target {suresh.full_name} – the designated dormant demo account, idle for "
                 f"{_idle_days(suresh.primary_account)} days (limit {p['R8']['inactive_days']}). Send at least "
                 f"{_inr(p['R8']['amount_threshold'])}."},
        {'code': 'R9', 'title': 'Suspicious login / account takeover',
         'hint': f"Click “Wrong password” {p['R9']['failed_login_threshold']} times, then “Log in with stolen "
                 f"password” – all with the same new device ID and a city other than {home}. Then attempt a transfer "
                 f"of at least {_inr(p['R9']['min_amount'])} with that same device ID (keep it ≤ "
                 f"{_inr(p['R4']['amount_threshold'])} to see R9 on its own)."},
    ]
    for g in guide:
        g.update({'weight': w[g['code']], 'active': active[g['code']], 'hard_block': g['code'] in hard})
    return guide
