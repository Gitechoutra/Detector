"""Test-only: wipe transactional data and restore seeded balances, watchlist and
(optionally) rule weights before each test. Users, roles and rules are kept."""
from sqlalchemy import text

from portal.extensions import db
from portal.seeders.seed_risk_categories import DEFAULT_BANDS


def reset_data(restore_rules=True):
    """Clears all transactional data and restores seeded balances, watchlist and
    (optionally) rule weights. Users, roles, rules and the audit trail are kept."""
    statements = [
        'DELETE FROM detection_runs',
        'SET @fs_maintenance = 1',
        'DELETE FROM investigation_actions',
        'DELETE FROM investigation_cases',
        'SET @fs_maintenance = NULL',
        'DELETE FROM receiver_blocks',
        'DELETE FROM simulation_events',
        'DELETE FROM triggered_rules',
        'DELETE FROM risk_assessments',
        'DELETE FROM verification_challenges',
        'DELETE FROM notifications',
        'DELETE FROM alerts',
        'DELETE FROM security_events',
        'DELETE FROM login_attempts',
        'DELETE FROM transactions',
        'DELETE FROM simulation_runs',
        'DELETE FROM devices',
        "DELETE FROM watchlist WHERE source <> 'SEED'",
        'UPDATE watchlist SET is_active = 1',
        'UPDATE accounts SET balance = opening_balance, last_txn_at = NULL, status = \'ACTIVE\'',
        "UPDATE users SET status = 'ACTIVE', failed_login_count = 0, locked_until = NULL "
        "WHERE status <> 'SUSPENDED'",
    ]
    if restore_rules:
        statements.append('UPDATE fraud_rules SET weight = default_weight, params = default_params, is_active = 1')
    counts = {}
    for sql in statements:
        result = db.session.execute(text(sql))
        counts[sql.split()[2] if sql.startswith('DELETE') else sql.split()[1]] = result.rowcount
    if restore_rules:
        for code, (lo, hi) in DEFAULT_BANDS.items():
            db.session.execute(text('UPDATE risk_categories SET min_score = :lo, max_score = :hi WHERE code = :c'),
                               {'lo': lo, 'hi': hi, 'c': code})
    db.session.commit()
    return counts
