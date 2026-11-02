"""Detection Engine: replays the nine SQL fraud rules over transactions that
are already stored – the dummy accounts' history and anything made since.

Each transaction is evaluated inside a SAVEPOINT that is rolled back, so a
scan never changes a payment, its status, its stored risk score or its rule
hits. Only the run's own results are saved (detection_runs).

The rules anchor on each payment's own time, so amount, velocity, travel,
hour, watchlist and structuring checks see the account as it was. R4 (device
first use) and R8 (dormancy, accounts.last_txn_at) read the account's current
state, so for older payments they show what the rule says today."""
import time
from collections import Counter
from datetime import timedelta

from portal.extensions import db
from portal.helpers import fraud_engine
from portal.helpers.audit import write_audit
from portal.helpers.responses import ApiError
from portal.models import Account, DetectionRun, FraudRule, Transaction, User, money, now

MAX_SCAN = 500


def scan_accounts():
    """The dummy accounts that hold a bank account (the senders a run can cover)."""
    users = (User.query.join(Account, Account.user_id == User.id)
             .filter(User.seed_key.isnot(None)).order_by(User.id).all())
    return [{'account_id': u.primary_account.id, 'name': u.full_name, 'upi_id': u.primary_account.upi_id,
             'seed_key': u.seed_key} for u in users]


def _query(account_id, days, include_simulated):
    dummy = [a['account_id'] for a in scan_accounts()]
    if account_id is not None and account_id not in dummy:
        raise ApiError('Choose one of the predefined dummy accounts.', 422, 'VALIDATION_ERROR',
                       {'field': 'account_id'})
    query = Transaction.query.filter(Transaction.sender_account_id.in_([account_id] if account_id else dummy),
                                     Transaction.status != 'PROCESSING')
    if days:
        query = query.filter(Transaction.txn_time >= now() - timedelta(days=days))
    if not include_simulated:
        query = query.filter(Transaction.is_simulated.is_(False))
    return query.order_by(Transaction.txn_time, Transaction.id)


def _evaluate_without_saving(txn):
    savepoint = db.session.begin_nested()
    try:
        result = fraud_engine.evaluate(txn, 'RE_EVALUATION', notes='Detection Engine scan (not saved)')
        return {'score': result['score'], 'band': result['decision'],
                'rules': [{'code': h['code'], 'name': h['name'], 'weight': h['weight'], 'reason': h['reason']}
                          for h in result['hits']]}
    finally:
        savepoint.rollback()


def _row(txn, found):
    stored = sorted(h.rule_code for h in txn.latest_hits())
    return {
        'id': txn.id, 'txn_ref': txn.txn_ref, 'txn_time': txn.txn_time.isoformat(timespec='seconds'),
        'sender': txn.sender_account.user.full_name, 'receiver': txn.receiver_account.user.full_name,
        'amount': money(txn.amount), 'status': txn.display_status(), 'outcome_label': txn.outcome_label(),
        'is_simulated': txn.is_simulated, 'seeded_history': txn.scenario_code == 'SEED_HISTORY',
        'city': txn.location.city if txn.location else None,
        'stored_score': txn.risk_score, 'stored_rules': stored,
        **found,
        'changed': txn.risk_score is not None and (txn.risk_score != found['score']
                                                   or stored != sorted(r['code'] for r in found['rules'])),
    }


def _summary(rows):
    by_rule, by_band, by_account = Counter(), Counter(), {}
    for r in rows:
        by_band[r['band']] += 1
        for hit in r['rules']:
            by_rule[hit['code']] += 1
        acc = by_account.setdefault(r['sender'], {'name': r['sender'], 'scanned': 0, 'flagged': 0, 'max_score': 0,
                                                   'amount_flagged': 0.0})
        acc['scanned'] += 1
        if r['rules']:
            acc['flagged'] += 1
            acc['amount_flagged'] += r['amount']
        acc['max_score'] = max(acc['max_score'], r['score'])
    names = {r.code: r.name for r in FraudRule.query.all()}
    return {
        'by_band': {band: by_band.get(band, 0) for band in ('APPROVED', 'REVIEW', 'BLOCKED')},
        'by_rule': [{'code': code, 'name': names.get(code, code), 'count': by_rule.get(code, 0)}
                    for code in sorted(names)],
        'by_account': sorted(by_account.values(), key=lambda a: (-a['flagged'], a['name'])),
        'amount_flagged': round(sum(r['amount'] for r in rows if r['rules']), 2),
        'changed_vs_stored': sum(1 for r in rows if r['changed']),
    }


def run(analyst, account_id=None, days=None, include_simulated=True, ip=None):
    started = time.perf_counter()
    query = _query(account_id, days, include_simulated)
    total = query.count()
    txns = query.all()[-MAX_SCAN:]               # the most recent ones if there are more
    rows = [_row(t, _evaluate_without_saving(t)) for t in txns]
    db.session.rollback()                        # nothing from the scan is kept

    rows.sort(key=lambda r: (-r['score'], r['txn_time']))
    flagged = sum(1 for r in rows if r['rules'])
    scope = {'account_id': account_id, 'days': days, 'include_simulated': include_simulated,
             'account': next((a['name'] for a in scan_accounts() if a['account_id'] == account_id), 'All dummy accounts'),
             'matched': total, 'limited_to': MAX_SCAN if total > MAX_SCAN else None}
    detection_run = DetectionRun(run_by=analyst.id, scope=scope, txns_scanned=len(rows), txns_flagged=flagged,
                                 summary=_summary(rows), results=rows,
                                 duration_ms=round((time.perf_counter() - started) * 1000, 2))
    db.session.add(detection_run)
    db.session.flush()
    write_audit('DETECTION_ENGINE_RUN', 'detection_run', detection_run.id,
                {'scanned': len(rows), 'flagged': flagged, 'scope': scope}, actor=analyst, ip=ip)
    db.session.commit()
    return detection_run
