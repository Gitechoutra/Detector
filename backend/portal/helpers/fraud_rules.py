"""The nine fraud rules, each a parameterised SQL query.

Every rule receives the transaction context (already INSERTed, same DB
transaction) and its parameters from fraud_rules.params, and returns None when
it does not fire or (reason, evidence) when it does. Time windows are anchored
on the transaction's own txn_time, never on NOW(), so evaluation is
reproducible and re-evaluation later gives the same answer for the same data.

Each rule also writes what it measured into ctx['trace'][code] as
{'observed': ..., 'threshold': ...}, fired or not, so the result screen can show
the actual value compared against the configured threshold for all nine rules.
"""
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import text

from portal.extensions import db


def _q(sql, **params):
    return db.session.execute(text(sql), params).mappings().first()


def _inr(value):
    return f'₹{Decimal(value):,.2f}'


def _trace(ctx, code, observed, threshold):
    ctx.setdefault('trace', {})[code] = {'observed': observed, 'threshold': threshold}


# R1 ── High amount: AVG() over an indexed per-account time range ───────────
R1_SQL = """
SELECT COUNT(*) AS n, AVG(amount) AS avg_amount
FROM transactions
WHERE sender_account_id = :acc
  AND status = 'COMPLETED'
  AND txn_time >= :since AND txn_time < :t
  AND id <> :tid
"""


def r1_high_amount(ctx, p):
    row = _q(R1_SQL, acc=ctx['sender_account_id'], tid=ctx['id'], t=ctx['txn_time'],
             since=ctx['txn_time'] - timedelta(days=p['lookback_days']))
    n, avg = row['n'], row['avg_amount']
    amount = ctx['amount']
    if n >= p['min_history_txns']:
        limit = Decimal(avg) * Decimal(str(p['multiplier']))
        _trace(ctx, 'R1', f'{_inr(amount)} vs average {_inr(avg)} of {n} payments',
               f"more than {p['multiplier']}× average = {_inr(limit)}")
        if amount > limit:
            return (f"{_inr(amount)} is {amount / Decimal(avg):.1f}× the {p['lookback_days']}-day "
                    f"average of {_inr(avg)}",
                    {'history_txns': n, 'average': float(avg), 'limit': float(limit)})
        return None
    # Not enough history for an average: fall back to an absolute ceiling.
    _trace(ctx, 'R1', f'{_inr(amount)} with only {n} past payment(s)',
           f"no history: at least {_inr(p['no_history_threshold'])}")
    if amount >= Decimal(str(p['no_history_threshold'])):
        return (f"{_inr(amount)} with only {n} past payment(s) exceeds the no-history limit of "
                f"{_inr(p['no_history_threshold'])}",
                {'history_txns': n, 'limit': p['no_history_threshold']})
    return None


# R2 ── Velocity: COUNT() over a sliding time window ─────────────────────────
R2_SQL = """
SELECT COUNT(*) AS n
FROM transactions
WHERE sender_account_id = :acc
  AND txn_time > :since AND txn_time <= :t
"""


def r2_velocity(ctx, p):
    n = _q(R2_SQL, acc=ctx['sender_account_id'], t=ctx['txn_time'],
           since=ctx['txn_time'] - timedelta(minutes=p['window_minutes']))['n']
    _trace(ctx, 'R2', f"{n} payment(s) in the last {p['window_minutes']} min",
           f"more than {p['max_txns']} in {p['window_minutes']} min")
    if n > p['max_txns']:
        return (f"{n} payments in {p['window_minutes']} minutes (limit {p['max_txns']})",
                {'count': n, 'window_minutes': p['window_minutes']})
    return None


# R3 ── Impossible travel: LAG() window function + TIMESTAMPDIFF() ───────────
R3_SQL = """
WITH seq AS (
    SELECT t.id, t.txn_time, t.location_id,
           LAG(t.location_id) OVER w AS prev_location_id,
           LAG(t.txn_time)    OVER w AS prev_txn_time
    FROM transactions t
    WHERE t.sender_account_id = :acc
      AND t.txn_time >= :since AND t.txn_time <= :t
    WINDOW w AS (ORDER BY t.txn_time, t.id)
)
SELECT pl.city AS prev_city, cl.city AS cur_city, s.prev_txn_time,
       TIMESTAMPDIFF(MINUTE, s.prev_txn_time, s.txn_time) AS gap_minutes,
       ST_Distance_Sphere(POINT(pl.longitude, pl.latitude),
                          POINT(cl.longitude, cl.latitude)) / 1000 AS distance_km
FROM seq s
JOIN locations cl ON cl.id = s.location_id
JOIN locations pl ON pl.id = s.prev_location_id
WHERE s.id = :tid
"""


def r3_impossible_travel(ctx, p):
    threshold = f"different city ≥ {p['min_distance_km']} km within {p['window_minutes']} min"
    if not ctx['location_id']:
        _trace(ctx, 'R3', 'no location recorded', threshold)
        return None
    row = _q(R3_SQL, acc=ctx['sender_account_id'], tid=ctx['id'], t=ctx['txn_time'],
             since=ctx['txn_time'] - timedelta(minutes=p['window_minutes']))
    if not row:
        _trace(ctx, 'R3', f"no earlier payment in the last {p['window_minutes']} min", threshold)
        return None
    km = float(row['distance_km'])
    _trace(ctx, 'R3', f"{row['prev_city']} → {row['cur_city']}: {km:,.0f} km in {row['gap_minutes']} min", threshold)
    if row['prev_city'] == row['cur_city']:
        return None
    if row['gap_minutes'] <= p['window_minutes'] and km >= p['min_distance_km']:
        return (f"{row['prev_city']} → {row['cur_city']} ({km:,.0f} km) in {row['gap_minutes']} min",
                {'from': row['prev_city'], 'to': row['cur_city'], 'minutes': row['gap_minutes'],
                 'distance_km': round(km)})
    return None


# R4 ── New device + high amount: NOT EXISTS against device history ──────────
R4_SQL = """
SELECT d.device_name, d.is_trusted,
       NOT EXISTS (SELECT 1 FROM transactions t
                   WHERE t.device_id = d.id AND t.status = 'COMPLETED' AND t.id <> :tid) AS first_use
FROM devices d
WHERE d.id = :device_id
"""


def r4_new_device_high_amount(ctx, p):
    threshold = f"untrusted, never-used device and amount above {_inr(p['amount_threshold'])}"
    if ctx['device_id'] is None:
        # No device information at all: nothing to judge the device on.
        _trace(ctx, 'R4', f'{_inr(ctx["amount"])}, no device information', threshold)
        return None
    row = _q(R4_SQL, device_id=ctx['device_id'], tid=ctx['id'])
    is_new = bool(row and not row['is_trusted'] and row['first_use'])
    device_label = (row['device_name'] if row else 'unknown') + (' (new, untrusted)' if is_new else
                                                                 ' (known)' if row else '')
    _trace(ctx, 'R4', f'{_inr(ctx["amount"])} from {device_label}', threshold)
    if ctx['amount'] <= Decimal(str(p['amount_threshold'])):
        return None
    if is_new:
        return (f"{_inr(ctx['amount'])} from a first-seen device ({row['device_name'] or 'unknown'}), "
                f"above {_inr(p['amount_threshold'])}",
                {'device': row['device_name'], 'threshold': p['amount_threshold']})
    return None


# R5 ── Odd-hour activity: HOUR() with an amount condition ───────────────────
R5_SQL = "SELECT HOUR(txn_time) AS hr FROM transactions WHERE id = :tid"


def r5_odd_hour(ctx, p):
    hour = _q(R5_SQL, tid=ctx['id'])['hr']
    _trace(ctx, 'R5', f"{_inr(ctx['amount'])} at {ctx['txn_time']:%H:%M}",
           f"between {p['start_hour']:02d}:00 and {p['end_hour']:02d}:00 and above {_inr(p['amount_threshold'])}")
    if p['start_hour'] <= hour < p['end_hour'] and ctx['amount'] > Decimal(str(p['amount_threshold'])):
        return (f"{_inr(ctx['amount'])} at {ctx['txn_time']:%H:%M}, inside the "
                f"{p['start_hour']:02d}:00–{p['end_hour']:02d}:00 risk window",
                {'hour': hour, 'threshold': p['amount_threshold']})
    return None


# R6 ── Watch-listed counterparty: JOIN against the watchlist ────────────────
R6_SQL = """
SELECT w.entity_type, w.entity_value, w.reason
FROM transactions t
JOIN accounts sa ON sa.id = t.sender_account_id
JOIN accounts ra ON ra.id = t.receiver_account_id
LEFT JOIN devices d ON d.id = t.device_id
JOIN watchlist w ON w.is_active = 1 AND (
       (w.entity_type = 'ACCOUNT' AND w.entity_value IN (ra.account_number, sa.account_number))
    OR (w.entity_type = 'UPI'     AND w.entity_value IN (ra.upi_id, sa.upi_id))
    OR (w.entity_type = 'DEVICE'  AND w.entity_value = d.fingerprint)
    OR (w.entity_type = 'IP'      AND w.entity_value = t.ip_address))
WHERE t.id = :tid
"""


def r6_watchlist(ctx, p):
    rows = db.session.execute(text(R6_SQL), {'tid': ctx['id']}).mappings().all()
    labels = ', '.join(f"{r['entity_type'].lower()} {r['entity_value']}" for r in rows)
    _trace(ctx, 'R6', f'matches: {labels}' if rows else 'no watch-listed account, UPI, device or IP',
           'any match on the active watchlist')
    if not rows:
        return None
    return (f"Watch-listed {labels}",
            {'matches': [{'type': r['entity_type'], 'value': r['entity_value'], 'reason': r['reason']}
                         for r in rows]})


# R7 ── Structuring: COUNT() with BETWEEN on amount ──────────────────────────
R7_SQL = """
SELECT COUNT(*) AS n
FROM transactions
WHERE sender_account_id = :acc
  AND txn_time > :since AND txn_time <= :t
  AND amount BETWEEN :low AND :high
"""


def r7_structuring(ctx, p):
    threshold = Decimal(str(p['reporting_threshold']))
    low = (threshold * (Decimal(100) - Decimal(str(p['band_percent']))) / 100).quantize(Decimal('0.01'))
    high = threshold - Decimal('0.01')
    limit = f"{p['min_count']}+ payments of {_inr(low)}–{_inr(high)} in {p['window_hours']} h"
    if not low <= ctx['amount'] <= high:
        _trace(ctx, 'R7', f"{_inr(ctx['amount'])} is outside the {_inr(low)}–{_inr(high)} band", limit)
        return None
    n = _q(R7_SQL, acc=ctx['sender_account_id'], t=ctx['txn_time'], low=low, high=high,
           since=ctx['txn_time'] - timedelta(hours=p['window_hours']))['n']
    _trace(ctx, 'R7', f"{n} payment(s) in the band in the last {p['window_hours']} h", limit)
    if n >= p['min_count']:
        return (f"{n} payments between {_inr(low)} and {_inr(high)} in {p['window_hours']} h, just under "
                f"the {_inr(threshold)} reporting threshold",
                {'count': n, 'band': [float(low), float(high)]})
    return None


# R8 ── Dormant reactivation: DATEDIFF() on accounts.last_txn_at ─────────────
R8_SQL = """
SELECT DATEDIFF(:t, COALESCE(last_txn_at, created_at)) AS idle_days,
       last_txn_at
FROM accounts
WHERE id = :acc
"""


def r8_dormant(ctx, p):
    row = _q(R8_SQL, acc=ctx['sender_account_id'], t=ctx['txn_time'])
    _trace(ctx, 'R8', f"{row['idle_days']} idle day(s), {_inr(ctx['amount'])}",
           f"at least {p['inactive_days']} idle days and {_inr(p['amount_threshold'])}")
    if ctx['amount'] < Decimal(str(p['amount_threshold'])):
        return None
    if row['idle_days'] is not None and row['idle_days'] >= p['inactive_days']:
        return (f"Account inactive for {row['idle_days']} days, now sending {_inr(ctx['amount'])}",
                {'idle_days': row['idle_days'], 'last_txn_at': str(row['last_txn_at'])})
    return None


# R9 ── Suspicious login / account takeover: JOINs on login & security events ─
# Login signals only count after the customer's last sign-in on a trusted
# device: a verified sign-in by the owner clears earlier failures.
R9_SINCE_SQL = """
SELECT GREATEST(:login_since, COALESCE((
    SELECT MAX(la.created_at) FROM login_attempts la
    JOIN devices d ON d.id = la.device_id AND d.is_trusted = 1
    WHERE la.user_id = :uid AND la.success = 1 AND la.created_at <= :t), :login_since)) AS since
"""

R9_SQL = """
SELECT
  (SELECT COUNT(*) FROM login_attempts la
    WHERE la.user_id = :uid AND la.success = 0
      AND la.created_at BETWEEN :since AND :t)                             AS failed_logins,
  (SELECT COUNT(*) FROM security_events se
    WHERE se.user_id = :uid AND se.event_type = 'OTP_FAILED'
      AND se.created_at BETWEEN :since AND :t)                             AS otp_failures,
  (SELECT MAX(la.created_at) FROM login_attempts la
    JOIN devices d ON d.id = la.device_id AND d.is_trusted = 0
    WHERE la.user_id = :uid AND la.success = 1 AND la.is_new_device = 1
      AND la.device_id = :device_id
      AND la.created_at BETWEEN :newdev_since AND :t)                      AS new_device_login_at,
  (SELECT lc.city FROM login_attempts la
    JOIN users u ON u.id = la.user_id
    JOIN locations lc ON lc.id = la.location_id
    WHERE la.user_id = :uid AND la.success = 1
      AND la.location_id <> u.home_location_id
      AND la.created_at BETWEEN :since AND :t
    ORDER BY la.created_at DESC LIMIT 1)                                   AS unusual_login_city,
  NOT EXISTS (SELECT 1 FROM transactions t
    WHERE t.sender_account_id = :acc AND t.receiver_account_id = :racc
      AND t.status = 'COMPLETED' AND t.id <> :tid)                         AS first_time_payee
"""


def r9_account_takeover(ctx, p):
    t = ctx['txn_time']
    since = _q(R9_SINCE_SQL, uid=ctx['sender_user_id'], t=t,
               login_since=t - timedelta(minutes=p['login_window_minutes']))['since']
    row = _q(R9_SQL, uid=ctx['sender_user_id'], acc=ctx['sender_account_id'],
             racc=ctx['receiver_account_id'], tid=ctx['id'], device_id=ctx['device_id'], t=t, since=since,
             newdev_since=t - timedelta(minutes=p['new_device_minutes']))
    signals = []
    if row['failed_logins'] >= p['failed_login_threshold']:
        signals.append(f"{row['failed_logins']} failed logins")
    if row['otp_failures'] >= p['otp_failure_threshold']:
        signals.append(f"{row['otp_failures']} wrong OTP entries")
    if row['new_device_login_at']:
        signals.append(f"new-device login {row['new_device_login_at']:%H:%M}")
    if row['unusual_login_city']:
        signals.append(f"login from {row['unusual_login_city']}")
    _trace(ctx, 'R9',
           f"{row['failed_logins']} failed login(s), {row['otp_failures']} wrong OTP(s), "
           f"new-device login: {'yes' if row['new_device_login_at'] else 'no'}, "
           f"away-from-home login: {row['unusual_login_city'] or 'no'}; amount {_inr(ctx['amount'])}",
           f"any of: {p['failed_login_threshold']}+ failed logins, {p['otp_failure_threshold']}+ wrong OTPs, "
           f"new-device login (≤{p['new_device_minutes']} min), away-from-home login – and amount ≥ "
           f"{_inr(p['min_amount'])}")
    if not signals or ctx['amount'] < Decimal(str(p['min_amount'])):
        return None
    if row['first_time_payee']:
        signals.append('first payment to this payee')
    return ('Possible account takeover: ' + ', '.join(signals),
            {'signals': signals, 'failed_logins': row['failed_logins'],
             'otp_failures': row['otp_failures'], 'first_time_payee': bool(row['first_time_payee'])})


RULE_FUNCTIONS = {
    'R1': r1_high_amount,
    'R2': r2_velocity,
    'R3': r3_impossible_travel,
    'R4': r4_new_device_high_amount,
    'R5': r5_odd_hour,
    'R6': r6_watchlist,
    'R7': r7_structuring,
    'R8': r8_dormant,
    'R9': r9_account_takeover,
}

# Rules about *who* is paying. A successful step-up (OTP to the registered
# customer + password) answers these; it says nothing about the payment
# pattern, so R1-R3, R5-R8 are never mitigated.
IDENTITY_RULES = ('R4', 'R9')
