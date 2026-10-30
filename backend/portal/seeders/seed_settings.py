from portal.seeders.utils import exists, insert

SETTINGS = [
    ('LOGIN_MAX_FAILURES', '5', 'Consecutive failed logins before the account is locked.'),
    ('LOGIN_LOCK_MINUTES', '15', 'How long a locked account stays locked.'),
    ('OTP_EXPIRY_MINUTES', '5', 'Validity of a step-up verification OTP.'),
    ('OTP_MAX_ATTEMPTS', '3', 'Wrong OTP/password entries before a held payment is declined.'),
    ('SIM_DEFAULT_INTERVAL_SECONDS', '6', 'Default delay between automatic simulation scenarios.'),
    ('MAX_TXN_AMOUNT', '1000000', 'Largest single payment accepted (₹).'),
    ('NEW_USER_OPENING_BALANCE', '50000', 'Simulated welcome balance for a newly registered User (sender).'),
    ('CONFIRMATION_EXPIRY_MINUTES', '30', 'How long the account owner has to answer "Was this you?".'),
    ('CONFIRMATION_EXPIRY_ACTION', 'BLOCK',
     'Unanswered confirmation: BLOCK the payment, or HOLD it for the fraud team. Never approved.'),
    ('CONFIRMATION_HARD_BLOCK_RULES', 'R6',
     'Comma-separated rules a YES from the account owner can never override (payment stays blocked).'),
]


def seed_settings(conn):
    for key, value, description in SETTINGS:
        if not exists(conn, 'system_settings', 'setting_key', key):
            insert(conn, 'system_settings', {'setting_key': key, 'setting_value': value, 'description': description})
