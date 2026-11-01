from portal.seeders.utils import exists, insert

ROLES = [
    ('USER', 'User', 'Bank customer who sends and receives money.'),
    # Retired: customers now send and receive with one USER login. Kept for old references.
    ('RECEIVER', 'Receiver (retired)', 'Merged into User: every customer can send and receive.'),
    ('DETECTION', 'Detection System', 'Fraud team: monitors transactions, reviews alerts, manages rules.'),
    ('FRAUDER', 'Frauder', 'Runs controlled fraud simulations to test the detection system.'),
]


def seed_roles(conn):
    for code, name, description in ROLES:
        if not exists(conn, 'roles', 'code', code):
            insert(conn, 'roles', {'code': code, 'name': name, 'description': description})
