from sqlalchemy import bindparam, text

from portal.extensions import db
from portal.models import User
from portal.helpers.audit import write_audit
from portal.helpers.responses import ApiError
from portal.seeders.seed_risk_categories import DEFAULT_BANDS

DEMO_CREDENTIALS = [
    {'role': 'USER', 'label': 'User (sender)', 'name': 'Rahul Sharma', 'email': 'rahul@demo.bank',
     'password': 'Rahul@123', 'what': 'Sends money manually by UPI, QR code or bank transfer.'},
    {'role': 'USER', 'label': 'User (sender)', 'name': 'Karan Mehta', 'email': 'karan@demo.bank',
     'password': 'Karan@123', 'what': 'Second sender, useful to show per-customer history.'},
    {'role': 'RECEIVER', 'label': 'Receiver', 'name': 'Priya Patel', 'email': 'priya@demo.bank',
     'password': 'Priya@123', 'what': 'Receives money; credited only when a payment is approved.'},
    {'role': 'RECEIVER', 'label': 'Receiver', 'name': 'Amit Verma', 'email': 'amit@demo.bank',
     'password': 'Amit@123', 'what': 'Second clean receiver.'},
    {'role': 'RECEIVER', 'label': 'Receiver (watch-listed)', 'name': 'QuickCash Services',
     'email': 'quickcash@demo.bank', 'password': 'Quick@123',
     'what': 'On the watchlist: paying it fires R6 (send to quickcash@fsbank).'},
    {'role': 'USER', 'label': 'User (dormant demo)', 'name': 'Suresh Nair', 'email': 'suresh@demo.bank',
     'password': 'Suresh@123', 'what': 'Account opened long ago and never used – the designated R8 victim.'},
    {'role': 'DETECTION', 'label': 'Detection System (optional)', 'name': 'Detection Officer',
     'email': 'analyst@demo.bank', 'password': 'Detect@123',
     'what': 'Optional monitoring dashboard: every transaction, alert and rule.'},
    {'role': 'FRAUDER', 'label': 'Frauder', 'name': 'Fraud Simulator', 'email': 'frauder@demo.bank',
     'password': 'Fraud@123', 'what': 'You play the attacker by hand on the designated demo victim accounts.'},
]

GUIDE = [
    {'title': 'Genuine payment', 'detail': 'Log in as Rahul (User) and send ₹500 to priya@fsbank. It is APPROVED '
                                           'and Rahul’s balance drops by ₹500.'},
    {'title': 'Receiver credited', 'detail': 'Log in as Priya (Receiver) in another tab: the ₹500 is credited.'},
    {'title': 'Become the attacker', 'detail': 'Log in as the Frauder. Pick the victim (Rahul), try logins, choose '
                                               'an unknown device or another city – every step is yours.'},
    {'title': 'Attempt a transfer', 'detail': 'Enter an amount and receiver and press Send. The SQL rules run '
                                              'automatically and the screen shows each rule, score and decision.'},
    {'title': 'Show the 9 rules', 'detail': 'Use “Test the 9 Fraud Detection Rules”: each card explains what to do; '
                                            '“Fill the form” only pre-fills – you still press the buttons.'},
    {'title': 'Prove nothing moved', 'detail': 'Blocked and held attempts leave both balances unchanged – check '
                                               'Rahul’s and Priya’s dashboards. Rahul also sees security alerts.'},
    {'title': 'Reset', 'detail': '“Reset fraud attempts” reverses only Frauder transfers. “Reset all demo data” '
                                 'wipes everything back to the start.'},
]



def info():
    return {'credentials': DEMO_CREDENTIALS, 'guide': GUIDE}


def frauder_user():
    return User.query.filter_by(email='frauder@demo.bank').first()


def reset(actor=None, restore_rules=True):
    """Clears all transactional data and restores seeded balances, watchlist and
    (optionally) rule weights. Users, roles, rules and the audit trail are kept."""
    statements = [
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
    write_audit('DEMO_RESET', 'system', None, {'rows': counts, 'rules_restored': restore_rules}, actor=actor)
    db.session.commit()
    return counts


def reset_simulation(actor=None):
    """Undo only what the Frauder did, leaving every genuine payment,
    registered user and unrelated record alone.

    Money is restored by reversing each completed simulated payment (sender
    gets it back, receiver gives it back), so balances return to exactly what
    they would be had the simulation never run – even if people also made real
    payments in between."""
    from portal.models import Account, Transaction
    from portal.helpers.payment_engine import _lock_accounts

    sim_txns = Transaction.query.filter_by(is_simulated=True).all()
    ids = [t.id for t in sim_txns]
    touched = {t.sender_account_id for t in sim_txns} | {t.receiver_account_id for t in sim_txns}

    completed = [t for t in sim_txns if t.status == 'COMPLETED']
    reversed_total = 0
    if completed:
        accounts = _lock_accounts(*{a for t in completed for a in (t.sender_account_id, t.receiver_account_id)})
        for t in completed:
            accounts[t.sender_account_id].balance += t.amount
            accounts[t.receiver_account_id].balance -= t.amount
            reversed_total += t.amount
        short = [a.user.full_name for a in accounts.values() if a.balance < 0]
        if short:
            db.session.rollback()
            raise ApiError(f'Cannot reverse the simulation: {", ".join(short)} no longer hold(s) the simulated '
                           f'money. Use the full demo reset instead.', 409, 'REVERSAL_IMPOSSIBLE')

    counts = {}

    def run(label, sql, params=None):
        counts[label] = db.session.execute(text(sql), params or {}).rowcount

    # IPs the presenter typed (transfers and logins) – auto-watchlisted ones are removed too.
    typed_ips = ({t.ip_address for t in sim_txns if t.ip_address}
                 | {ip for (ip,) in db.session.execute(text(
                     'SELECT DISTINCT ip_address FROM login_attempts WHERE is_simulated = 1 AND ip_address IS NOT NULL'))})
    counts['watchlist_typed_ips'] = 0
    if typed_ips:
        counts['watchlist_typed_ips'] = db.session.execute(
            text("DELETE FROM watchlist WHERE source = 'AUTO' AND entity_type = 'IP' AND entity_value IN :ips")
            .bindparams(bindparam('ips', expanding=True)), {'ips': list(typed_ips)}).rowcount
    in_ids = {'ids': ids or [0]}
    expanding = lambda sql: text(sql).bindparams(bindparam('ids', expanding=True))  # noqa: E731
    for label, sql in (
        ('simulation_events', 'DELETE FROM simulation_events'),
        ('notifications', 'DELETE FROM notifications WHERE is_simulated = 1 OR transaction_id IN :ids'),
        ('alerts', 'DELETE FROM alerts WHERE is_simulated = 1 OR transaction_id IN :ids'),
        ('security_events', 'DELETE FROM security_events WHERE is_simulated = 1 OR transaction_id IN :ids'),
        ('login_attempts', 'DELETE FROM login_attempts WHERE is_simulated = 1'),
        ('transactions', 'DELETE FROM transactions WHERE id IN :ids'),
        ('simulation_runs', 'DELETE FROM simulation_runs'),
        ('watchlist', "DELETE FROM watchlist WHERE source = 'AUTO' AND (entity_value LIKE 'sim-atk-%' "
                      "OR entity_value LIKE '198.51.100.%')"),
        ('devices', "DELETE FROM devices WHERE fingerprint LIKE 'sim-atk-%'"),
    ):
        counts[label] = db.session.execute(expanding(sql) if ':ids' in sql else text(sql),
                                           in_ids if ':ids' in sql else {}).rowcount

    # last_txn_at back to what the remaining (real) history says.
    for account in Account.query.filter(Account.id.in_(touched or [0])).all():
        account.last_txn_at = db.session.execute(text(
            "SELECT MAX(txn_time) FROM transactions WHERE status = 'COMPLETED' "
            "AND (sender_account_id = :a OR receiver_account_id = :a)"), {'a': account.id}).scalar()
    run('unlocked_demo_users', "UPDATE users SET status = 'ACTIVE', failed_login_count = 0, locked_until = NULL "
                               "WHERE is_demo = 1 AND status = 'LOCKED'")
    run('reset_failed_counts', 'UPDATE users SET failed_login_count = 0 WHERE is_demo = 1')

    counts['amount_reversed'] = float(reversed_total)
    write_audit('SIMULATION_RESET', 'system', None, counts, actor=actor)
    db.session.commit()
    return counts
