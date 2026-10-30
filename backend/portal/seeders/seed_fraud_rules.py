"""The nine fraud rules with default weights and thresholds. Existing rules are
never overwritten, so an analyst's tuning survives re-seeding."""
import json

from portal.seeders.utils import exists, insert

RULES = [
    ('R1', 'High transaction amount',
     "Amount far above the sender's normal: more than <multiplier> × the average of completed payments in the "
     "last <lookback_days> days. With fewer than <min_history_txns> past payments, fires at <no_history_threshold>.",
     'AVG() over an indexed per-account time range', 30,
     {'multiplier': 5, 'lookback_days': 90, 'min_history_txns': 3, 'no_history_threshold': 100000}),
    ('R2', 'Transaction velocity',
     'More than <max_txns> payments from the same account within <window_minutes> minutes.',
     'COUNT() over a sliding time window', 25, {'max_txns': 5, 'window_minutes': 10}),
    ('R3', 'Impossible travel',
     'Payment from a different city than the previous one, at least <min_distance_km> km away, within '
     '<window_minutes> minutes.',
     'LAG() window function, TIMESTAMPDIFF(), ST_Distance_Sphere()', 35,
     {'window_minutes': 30, 'min_distance_km': 100}),
    ('R4', 'New device + high amount',
     'Payment above <amount_threshold> from a device that is not trusted and has never completed a payment.',
     'NOT EXISTS against device history', 20, {'amount_threshold': 25000}),
    ('R5', 'Odd-hour transaction',
     'Payment above <amount_threshold> between <start_hour>:00 and <end_hour>:00.',
     'HOUR() with an amount condition', 10, {'start_hour': 0, 'end_hour': 5, 'amount_threshold': 10000}),
    ('R6', 'Watch-listed counterparty',
     'Sender or receiver account / UPI ID, device or IP address is on the active watchlist.',
     'JOIN against the watchlist table', 50, {}),
    ('R7', 'Transaction structuring',
     '<min_count> or more payments within <window_hours> h, each within <band_percent>% below the '
     '<reporting_threshold> reporting threshold.',
     'COUNT() with BETWEEN on amount', 15,
     {'reporting_threshold': 50000, 'band_percent': 10, 'min_count': 3, 'window_hours': 24}),
    ('R8', 'Dormant account reactivation',
     'Payment of at least <amount_threshold> from an account with no activity for <inactive_days> days.',
     'DATEDIFF() on accounts.last_txn_at', 20, {'inactive_days': 180, 'amount_threshold': 25000}),
    ('R9', 'Suspicious login / account takeover',
     'Payment of at least <min_amount> soon after: <failed_login_threshold>+ failed logins or '
     '<otp_failure_threshold>+ wrong OTPs (last <login_window_minutes> min), a login from a new untrusted device '
     '(last <new_device_minutes> min), or a login away from the home city.',
     'Correlated subqueries / JOINs on login_attempts, security_events, devices', 45,
     {'min_amount': 5000, 'failed_login_threshold': 3, 'otp_failure_threshold': 2,
      'login_window_minutes': 60, 'new_device_minutes': 15}),
]


def seed_fraud_rules(conn):
    for code, name, description, technique, weight, params in RULES:
        if not exists(conn, 'fraud_rules', 'code', code):
            insert(conn, 'fraud_rules', {
                'code': code, 'name': name, 'description': description, 'sql_technique': technique,
                'weight': weight, 'params': json.dumps(params), 'default_weight': weight,
                'default_params': json.dumps(params), 'is_active': 1})
