import sqlalchemy as sa

from portal.seeders.utils import insert

WATCHLIST = [
    ('UPI', 'quickcash@fsbank', 'Reported in multiple loan-app fraud complaints (demo receiver).'),
    ('UPI', 'shadowwallet@fsbank', 'Known mule wallet used to cash out stolen funds.'),
    ('IP', '203.0.113.66', 'IP linked to a phishing kit hosting provider.'),
    ('DEVICE', 'blacklisted-device-0001', 'Device fingerprint seen in previous account takeovers.'),
]


def _listed(conn, entity_type, value):
    return conn.execute(sa.text('SELECT 1 FROM watchlist WHERE entity_type = :t AND entity_value = :v'),
                        {'t': entity_type, 'v': value}).first()


def seed_watchlist(conn):
    for entity_type, value, reason in WATCHLIST:
        if not _listed(conn, entity_type, value):
            insert(conn, 'watchlist', {'entity_type': entity_type, 'entity_value': value, 'reason': reason,
                                       'source': 'SEED', 'is_active': 1})
    # The mule wallet's account number too, so bank transfers to it are caught as well.
    shadow = conn.execute(sa.text("SELECT account_number FROM accounts WHERE upi_id = 'shadowwallet@fsbank'")).scalar()
    if shadow and not _listed(conn, 'ACCOUNT', shadow):
        insert(conn, 'watchlist', {'entity_type': 'ACCOUNT', 'entity_value': shadow, 'source': 'SEED',
                                   'reason': 'Bank account behind the Shadow Wallet mule.', 'is_active': 1})
