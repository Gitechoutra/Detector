"""The predefined dummy accounts and their bank accounts.

Each account has a stable `seed_key` (rahul, karan, ...). Login emails and
passwords come from backend/.env (SEED_<KEY>_EMAIL / SEED_<KEY>_PASSWORD), with
backend/.env.example as the fallback, so no password lives in the source code.
seed_users() both creates missing accounts and synchronises existing ones
with the configured credentials. Accounts are matched by seed_key, so
changing an email in .env renames the account instead of creating a second one.

It runs from the migrations (`flask db upgrade`), from `flask seed`, and on
every application start (sync_on_startup), so a changed .env takes effect
after a restart."""
import logging
import os
import secrets
from collections import namedtuple

import sqlalchemy as sa
from werkzeug.security import check_password_hash, generate_password_hash

from portal.seeders.utils import exists, has_column, id_of, insert

log = logging.getLogger('portal.seed')

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENV_EXAMPLE = os.path.join(BACKEND_DIR, '.env.example')

SeedAccount = namedtuple('SeedAccount', 'key default_email name role city phone upi balance')

# Order matters: it fixes each account's number and IFSC (5010 0000 000<n>).
ACCOUNTS = [
    SeedAccount('rahul', 'rahul@demo.bank', 'Rahul Sharma', 'USER', 'Mumbai', '9800000001', 'rahul', 250000),
    SeedAccount('karan', 'karan@demo.bank', 'Karan Mehta', 'USER', 'Delhi', '9800000002', 'karan', 150000),
    SeedAccount('priya', 'priya@demo.bank', 'Priya Patel', 'USER', 'Pune', '9800000003', 'priya', 25000),
    SeedAccount('amit', 'amit@demo.bank', 'Amit Verma', 'USER', 'Delhi', '9800000004', 'amit', 10000),
    SeedAccount('quickcash', 'quickcash@demo.bank', 'QuickCash Services', 'USER', 'Kolkata', '9800000005',
                'quickcash', 5000),
    SeedAccount('analyst', 'analyst@demo.bank', 'Detection Officer', 'DETECTION', 'Mumbai', '9800000006', None, None),
    SeedAccount('frauder', 'frauder@demo.bank', 'Fraud Simulator', 'FRAUDER', 'Mumbai', '9800000007', None, None),
    # Dormant account for R8: opened long ago, never used.
    SeedAccount('suresh', 'suresh@demo.bank', 'Suresh Nair', 'USER', 'Kochi', '9800000008', 'suresh', 300000),
]
BY_KEY = {a.key: a for a in ACCOUNTS}
OPENED_DAYS_AGO = {'suresh': 400}


def env_name(key, field):
    return f'SEED_{key.upper()}_{field}'


def _example_values():
    values = {}
    try:
        with open(ENV_EXAMPLE, encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if line.startswith('SEED_') and '=' in line:
                    name, value = line.split('=', 1)
                    values[name.strip()] = value.strip()
    except OSError:
        pass
    return values


def _env_source():
    """The app's SEED_ACCOUNT_ENV mapping when one is configured (tests use an
    empty one so a developer's .env never changes test credentials), else os.environ."""
    try:
        from flask import current_app
        mapping = current_app.config.get('SEED_ACCOUNT_ENV')
    except RuntimeError:          # outside an application context
        mapping = None
    return os.environ if mapping is None else mapping


def configured_credentials():
    """{seed_key: (email, password)} from .env, falling back to .env.example.
    A value missing from both is None."""
    source, example = _env_source(), _example_values()
    creds = {}
    for account in ACCOUNTS:
        def value(field, default=None):
            name = env_name(account.key, field)
            return (source.get(name) or example.get(name) or default or '').strip() or None
        email = value('EMAIL', account.default_email)
        creds[account.key] = (email.lower() if email else None, value('PASSWORD'))
    return creds


def _password_matches(stored, password):
    try:
        return check_password_hash(stored, password)
    except (ValueError, TypeError):   # unhashed or malformed value typed straight into the DB
        return False


def _find_user(conn, account, email, keyed):
    if keyed:
        found = conn.execute(sa.text('SELECT id FROM users WHERE seed_key = :k'), {'k': account.key}).scalar()
        if found:
            return found
    for candidate in (email, account.default_email):
        if not candidate:
            continue
        row = conn.execute(sa.text('SELECT id' + (', seed_key' if keyed else '') + ' FROM users WHERE email = :e'),
                           {'e': candidate}).first()
        # Claim an unkeyed row only: another dummy account's row is never taken over.
        if row and (not keyed or row[1] in (None, account.key)):
            return row[0]
    return None


def _create_user(conn, account, email, password, keyed):
    if not password:
        raise RuntimeError(f'{env_name(account.key, "PASSWORD")} is not set. Add it to backend/.env '
                           f'(see backend/.env.example).')
    row = {'role_id': id_of(conn, 'roles', 'code', account.role), 'full_name': account.name, 'email': email,
           'phone': account.phone, 'password_hash': generate_password_hash(password),
           'home_location_id': id_of(conn, 'locations', 'city', account.city), 'is_demo': 1, 'is_simulated': 0}
    if keyed:
        row['seed_key'] = account.key
    insert(conn, 'users', row)
    log.info('Seeded dummy account %s (%s)', account.key, email)
    return id_of(conn, 'users', 'email', email)


def _sync_user(conn, user_id, account, email, password, keyed):
    """Bring an existing account in line with the configured credentials and role."""
    cols = 'email, password_hash, role_id' + (', seed_key' if keyed else '')
    row = conn.execute(sa.text(f'SELECT {cols} FROM users WHERE id = :id'), {'id': user_id}).mappings().first()
    updates, changed = {}, []
    if keyed and row['seed_key'] != account.key:
        updates['seed_key'] = account.key
    if email and row['email'] != email:
        taken = conn.execute(sa.text('SELECT id FROM users WHERE email = :e AND id <> :id'),
                             {'e': email, 'id': user_id}).scalar()
        if taken:
            log.warning('Cannot change %s to %s: another account already uses that email.',
                        account.key, email)
        else:
            updates['email'] = email
            changed.append('email')
    if password and not _password_matches(row['password_hash'], password):
        updates['password_hash'] = generate_password_hash(password)
        changed.append('password')
    role_id = id_of(conn, 'roles', 'code', account.role)
    if row['role_id'] != role_id:
        updates['role_id'] = role_id
        changed.append('role')
    if updates:
        sets = ', '.join(f'{k} = :{k}' for k in updates)
        conn.execute(sa.text(f'UPDATE users SET {sets}, is_demo = 1 WHERE id = :id'), {**updates, 'id': user_id})
    if changed:
        log.info('Synchronised dummy account %s from .env: %s', account.key, ', '.join(changed))
    return changed


def _ensure_bank_account(conn, n, account, user_id):
    if account.upi is None or exists(conn, 'accounts', 'user_id', user_id):
        return
    number = f'5010{n:08d}'
    upi = f'{account.upi}@fsbank'
    if exists(conn, 'accounts', 'account_number', number) or exists(conn, 'accounts', 'upi_id', upi):
        number = f'5010{90000000 + n:08d}'
        if exists(conn, 'accounts', 'account_number', number) or exists(conn, 'accounts', 'upi_id', upi):
            return
    insert(conn, 'accounts', {
        'user_id': user_id, 'account_number': number, 'ifsc': f'FSBK0{100 + n:06d}', 'upi_id': upi,
        'qr_token': secrets.token_hex(8), 'account_type': 'CURRENT' if account.key == 'quickcash' else 'SAVINGS',
        'balance': account.balance, 'opening_balance': account.balance})
    if account.key in OPENED_DAYS_AGO:
        days = OPENED_DAYS_AGO[account.key]
        conn.execute(sa.text('UPDATE users SET created_at = NOW() - INTERVAL :d DAY WHERE id = :u'),
                     {'d': days, 'u': user_id})
        conn.execute(sa.text('UPDATE accounts SET created_at = NOW() - INTERVAL :d DAY, last_txn_at = NULL '
                             'WHERE user_id = :u'), {'d': days, 'u': user_id})


def seed_users(conn):
    """Creates missing dummy accounts and synchronises existing ones with .env.
    Returns {seed_key: [what changed]} for accounts that changed."""
    keyed = has_column(conn, 'users', 'seed_key')     # added by migration 0009
    creds = configured_credentials()
    report = {}
    for n, account in enumerate(ACCOUNTS, 1):
        email, password = creds[account.key]
        user_id = _find_user(conn, account, email, keyed)
        if user_id is None:
            user_id = _create_user(conn, account, email, password, keyed)
            report[account.key] = ['created']
        else:
            changed = _sync_user(conn, user_id, account, email, password, keyed)
            if changed:
                report[account.key] = changed
        _ensure_bank_account(conn, n, account, user_id)
    return report


def sync_on_startup(app):
    """Applies .env credential changes whenever the app starts. Skipped (with a
    hint) until the database has been migrated; never stops the app from starting."""
    from portal.extensions import db
    with app.app_context():
        try:
            inspector = sa.inspect(db.engine)
            if not inspector.has_table('users') or 'seed_key' not in {c['name'] for c in
                                                                        inspector.get_columns('users')}:
                app.logger.info('Dummy-account sync skipped: run `flask db upgrade` first.')
                return
            with db.engine.begin() as conn:
                report = seed_users(conn)
            if report:
                app.logger.info('Dummy accounts synchronised with .env: %s', report)
        except sa.exc.OperationalError as exc:
            if getattr(exc.orig, 'args', [None])[0] == 1049:      # MySQL: unknown database
                app.logger.info('Database does not exist yet: run `flask init-db`.')
            else:
                app.logger.warning('Dummy-account sync failed: %s', exc)
        except Exception as exc:  # noqa: BLE001  (a sync problem must not stop the API)
            app.logger.warning('Dummy-account sync failed: %s', exc)
