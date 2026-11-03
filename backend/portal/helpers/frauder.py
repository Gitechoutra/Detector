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

from sqlalchemy import bindparam, func, text

from portal.extensions import db
from portal.helpers import investigations
from portal.helpers.audit import write_audit
from portal.helpers.auth import _clear_expired_lock, register_attempt
from portal.helpers.helpers import security_event, setting
from portal.helpers.fraud_engine import band_floor
from portal.helpers.payment_engine import expire_confirmations, hard_block_rules, send_money
from portal.helpers.responses import ApiError
from portal.helpers.validators import as_text, parse_amount
from portal.models import (Account, Alert, Device, Location, LoginAttempt, RiskAssessment, SecurityEvent,
                           InvestigationAction, InvestigationCase, ReceiverBlock, Transaction, User, WatchlistEntry,
                           money, now)
from portal.models.investigations import OPEN_STATUSES

# Designated dummy accounts, by seed_key (their emails come from .env and may change).
VICTIMS = ('rahul', 'suresh', 'karan')
RECEIVERS = ('priya', 'amit', 'quickcash')
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
    if user is None or user.seed_key not in VICTIMS:
        raise ApiError('Choose one of the designated demo victim accounts.', 422, 'NOT_A_DEMO_VICTIM',
                       {'field': 'victim_id'})
    return user


def _receiver(receiver_id, victim):
    user = db.session.get(User, int(receiver_id)) if str(receiver_id).isdigit() else None
    if user is None or user.seed_key not in RECEIVERS or user.id == victim.id:
        raise ApiError('Choose one of the designated demo receivers.', 422, 'NOT_A_DEMO_RECEIVER',
                       {'field': 'receiver_id'})
    return user


def _invalid(field, message):
    return ApiError(message, 422, 'VALIDATION_ERROR', {'field': field})


def _attacker_details(data, for_login=False):
    """Validates the values the presenter typed and returns them as the
    SIMULATED record stored with the attempt."""
    city_name = as_text(data.get('city')).strip()
    if not city_name:
        raise _invalid('city', 'Enter the target city.')
    location = Location.query.filter(func.lower(Location.city) == city_name.lower()).first()
    if location is None:
        cities = ', '.join(l.city for l in Location.query.order_by(Location.city).all())
        raise _invalid('city', f'Unknown city "{city_name}". The travel rule needs its coordinates – use one of: '
                               f'{cities}.')

    registered = bool(data.get('use_registered_device')) and not for_login
    device_type = as_text(data.get('device_type')).strip()
    device_id = as_text(data.get('device_id')).strip()
    if not registered:
        if not device_type or len(device_type) > 60:
            raise _invalid('device_type', 'Enter the device type (up to 60 characters), e.g. Android phone.')
        if not DEVICE_ID_RE.match(device_id):
            raise _invalid('device_id', 'Device ID: 3–40 letters, digits or . _ : - (e.g. ATK-PHONE-01).')

    try:
        ip = str(ipaddress.ip_address(as_text(data.get('ip_address')).strip()))
    except ValueError:
        raise _invalid('ip_address', 'Enter a valid IPv4 or IPv6 address, e.g. 203.0.113.25.')

    target_location = as_text(data.get('target_location')).strip()
    if len(target_location) > 120:
        raise _invalid('target_location', 'Target location can be at most 120 characters.')
    scenario = as_text(data.get('scenario')).strip().upper() or None
    if scenario and scenario not in dict(SCENARIOS):
        raise _invalid('scenario', 'Choose a fraud scenario from the list.')

    return {
        'source': 'SIMULATED', 'verified': False,
        'city': location.city, 'location_id': location.id, 'target_location': target_location or None,
        'use_registered_device': registered,
        'device_type': None if registered else device_type, 'device_id': None if registered else device_id,
        'ip_address': ip, 'scenario': scenario, 'scenario_name': dict(SCENARIOS).get(scenario),
    }


CONTEXT_FIELDS = ('city', 'target_location', 'device_type', 'device_id', 'ip_address', 'use_registered_device',
                  'demo_time')


def _no_context(data, victim):
    """No attempt context entered (the console no longer asks for one): the
    attempt uses the victim's own home city and registered device, if any."""
    scenario = as_text(data.get('scenario')).strip().upper() or None
    if scenario and scenario not in dict(SCENARIOS):
        raise _invalid('scenario', 'Choose a fraud scenario from the list.')
    return {'source': 'FRAUDER', 'city': victim.home_location.city if victim.home_location else None,
            'location_id': victim.home_location_id, 'scenario': scenario,
            'scenario_name': dict(SCENARIOS).get(scenario)}


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

def _victim_dict(user):
    """What the console's target list needs (the old profile cards are gone)."""
    account = user.primary_account
    return {'id': user.id, 'name': user.full_name, 'upi_id': account.upi_id, 'balance': money(account.balance),
            'home_city': user.home_location.city if user.home_location else None, 'status': user.status}


def context():
    expire_confirmations()
    victims = User.query.filter(User.seed_key.in_(VICTIMS)).all()
    receivers = User.query.filter(User.seed_key.in_(RECEIVERS)).all()
    listed = {w.entity_value for w in WatchlistEntry.query.filter_by(is_active=True).all()}
    order = {e: i for i, e in enumerate(VICTIMS + RECEIVERS)}
    return {
        'victims': [_victim_dict(u) for u in sorted(victims, key=lambda u: order[u.seed_key])],
        'receivers': [{'id': u.id, 'name': u.full_name, 'upi_id': u.primary_account.upi_id,
                       'balance': money(u.primary_account.balance),
                       'watchlisted': u.primary_account.upi_id in listed or u.primary_account.account_number in listed,
                       'blocked': u.primary_account.status in ('BLOCKED', 'PERMANENTLY_BLOCKED')}
                      for u in sorted(receivers, key=lambda u: order[u.seed_key])],
        # Suggestions for the free-text fields; nothing is pre-selected.
        'cities': [l.city for l in Location.query.order_by(Location.city).all()],
        'device_types': list(DEVICE_TYPES),
        'scenarios': [{'code': c, 'name': n} for c, n in SCENARIOS],
        'policy': {'confirmation_expiry_minutes': setting('CONFIRMATION_EXPIRY_MINUTES'),
                   'expiry_action': setting('CONFIRMATION_EXPIRY_ACTION', str).upper(),
                   'hard_block_rules': sorted(hard_block_rules()),
                   'review_floor': band_floor('REVIEW'), 'block_floor': band_floor('BLOCKED')},
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
        'simulated_details': None,
        'confirmation': None,
        # Both texts describe the owner's approval step, which the Frauder does not see.
        'risk_explanation': None, 'final_reason': None, 'decline_reason': None,
        'outcome_label': txn.frauder_label(),
        'display_status': txn.frauder_label(),
        'receiver_account_status': txn.receiver_account.status,
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
             'detail': first.decision},
        ]
    for later in assessments[1:]:
        items.append({'at': later.created_at, 'kind': 'engine', 'label': 'Re-evaluated',
                      'detail': f'{later.assessment_type.replace("_", " ").lower()}: score {later.risk_score} → '
                                f'{later.decision}'})
    for alert in Alert.query.filter_by(transaction_id=txn.id).order_by(Alert.id).all():
        items.append({'at': alert.created_at, 'kind': 'alert', 'label': 'Security alert created',
                      'detail': f'{alert.severity} – {alert.title}'})
    items.sort(key=lambda i: i['at'] or txn.created_at)

    end = txn.completed_at or txn.confirmation_responded_at or txn.decided_at or txn.created_at
    label = txn.frauder_label()
    items.append({'at': max(end, items[-1]['at'] or end), 'kind': 'money',
                  'label': {'SUCCESS': 'Success – money transferred', 'CANCELLED': 'Cancelled – no money moved',
                            'PROCESSING': 'Processing – no money moved yet'}.get(label, f'{label.title()} – no money moved'),
                  'detail': {'SUCCESS': 'Sender debited and receiver credited in one database transaction.',
                             'CANCELLED': 'The transaction was cancelled. Neither balance changed.',
                             'PROCESSING': 'The transaction is being processed.'}.get(label, 'Neither balance changed.')})
    return [{**i, 'at': i['at'].isoformat(timespec='seconds') if i['at'] else None} for i in items]


def _device_label(fingerprint):
    return fingerprint[len(ATTACKER_PREFIX):] if fingerprint and fingerprint.startswith(ATTACKER_PREFIX) else '?'


def attempts(limit=40):
    expire_confirmations()
    victims = [u.id for u in User.query.filter(User.seed_key.in_(VICTIMS)).all()]
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
        rows.append({'type': 'TRANSFER', 'at': t.created_at, 'victim': t.sender_account.user.full_name,
                     'transaction_id': t.id, 'txn_ref': t.txn_ref,
                     'summary': f"₹{money(t.amount):,.0f} → {t.receiver_account.user.full_name}",
                     'detail': f"{t.location.city if t.location else '?'} · {t.ip_address or '?'}",
                     'rules': [h.rule_code for h in t.latest_hits()], 'risk_score': t.risk_score,
                     'outcome': t.frauder_label(), 'outcome_label': t.frauder_label(),
                     'money_moved': t.status == 'COMPLETED'})
    rows.sort(key=lambda r: r['at'], reverse=True)
    return [{**r, 'at': r['at'].isoformat(timespec='seconds')} for r in rows[:limit]]


# ── Actions ────────────────────────────────────────────────────────────────

def login_attempt(frauder, data):
    victim = _victim(data.get('victim_id'))
    outcome = as_text(data.get('outcome')).upper()
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
    if as_text(data.get('ip_address')).strip():
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
    with_context = any(data.get(k) not in (None, '', False) for k in CONTEXT_FIELDS)
    details = _attacker_details(data) if with_context else _no_context(data, victim)
    txn_time = _demo_time(data.get('demo_time'))
    if txn_time:
        details['demo_time'] = txn_time.strftime('%H:%M')
    amount = parse_amount(data.get('amount'))

    if idempotency_key:
        existing = Transaction.query.filter_by(sender_account_id=victim.primary_account.id,
                                               idempotency_key=idempotency_key).first()
        if existing:
            return detection_result(existing), True

    if not with_context:
        device = (Device.query.filter_by(user_id=victim.id, is_trusted=True)
                  .order_by(Device.last_seen_at.desc()).first())
    elif details['use_registered_device']:
        device = _registered_device(victim)
    else:
        device = _attacker_device(victim, details)
    before = {'sender': money(victim.primary_account.balance), 'receiver': money(receiver.primary_account.balance)}
    db.session.commit()   # persist a newly created attacker device before the payment transaction
    txn, replayed = send_money(victim, 'UPI', {'upi_id': receiver.primary_account.upi_id}, amount,
                               remarks='Frauder attempt', idempotency_key=idempotency_key,
                               device_id=device.id if device else None, ip=details.get('ip_address'),
                               location_id=details['location_id'],
                               simulated=True, scenario_code=SCENARIO_CODE, fraud_label=True, txn_time=txn_time,
                               simulated_details=_stored(details), owner_must_confirm=True)
    write_audit('FRAUDER_TRANSFER_ATTEMPT', 'transaction', txn.id,
                {'amount': str(amount), 'decision': txn.decision, 'score': txn.risk_score,
                 'simulated_inputs': _stored(details)}, actor=frauder)
    db.session.commit()
    return detection_result(txn, before), replayed


# ── Reset: undo only what the Frauder did ──────────────────────────────────

def reset_attempts(actor=None):
    """Undo only what the Frauder did, leaving every genuine payment,
    registered user and unrelated record alone.

    Money is restored by reversing each completed simulated payment (sender
    gets it back, receiver gives it back), so balances return to exactly what
    they would be had the simulation never run – even if people also made real
    payments in between."""
    from portal.helpers.payment_engine import _lock_accounts

    sim_txns = Transaction.query.filter_by(is_simulated=True).all()
    ids = [t.id for t in sim_txns]
    touched = {t.sender_account_id for t in sim_txns} | {t.receiver_account_id for t in sim_txns}

    completed = [t for t in sim_txns if t.status == 'COMPLETED']
    reversed_total = 0
    if completed:
        accounts = _lock_accounts(*{a for t in completed for a in (t.sender_account_id, t.receiver_account_id)})
        for t in completed:
            accounts[t.sender_account_id].balance += t.amount
            accounts[t.receiver_account_id].balance -= t.amount
            reversed_total += t.amount
        short = [a.user.full_name for a in accounts.values() if a.balance < 0]
        if short:
            db.session.rollback()
            raise ApiError(f'Cannot reverse the simulation: {", ".join(short)} no longer hold(s) the simulated '
                           f'money.', 409, 'REVERSAL_IMPOSSIBLE')

    counts = {}

    def run(label, sql, params=None):
        counts[label] = db.session.execute(text(sql), params or {}).rowcount

    # IPs the presenter typed (transfers and logins) – auto-watchlisted ones are removed too.
    typed_ips = ({t.ip_address for t in sim_txns if t.ip_address}
                 | {ip for (ip,) in db.session.execute(text(
                     'SELECT DISTINCT ip_address FROM login_attempts WHERE is_simulated = 1 AND ip_address IS NOT NULL'))})
    counts['watchlist_typed_ips'] = 0
    if typed_ips:
        counts['watchlist_typed_ips'] = db.session.execute(
            text("DELETE FROM watchlist WHERE source = 'AUTO' AND entity_type = 'IP' AND entity_value IN :ips")
            .bindparams(bindparam('ips', expanding=True)), {'ips': list(typed_ips)}).rowcount
    in_ids = {'ids': ids or [0]}
    expanding = lambda sql: text(sql).bindparams(bindparam('ids', expanding=True))  # noqa: E731
    _close_cases(ids, counts, actor)
    _undo_receiver_blocks(ids, counts)
    for label, sql in (
        ('simulation_events', 'DELETE FROM simulation_events'),
        ('notifications', 'DELETE FROM notifications WHERE is_simulated = 1 OR transaction_id IN :ids'),
        ('alerts', 'DELETE FROM alerts WHERE is_simulated = 1 OR transaction_id IN :ids'),
        ('security_events', 'DELETE FROM security_events WHERE is_simulated = 1 OR transaction_id IN :ids'),
        ('login_attempts', 'DELETE FROM login_attempts WHERE is_simulated = 1'),
        ('transactions', 'DELETE FROM transactions WHERE id IN :ids'),
        ('simulation_runs', 'DELETE FROM simulation_runs'),
        ('watchlist', "DELETE FROM watchlist WHERE source = 'AUTO' AND (entity_value LIKE 'sim-atk-%' "
                      "OR entity_value LIKE '198.51.100.%')"),
        ('devices', "DELETE FROM devices WHERE fingerprint LIKE 'sim-atk-%'"),
    ):
        counts[label] = db.session.execute(expanding(sql) if ':ids' in sql else text(sql),
                                           in_ids if ':ids' in sql else {}).rowcount

    # last_txn_at back to what the remaining (real) history says.
    for account in Account.query.filter(Account.id.in_(touched or [0])).all():
        account.last_txn_at = db.session.execute(text(
            "SELECT MAX(txn_time) FROM transactions WHERE status = 'COMPLETED' "
            "AND (sender_account_id = :a OR receiver_account_id = :a)"), {'a': account.id}).scalar()
    run('unlocked_dummy_users', "UPDATE users SET status = 'ACTIVE', failed_login_count = 0, locked_until = NULL "
                               "WHERE is_demo = 1 AND status = 'LOCKED'")
    run('reset_failed_counts', 'UPDATE users SET failed_login_count = 0 WHERE is_demo = 1')

    counts['amount_reversed'] = float(reversed_total)
    write_audit('SIMULATION_RESET', 'system', None, counts, actor=actor)
    db.session.commit()
    return counts


# ── Fraud detection records (real data only) ───────────────────────────────

def _flagged_transactions(limit):
    """Payments on which the engine detected risk or asked the owner, newest first.
    The seeded sample history is not a detection record and is left out."""
    return (Transaction.query
            .filter(db.or_(Transaction.risk_score > 0, Transaction.confirmation_status.isnot(None)),
                    db.or_(Transaction.scenario_code.is_(None), Transaction.scenario_code != 'SEED_HISTORY'))
            .order_by(Transaction.id.desc()).limit(limit).all())


def _record(t):
    assessment = (RiskAssessment.query.filter_by(transaction_id=t.id).order_by(RiskAssessment.id).first())
    return {
        'transaction_id': t.id, 'txn_ref': t.txn_ref, 'amount': money(t.amount), 'payment_method': t.payment_method,
        'sender': t.sender_account.user.full_name, 'sender_upi': t.sender_account.upi_id,
        'receiver': t.receiver_account.user.full_name, 'receiver_upi': t.receiver_account.upi_id,
        'receiver_account_status': t.receiver_account.status,
        'source': 'Frauder attempt' if t.is_simulated else 'Customer payment',
        'risk_score': t.risk_score, 'risk_band': t.decision,
        'risk_factors': [{'code': h.rule_code, 'name': h.rule.name, 'weight': h.weight_applied, 'reason': h.reason}
                         for h in t.latest_hits()],
        'user_response': t.confirmation_response, 'responded_at': t.confirmation_responded_at.isoformat(
            timespec='seconds') if t.confirmation_responded_at else None,
        'otp': t.otp_dict() if t.status != 'UNDER_REVIEW' and t.confirmation_response == 'YES' else None,
        'status': t.frauder_label(), 'outcome_label': t.frauder_label(),
        'txn_time': t.txn_time.isoformat(timespec='seconds'),
        'detected_at': (assessment.created_at if assessment else t.decided_at or t.created_at).isoformat(
            timespec='seconds'),
    }


def records(limit=100):
    """What the fraud engine actually recorded: flagged transactions, flagged and
    blocked receiver accounts. Nothing here is typed in, hard-coded or seeded."""
    expire_confirmations()
    rows = [_record(t) for t in _flagged_transactions(limit)]
    blocks = ReceiverBlock.query.order_by(ReceiverBlock.id.desc()).limit(limit).all()
    accounts = {a.account_number: a for a in Account.query.all()}
    accounts.update({a.upi_id: a for a in accounts.values()})
    flagged = {}
    # Seeded starter entries are configuration, not detections: only the engine's
    # (AUTO) and analysts' (MANUAL) flags count.
    for w in (WatchlistEntry.query.filter(WatchlistEntry.is_active.is_(True), WatchlistEntry.source != 'SEED',
                                          WatchlistEntry.entity_type.in_(('UPI', 'ACCOUNT')))
              .order_by(WatchlistEntry.id.desc()).all()):
        account = accounts.get(w.entity_value)
        key = account.id if account else w.entity_value
        entry = flagged.setdefault(key, {
            'account_id': account.id if account else None,
            'name': account.user.full_name if account else None,
            'upi_id': account.upi_id if account else (w.entity_value if w.entity_type == 'UPI' else None),
            'account_number': account.account_number if account else (
                w.entity_value if w.entity_type == 'ACCOUNT' else None),
            'account_status': account.status if account else None,
            'reason': w.reason, 'source': w.source, 'flagged_at': w.created_at.isoformat(timespec='seconds')})
        entry['flagged_at'] = min(entry['flagged_at'], w.created_at.isoformat(timespec='seconds'))
    return {
        'summary': {
            'flagged_transactions': len(rows),
            'processing': sum(1 for r in rows if r['status'] == 'PROCESSING'),
            'successful': sum(1 for r in rows if r['status'] == 'SUCCESS'),
            'cancelled': sum(1 for r in rows if r['status'] == 'CANCELLED'),
            'user_yes': sum(1 for r in rows if r['user_response'] == 'YES'),
            'user_no': sum(1 for r in rows if r['user_response'] == 'NO'),
            'otp_verified': sum(1 for r in rows if (r['otp'] or {}).get('status') == 'VERIFIED'),
            'blocked_receivers': len({b.account_id for b in blocks if b.status == 'ACTIVE'}),
            'flagged_receivers': len(flagged),
        },
        'transactions': rows,
        'blocked_receivers': [b.to_dict() for b in blocks],
        'flagged_receivers': list(flagged.values()),
    }


def _undo_receiver_blocks(sim_txn_ids, counts):
    """Blocks caused by Frauder attempts are undone with them: the block records
    go, their watchlist flags go, and an account with no other active block is
    ACTIVE again. Blocks from genuine customer reports stay."""
    blocks = ReceiverBlock.query.filter(ReceiverBlock.transaction_id.in_(sim_txn_ids or [0])).all()
    accounts = {b.account for b in blocks}
    for block in blocks:
        db.session.delete(block)
    db.session.flush()
    for account in accounts:
        investigations.refresh_account_status(account)
        if ReceiverBlock.query.filter_by(account_id=account.id, status='ACTIVE').count():
            continue
        WatchlistEntry.query.filter(WatchlistEntry.source == 'AUTO',
                                    WatchlistEntry.entity_value.in_([account.upi_id, account.account_number]),
                                    WatchlistEntry.reason.like('Receiver blocked:%')).delete(synchronize_session=False)
    counts['receiver_blocks'] = len(blocks)


def _close_cases(sim_txn_ids, counts, actor):
    """Open investigation cases caused by Frauder attempts are closed (RESOLVED,
    recorded in the case history) and the accounts' restrictions re-derived.
    Decided cases are never touched: a permanent block stays permanent."""
    cases = InvestigationCase.query.filter(InvestigationCase.transaction_id.in_(sim_txn_ids or [0]),
                                           InvestigationCase.status.in_(OPEN_STATUSES)).all()
    for case in cases:
        previous, account_before = case.status, case.account.status
        case.status, case.decided_at = 'RESOLVED', now()
        case.decision_reason = 'Closed without a decision: the Frauder attempt that opened it was reset.'
        case.account.status = account_before
        db.session.flush()
        db.session.add(InvestigationAction(
            case_id=case.id, detective_id=actor.id if actor else None, account_id=case.account_id,
            action='CLOSED_BY_RESET', previous_case_status=previous, new_case_status='RESOLVED',
            previous_account_status=account_before, new_account_status=investigations.refresh_account_status(
                case.account), reason=case.decision_reason))
    counts['investigation_cases_closed'] = len(cases)
