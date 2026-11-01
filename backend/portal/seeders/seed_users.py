"""Demo logins and their bank accounts. The Frauder's simulations also run on
these accounts, so their balances are the ones every dashboard shows."""
import secrets

import sqlalchemy as sa

from werkzeug.security import generate_password_hash

from portal.seeders.utils import exists, id_of, insert

# (email, name, role, password, city, phone, upi handle, opening balance, is_demo, is_simulated)
# Demo passwords are public demo credentials shown in Demo Mode, not secrets.
# Accounts opened long ago and never used since: the designated dormant demo
# account for R8. Applied only when the row is first created.
OPENED_DAYS_AGO = {'suresh@demo.bank': 400}

USERS = [
    ('rahul@demo.bank', 'Rahul Sharma', 'USER', 'Rahul@123', 'Mumbai', '9800000001', 'rahul', 250000, 1, 0),
    ('karan@demo.bank', 'Karan Mehta', 'USER', 'Karan@123', 'Delhi', '9800000002', 'karan', 150000, 1, 0),
    ('priya@demo.bank', 'Priya Patel', 'USER', 'Priya@123', 'Pune', '9800000003', 'priya', 25000, 1, 0),
    ('amit@demo.bank', 'Amit Verma', 'USER', 'Amit@123', 'Delhi', '9800000004', 'amit', 10000, 1, 0),
    ('quickcash@demo.bank', 'QuickCash Services', 'USER', 'Quick@123', 'Kolkata', '9800000005',
     'quickcash', 5000, 1, 0),
    ('analyst@demo.bank', 'Detection Officer', 'DETECTION', 'Detect@123', 'Mumbai', '9800000006', None, None, 1, 0),
    ('frauder@demo.bank', 'Fraud Simulator', 'FRAUDER', 'Fraud@123', 'Mumbai', '9800000007', None, None, 1, 0),
    # Designated dormant demo account (R8): opened long ago, never used.
    ('suresh@demo.bank', 'Suresh Nair', 'USER', 'Suresh@123', 'Kochi', '9800000008', 'suresh', 300000, 1, 0),
]


def seed_users(conn):
    for n, (email, name, role, password, city, phone, upi, balance, is_demo, is_sim) in enumerate(USERS, 1):
        if not exists(conn, 'users', 'email', email):
            insert(conn, 'users', {
                'role_id': id_of(conn, 'roles', 'code', role), 'full_name': name, 'email': email, 'phone': phone,
                'password_hash': generate_password_hash(password or secrets.token_urlsafe(32)),
                'home_location_id': id_of(conn, 'locations', 'city', city), 'is_demo': is_demo,
                'is_simulated': is_sim})
        elif is_demo and password:
            # A demo password typed straight into the DB is stored unhashed and
            # can never match at login; re-hash it (real hashes look like method$salt$hash).
            stored = conn.execute(sa.text('SELECT password_hash FROM users WHERE email = :e'), {'e': email}).scalar()
            if stored.count('$') < 2:
                conn.execute(sa.text('UPDATE users SET password_hash = :h WHERE email = :e'),
                             {'h': generate_password_hash(password), 'e': email})
        if upi is None:
            continue
        user_id = id_of(conn, 'users', 'email', email)
        if exists(conn, 'accounts', 'user_id', user_id):
            continue
        number = f'5010{n:08d}'
        if exists(conn, 'accounts', 'account_number', number) or exists(conn, 'accounts', 'upi_id', f'{upi}@fsbank'):
            number = f'5010{90000000 + n:08d}'
            if exists(conn, 'accounts', 'account_number', number) or exists(conn, 'accounts', 'upi_id',
                                                                                f'{upi}@fsbank'):
                continue
        insert(conn, 'accounts', {
            'user_id': user_id, 'account_number': number, 'ifsc': f'FSBK0{100 + n:06d}',
            'upi_id': f'{upi}@fsbank', 'qr_token': secrets.token_hex(8),
            'account_type': 'CURRENT' if email == 'quickcash@demo.bank' else 'SAVINGS',
            'balance': balance, 'opening_balance': balance})
        if email in OPENED_DAYS_AGO:
            conn.execute(sa.text('UPDATE users SET created_at = NOW() - INTERVAL :d DAY WHERE id = :u'),
                         {'d': OPENED_DAYS_AGO[email], 'u': user_id})
            conn.execute(sa.text('UPDATE accounts SET created_at = NOW() - INTERVAL :d DAY, last_txn_at = NULL '
                                 'WHERE user_id = :u'), {'d': OPENED_DAYS_AGO[email], 'u': user_id})
