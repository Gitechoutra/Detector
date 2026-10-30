from portal.seeders.utils import exists, insert

RISK_CATEGORIES = [
    ('APPROVED', 'Approved', 0, 39, 'Transaction proceeds; no alert.', '#15803D'),
    ('REVIEW', 'Under Review', 40, 69, 'Transaction held; customer step-up verification and a medium alert.',
     '#B45309'),
    ('BLOCKED', 'Blocked', 70, 100, 'Transaction declined; high-priority alert.', '#B91C1C'),
]

# Also used by the demo reset to restore the default bands.
DEFAULT_BANDS = {code: (lo, hi) for code, _, lo, hi, _, _ in RISK_CATEGORIES}


def seed_risk_categories(conn):
    for code, label, lo, hi, action, color in RISK_CATEGORIES:
        if not exists(conn, 'risk_categories', 'code', code):
            insert(conn, 'risk_categories', {'code': code, 'label': label, 'min_score': lo, 'max_score': hi,
                                             'action': action, 'color': color})
