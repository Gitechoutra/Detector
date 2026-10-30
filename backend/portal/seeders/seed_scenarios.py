"""Retired catalogue of the old automatic Frauder scenarios (kept so historical
simulation records stay readable; marked inactive by migration 0006).

Scenarios run on the real demo accounts (senders Rahul / Karan, receivers
Priya / Amit / QuickCash). "Expected" is the outcome from a freshly reset demo:
the real decision always comes from the engine, so earlier activity on the same
account (velocity, history, travel) can legitimately change it."""
import json

import sqlalchemy as sa

from portal.seeders.utils import exists, insert

# (code, name, description, sender email, expected rules, expected decision, is_fraud)
SCENARIOS = [
    ('NORMAL_PAYMENT', 'Normal payment (control)',
     'Rahul pays Priya ₹1,250 from his usual device at home. Should be approved and Priya credited – shows '
     'genuine payments go straight through.', 'rahul@demo.bank', [], 'APPROVED', 0),
    ('UNAUTHORIZED_LOGIN', 'Unauthorized login attempts',
     'An attacker brute-forces Karan’s password from an unknown device. The account locks after 5 failures and '
     'the ₹25,000 transfer to Amit is refused.', 'karan@demo.bank', [], 'LOCKED', 1),
    ('RAPID_TRANSACTIONS', 'Multiple rapid transactions',
     'After a new-device login, six ₹46,000 transfers from Rahul to Amit fire in seconds – just under the '
     '₹50,000 reporting threshold.', 'rahul@demo.bank', ['R2', 'R4', 'R7', 'R9'], 'BLOCKED', 1),
    ('HIGH_VALUE', 'High-value suspicious transaction',
     'Rahul normally spends about ₹2,000. An attacker logs in on an unknown device and sends ₹80,000 to Priya.',
     'rahul@demo.bank', ['R1', 'R4', 'R9'], 'BLOCKED', 1),
    ('UNKNOWN_DEVICE_LOGIN', 'Unknown device login',
     'Login to Rahul’s account from a new device in Kolkata, followed immediately by ₹35,000 to Priya.',
     'rahul@demo.bank', ['R4', 'R9'], 'REVIEW', 1),
    ('IMPOSSIBLE_TRAVEL', 'Impossible travel',
     'Rahul pays Priya ₹500 in Mumbai; 3 minutes later his account sends ₹30,000 to Amit from Delhi '
     '(~1,150 km away).', 'rahul@demo.bank', ['R3', 'R4'], 'REVIEW', 1),
    ('BLACKLISTED_RECEIVER', 'Blacklisted receiver payment',
     'Rahul is tricked into paying ₹15,000 to QuickCash Services, which is on the watchlist.',
     'rahul@demo.bank', ['R6'], 'REVIEW', 1),
    ('DORMANT_REACTIVATION', 'Dormant account reactivation',
     'Karan’s account has been idle for 210 days; it suddenly sends ₹1,10,000 to Priya from a new device.',
     'karan@demo.bank', ['R1', 'R4', 'R8'], 'BLOCKED', 1),
    ('PHISHING_OTP', 'Phishing and fake OTP',
     'Rahul types his password into a fake KYC page. The fraudster logs in from Kolkata, enters wrong OTPs, then '
     'moves ₹44,000 to Amit.', 'rahul@demo.bank', ['R4', 'R9'], 'REVIEW', 1),
    ('ACCOUNT_TAKEOVER', 'Suspicious account takeover',
     'Four failed logins, then a successful login from a new device in Hyderabad, then ₹50,000 from Rahul to the '
     'watch-listed QuickCash.', 'rahul@demo.bank', ['R4', 'R6', 'R9'], 'BLOCKED', 1),
    ('ODD_HOUR', 'Odd-hour payment (genuine)',
     'Rahul pays Priya ₹15,000 at 02:47 (simulated clock) from his own device. R5 fires, but on its own it stays '
     'below the review threshold, so the payment is approved.', 'rahul@demo.bank', ['R5'], 'APPROVED', 0),
]


def _row(order, code, name, description, sender, rules, decision, is_fraud):
    return {'code': code, 'name': name, 'description': description, 'victim_email': sender,
            'expected_rules': json.dumps(rules), 'expected_decision': decision, 'is_fraud': is_fraud,
            'display_order': order, 'is_active': 1}


def seed_scenarios(conn):
    for order, scenario in enumerate(SCENARIOS):
        if not exists(conn, 'fraud_scenarios', 'code', scenario[0]):
            insert(conn, 'fraud_scenarios', _row(order, *scenario))


def refresh_scenarios(conn):
    """Insert missing scenarios and bring existing ones in line with the catalogue."""
    for order, scenario in enumerate(SCENARIOS):
        row = _row(order, *scenario)
        if exists(conn, 'fraud_scenarios', 'code', row['code']):
            sets = ', '.join(f'{k} = :{k}' for k in row if k != 'code')
            conn.execute(sa.text(f'UPDATE fraud_scenarios SET {sets} WHERE code = :code'), row)
        else:
            insert(conn, 'fraud_scenarios', row)
