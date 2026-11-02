"""Sample transaction history for the dummy accounts, so a freshly migrated
database has data for the Detection Engine to scan.

The history is the accounts' past: it happened before the seeded (opening)
balances, so it never changes a balance. Every row has a fixed reference
(SEED-0001...) and is inserted only if missing, so re-running never duplicates
it. Ordinary everyday payments are recent; the patterns that trip a rule are
older than 90 days, so they do not distort R1's 90-day averages for the
Frauder console. Dates are relative to the day the seeder runs."""
from datetime import datetime, timedelta

import sqlalchemy as sa

from portal.seeders.utils import exists, has_column, insert

SCENARIO = 'SEED_HISTORY'

# (days ago, HH:MM, sender, receiver, amount, city, remark) – senders/receivers are seed keys.
HISTORY = [
    # Everyday payments (recent)
    (55, '10:15', 'rahul', 'priya', 1200, 'Mumbai', 'Dinner split'),
    (41, '13:05', 'rahul', 'amit', 800, 'Mumbai', 'Books'),
    (28, '18:40', 'rahul', 'priya', 1500, 'Mumbai', 'Movie tickets'),
    (14, '11:20', 'rahul', 'amit', 2200, 'Mumbai', 'Electricity share'),
    (6, '09:45', 'rahul', 'priya', 950, 'Mumbai', 'Groceries'),
    (50, '12:00', 'karan', 'amit', 1800, 'Delhi', 'Lunch'),
    (33, '16:30', 'karan', 'priya', 3200, 'Delhi', 'Gift'),
    (12, '10:10', 'karan', 'amit', 2500, 'Delhi', 'Rent share'),
    (20, '19:00', 'priya', 'amit', 600, 'Pune', 'Snacks'),
    (18, '08:30', 'amit', 'priya', 400, 'Delhi', 'Cab fare'),
    # R2 velocity: six payments within five minutes – the sixth fires
    *[(110, f'14:0{i}', 'karan', 'amit', 300, 'Delhi', 'Quick transfer') for i in range(6)],
    # R1 high amount: far above Karan's average of the six above
    (108, '12:00', 'karan', 'priya', 40000, 'Delhi', 'Urgent payment'),
    # R7 structuring: three payments just under ₹50,000 within 24 h – the third fires
    (105, '11:00', 'rahul', 'amit', 46000, 'Mumbai', 'Invoice 1'),
    (105, '12:00', 'rahul', 'amit', 47500, 'Mumbai', 'Invoice 2'),
    (105, '13:00', 'rahul', 'amit', 48900, 'Mumbai', 'Invoice 3'),
    # R3 impossible travel: Mumbai, then Delhi 20 minutes later
    (100, '09:00', 'rahul', 'priya', 500, 'Mumbai', 'Coffee'),
    (100, '09:20', 'rahul', 'priya', 500, 'Delhi', 'Coffee'),
    # R5 odd hour: ₹12,000 at 02:40
    (97, '02:40', 'rahul', 'priya', 12000, 'Mumbai', 'Late-night transfer'),
    # R6 watchlist: payment to the watch-listed QuickCash
    (95, '15:00', 'rahul', 'quickcash', 3000, 'Mumbai', 'Loan app fee'),
]


def _ref(n):
    return f'SEED-{n:04d}'


def seed_transactions(conn):
    """Inserts any missing history rows. Needs the seed_key column (migration 0009)."""
    if not has_column(conn, 'users', 'seed_key') or not has_column(conn, 'transactions', 'simulated_details'):
        return 0
    accounts = dict(conn.execute(sa.text(
        'SELECT u.seed_key, a.id FROM users u JOIN accounts a ON a.user_id = u.id WHERE u.seed_key IS NOT NULL')).all())
    cities = dict(conn.execute(sa.text('SELECT city, id FROM locations')).all())
    today = datetime.now().replace(second=0, microsecond=0)
    inserted, touched = 0, {}
    for n, (days, hhmm, sender, receiver, amount, city, remark) in enumerate(HISTORY, 1):
        if sender not in accounts or receiver not in accounts or exists(conn, 'transactions', 'txn_ref', _ref(n)):
            continue
        hour, minute = map(int, hhmm.split(':'))
        at = (today - timedelta(days=days)).replace(hour=hour, minute=minute)
        insert(conn, 'transactions', {
            'txn_ref': _ref(n), 'sender_account_id': accounts[sender], 'receiver_account_id': accounts[receiver],
            'amount': amount, 'payment_method': 'UPI', 'remarks': remark, 'status': 'COMPLETED',
            'location_id': cities.get(city), 'scenario_code': SCENARIO, 'is_simulated': 0,
            'txn_time': at, 'decided_at': at, 'completed_at': at, 'created_at': at,
            'final_reason': 'Sample history seeded for the Detection Engine (before the opening balance).'})
        inserted += 1
        for account_id in (accounts[sender], accounts[receiver]):
            touched[account_id] = max(at, touched.get(account_id, at))
    # Activity dates follow the history (R8 dormancy); balances are left alone.
    for account_id, last in touched.items():
        conn.execute(sa.text('UPDATE accounts SET last_txn_at = GREATEST(COALESCE(last_txn_at, :t), :t) '
                             'WHERE id = :a'), {'t': last, 'a': account_id})
    return inserted
