from portal.seeders.utils import exists, insert

ROLES = [
    ('USER', 'User', 'Bank customer who sends money manually.'),
    ('RECEIVER', 'Receiver', 'Bank customer who receives money; credited only after approval.'),
    ('DETECTION', 'Detection System', 'Fraud team: monitors transactions, reviews alerts, manages rules.'),
    ('FRAUDER', 'Frauder', 'Runs controlled fraud simulations to test the detection system.'),
]


def seed_roles(conn):
    for code, name, description in ROLES:
        if not exists(conn, 'roles', 'code', code):
            insert(conn, 'roles', {'code': code, 'name': name, 'description': description})
