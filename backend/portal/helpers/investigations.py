"""Fraud investigations: accounts restricted by the engine wait here for a
detective, who approves them (access restored) or blocks them permanently.

Account statuses involved:
  TEMPORARILY_BLOCKED – a payment reached the blocking threshold; the account
                        cannot send until the case is decided.
  BLOCKED             – the account received a payment its payer's owner denied;
                        it cannot receive until the case is decided.
  PERMANENTLY_BLOCKED – a detective confirmed fraud; no sending or receiving.
The status is always derived from the open cases (refresh_account_status), and
every case action is written to the append-only investigation_actions table."""
import uuid

from sqlalchemy import text

from portal.extensions import db
from portal.helpers.audit import write_audit
from portal.helpers.helpers import inr, notify, raise_alert
from portal.helpers.responses import ApiError
from portal.models import (Account, Alert, InvestigationAction, InvestigationCase, ReceiverBlock, Transaction, now)
from portal.models.investigations import FINAL_STATUSES, OPEN_STATUSES, mask_account

SEND_OK = ('ACTIVE', 'BLOCKED')                     # BLOCKED only stops receiving
NO_RECEIVE = ('BLOCKED', 'PERMANENTLY_BLOCKED', 'FROZEN', 'CLOSED')
DECISIONS = {'PERMANENT_BLOCK': 'PERMANENTLY_BLOCKED', 'APPROVE': 'APPROVED'}
MIN_REASON = 10

# Queue views → case statuses.
VIEWS = {
    'pending': ('TEMPORARILY_BLOCKED',),
    'under_investigation': ('UNDER_INVESTIGATION',),
    'open': OPEN_STATUSES,
    'permanently_blocked': ('PERMANENTLY_BLOCKED',),
    'approved': ('APPROVED',),
    'resolved': FINAL_STATUSES,
    'all': OPEN_STATUSES + FINAL_STATUSES,
}


# ── Restrictions, enforced wherever money can move ─────────────────────────

def can_send(account):
    return account.status in SEND_OK


def can_receive(account):
    if account.status in NO_RECEIVE:
        return False
    return not ReceiverBlock.query.filter_by(account_id=account.id, status='ACTIVE').count()


def send_refusal(account):
    """(message, http status, code) for an account that may not send."""
    if account.status == 'TEMPORARILY_BLOCKED':
        return ('Your account is temporarily restricted while our fraud team investigates suspicious activity. '
                'Payments are disabled until the investigation is complete.', 423, 'ACCOUNT_TEMPORARILY_BLOCKED')
    if account.status == 'PERMANENTLY_BLOCKED':
        return ('Your account has been permanently blocked after a fraud investigation. Contact the bank.', 403,
                'ACCOUNT_PERMANENTLY_BLOCKED')
    return 'Your account is frozen. Contact the bank.', 409, 'ACCOUNT_FROZEN'


def refresh_account_status(account):
    """Derives the status from what is still open. A permanent block, FROZEN and
    CLOSED are never lifted automatically."""
    if account.status in ('PERMANENTLY_BLOCKED', 'FROZEN', 'CLOSED'):
        return account.status
    open_sender_case = InvestigationCase.query.filter(
        InvestigationCase.account_id == account.id, InvestigationCase.case_type == 'HIGH_RISK_PAYMENT',
        InvestigationCase.status.in_(OPEN_STATUSES)).count()
    receive_block = ReceiverBlock.query.filter_by(account_id=account.id, status='ACTIVE').count()
    account.status = 'TEMPORARILY_BLOCKED' if open_sender_case else 'BLOCKED' if receive_block else 'ACTIVE'
    return account.status


# ── Opening cases ───────────────────────────────────────────────────────────

def _factors(txn):
    return [{'code': h.rule_code, 'name': h.rule.name, 'weight': h.weight_applied, 'reason': h.reason}
            for h in txn.latest_hits()]


def _snapshot(txn):
    return {'txn_ref': txn.txn_ref, 'amount': float(txn.amount), 'payment_method': txn.payment_method,
            'sender': txn.sender_account.user.full_name, 'receiver': txn.receiver_account.user.full_name,
            'txn_time': txn.txn_time.isoformat(timespec='seconds'), 'is_simulated': txn.is_simulated}


def _record(case, action, account, prev_case, prev_account, reason, detective=None):
    db.session.add(InvestigationAction(
        case_id=case.id, detective_id=detective.id if detective else None, account_id=account.id, action=action,
        previous_case_status=prev_case, new_case_status=case.status, previous_account_status=prev_account,
        new_account_status=account.status, reason=(reason or '')[:500] or None))


def open_case(txn, account, case_type, reason):
    """Opens the case for one fraud event, or returns the existing one (never a duplicate)."""
    existing = InvestigationCase.query.filter_by(account_id=account.id, transaction_id=txn.id,
                                                 case_type=case_type).first()
    if existing:
        return existing
    case = InvestigationCase(case_ref='TMP-' + uuid.uuid4().hex[:14], account_id=account.id, transaction_id=txn.id,
                             case_type=case_type, status='TEMPORARILY_BLOCKED', detection_reason=reason[:500],
                             risk_score=txn.risk_score, risk_factors=_factors(txn), transaction_snapshot=_snapshot(txn),
                             account_status_at_open=account.status)
    db.session.add(case)
    db.session.flush()
    case.case_ref = f'CASE-{case.id:06d}'
    previous = account.status
    refresh_account_status(account)
    _record(case, 'CASE_OPENED', account, None, previous, reason)
    write_audit('INVESTIGATION_OPENED', 'investigation_case', case.id,
                {'case_ref': case.case_ref, 'account_id': account.id, 'transaction': txn.txn_ref, 'type': case_type})
    return case


def restrict_sender(txn, result):
    """A payment at or above the blocking threshold: stopped, the sender restricted
    and a case opened. Nothing is debited, whatever happens to the case later."""
    from portal.helpers.fraud_engine import band_floor
    from portal.helpers.payment_engine import _block, _lock_accounts, _phrases
    account = _lock_accounts(txn.sender_account_id)[txn.sender_account_id]
    codes = [h['code'] for h in result['hits']]
    reason = (f'Risk score {result["score"]} reached the blocking threshold of {band_floor("BLOCKED")} because '
              f'{_phrases(codes)}.')
    _block(txn, result, (f'Transaction stopped: {reason} Your account is temporarily restricted while our fraud team '
                         f'investigates. No money has left your account.')[:500])
    case = open_case(txn, account, 'HIGH_RISK_PAYMENT', reason)
    user = account.user
    notify(user.id, 'Suspicious activity detected – account temporarily restricted',
           f'We stopped {inr(txn.amount)} to {txn.receiver_account.user.full_name} ({txn.txn_ref}) and temporarily '
           f'restricted your account while our fraud team investigates (case {case.case_ref}). No money has left your '
           f'account. You will be notified when the investigation is complete.', 'DANGER', txn.id, txn.is_simulated)
    raise_alert('ACCOUNT_RESTRICTED', 'HIGH', f'Account restricted: {user.full_name} ({case.case_ref})',
                f'{inr(txn.amount)} to {txn.receiver_account.user.full_name} stopped. {reason} '
                f'Rules: {", ".join(codes)}.', user_id=user.id, transaction_id=txn.id, risk_score=result['score'],
                simulated=txn.is_simulated)
    return case


# ── Detective actions ───────────────────────────────────────────────────────

def _lock_case(case_id):
    db.session.execute(text('SELECT id FROM investigation_cases WHERE id = :id FOR UPDATE'), {'id': case_id})
    case = db.session.get(InvestigationCase, case_id, populate_existing=True)
    if case is None:
        raise ApiError('Investigation case not found.', 404, 'NOT_FOUND')
    return case


def start_review(detective, case_id, ip=None):
    case = _lock_case(case_id)
    if case.status != 'TEMPORARILY_BLOCKED':
        raise ApiError(f'This case is {case.status.replace("_", " ").lower()} and cannot be started again.', 409,
                       'CASE_NOT_PENDING')
    previous = case.status
    case.status, case.assigned_to, case.review_started_at = 'UNDER_INVESTIGATION', detective.id, now()
    _record(case, 'REVIEW_STARTED', case.account, previous, case.account.status, 'Investigation started.', detective)
    write_audit('INVESTIGATION_STARTED', 'investigation_case', case.id, {'case_ref': case.case_ref},
                actor=detective, ip=ip)
    db.session.commit()
    return case


def decide(detective, case_id, decision, reason, confirm, ip=None):
    """The final decision. Validated here, not only in the browser; the account's
    access changes in the same database transaction that records the decision."""
    from portal.helpers.payment_engine import _lock_accounts
    decision = (decision or '').strip().upper()
    if decision not in DECISIONS:
        raise ApiError('Choose PERMANENT_BLOCK or APPROVE.', 422, 'VALIDATION_ERROR', {'field': 'decision'})
    reason = (reason or '').strip()
    if len(reason) < MIN_REASON:
        raise ApiError(f'Give a reason of at least {MIN_REASON} characters.', 422, 'VALIDATION_ERROR',
                       {'field': 'reason'})
    if confirm is not True:
        raise ApiError('Confirm the decision before it is finalized.', 422, 'CONFIRMATION_REQUIRED',
                       {'field': 'confirm'})
    case = _lock_case(case_id)
    if not case.is_open:
        raise ApiError(f'This case was already closed ({case.status.replace("_", " ").lower()}). Decisions cannot be '
                       f'changed.', 409, 'CASE_ALREADY_DECIDED')
    account = _lock_accounts(case.account_id)[case.account_id]
    previous_case, previous_account = case.status, account.status
    case.status, case.decision, case.decision_reason = DECISIONS[decision], decision, reason[:500]
    case.decided_by, case.decided_at = detective.id, now()
    case.assigned_to = case.assigned_to or detective.id

    if decision == 'PERMANENT_BLOCK':
        account.status = 'PERMANENTLY_BLOCKED'
        # Other open cases on the same account are settled by this decision.
        for other in InvestigationCase.query.filter(InvestigationCase.account_id == account.id,
                                                    InvestigationCase.id != case.id,
                                                    InvestigationCase.status.in_(OPEN_STATUSES)).all():
            prior = other.status
            other.status, other.decided_by, other.decided_at = 'RESOLVED', detective.id, now()
            other.decision_reason = f'Closed by the permanent block in {case.case_ref}.'
            _record(other, 'CLOSED_BY_PERMANENT_BLOCK', account, prior, previous_account, other.decision_reason,
                    detective)
        notify(account.user_id, 'Your account has been permanently blocked',
               f'After investigating case {case.case_ref}, our fraud team has permanently blocked your account. '
               f'No payments can be made to or from it. Contact the bank if you believe this is a mistake.', 'DANGER')
        message = 'Account permanently blocked. All future transactions to and from it are refused.'
    else:
        if case.case_type == 'RECEIVER_REPORTED':
            for block in ReceiverBlock.query.filter_by(account_id=account.id, transaction_id=case.transaction_id,
                                                       status='ACTIVE').all():
                block.status, block.lifted_at, block.lifted_by = 'LIFTED', now(), detective.id
                block.lift_reason = f'Approved in {case.case_ref}: {reason}'[:255]
        db.session.flush()
        refresh_account_status(account)
        if not ReceiverBlock.query.filter_by(account_id=account.id, status='ACTIVE').count():
            from portal.models import WatchlistEntry
            WatchlistEntry.query.filter(WatchlistEntry.source == 'AUTO',
                                        WatchlistEntry.entity_value.in_([account.upi_id, account.account_number]),
                                        WatchlistEntry.reason.like('Receiver blocked:%')).update(
                {'is_active': False}, synchronize_session=False)
        if account.status == 'ACTIVE':
            notify(account.user_id, 'Your account access has been restored',
                   f'Our fraud team reviewed case {case.case_ref} and verified the activity as legitimate. Your '
                   f'account is active again and can send and receive payments.', 'SUCCESS')
            message = 'Account approved. The restriction was removed and the account is active again.'
        else:
            message = (f'Case approved, but the account stays {account.status.replace("_", " ").lower()} because '
                       f'another case on it is still open.')
    _record(case, decision, account, previous_case, previous_account, reason, detective)
    write_audit('INVESTIGATION_DECIDED', 'investigation_case', case.id,
                {'case_ref': case.case_ref, 'decision': decision, 'reason': reason, 'account_id': account.id,
                 'account_status': [previous_account, account.status]}, actor=detective, ip=ip)
    db.session.commit()
    return case, message


# ── Reading ─────────────────────────────────────────────────────────────────

def list_cases(view='open', q=None, sort='newest', page=1, size=20):
    from portal.models import User
    statuses = VIEWS.get(view)
    if statuses is None:
        raise ApiError(f'Unknown view. Use one of: {", ".join(VIEWS)}.', 422, 'VALIDATION_ERROR', {'field': 'view'})
    query = (InvestigationCase.query.join(Account, Account.id == InvestigationCase.account_id)
             .join(User, User.id == Account.user_id).filter(InvestigationCase.status.in_(statuses)))
    if q:
        like = f'%{q.strip()}%'
        query = query.filter(db.or_(InvestigationCase.case_ref.like(like), User.full_name.like(like),
                                    Account.upi_id.like(like), Account.account_number.like(like),
                                    InvestigationCase.transaction_snapshot['txn_ref'].as_string().like(like)))
    order = {'newest': InvestigationCase.opened_at.desc(), 'oldest': InvestigationCase.opened_at.asc(),
             'risk': InvestigationCase.risk_score.desc(),
             'amount': InvestigationCase.transaction_snapshot['amount'].as_float().desc()}.get(sort)
    if order is None:
        raise ApiError('Sort by newest, oldest, risk or amount.', 422, 'VALIDATION_ERROR', {'field': 'sort'})
    total = query.count()
    items = query.order_by(order, InvestigationCase.id.desc()).offset((page - 1) * size).limit(size).all()
    counts = dict(db.session.query(InvestigationCase.status, db.func.count()).group_by(InvestigationCase.status).all())
    return {
        'items': [c.to_dict() for c in items],
        'meta': {'page': page, 'page_size': size, 'total': total, 'pages': max(1, -(-total // size))},
        'counts': {name: sum(counts.get(s, 0) for s in statuses) for name, statuses in VIEWS.items()},
    }


def case_detail(case_id):
    case = db.session.get(InvestigationCase, case_id)
    if case is None:
        raise ApiError('Investigation case not found.', 404, 'NOT_FOUND')
    account, txn = case.account, case.transaction
    user = account.user
    related_ids = [txn.id] if txn else []
    suspicious = (Transaction.query.filter(
        db.or_(Transaction.sender_account_id == account.id, Transaction.receiver_account_id == account.id),
        Transaction.risk_score > 0, Transaction.id.notin_(related_ids or [0]))
        .order_by(Transaction.txn_time.desc()).limit(15).all())
    alerts = (Alert.query.filter(db.or_(Alert.transaction_id.in_(related_ids or [0]), Alert.user_id == user.id))
              .order_by(Alert.id.desc()).limit(20).all())
    actions = (InvestigationAction.query.filter_by(case_id=case.id).order_by(InvestigationAction.id).all())
    other_cases = (InvestigationCase.query.filter(InvestigationCase.account_id == account.id,
                                                  InvestigationCase.id != case.id)
                   .order_by(InvestigationCase.id.desc()).all())
    trace = []
    if txn:
        from portal.models import RiskAssessment
        first = RiskAssessment.query.filter_by(transaction_id=txn.id).order_by(RiskAssessment.id).first()
        trace = first.rule_trace if first else []
    data = case.to_dict()
    data.update({
        'customer_detail': {**user.to_dict(), 'phone': user.phone},
        'account_detail': {'id': account.id, 'masked_number': mask_account(account.account_number),
                           'upi_id': account.upi_id, 'ifsc': account.ifsc, 'type': account.account_type,
                           'status': account.status, 'balance': float(account.balance),
                           'opened_at': account.created_at.isoformat(timespec='seconds')},
        'transaction_detail': txn.to_dict() if txn else None,
        'rule_trace': trace,
        'previous_suspicious': [{**t.to_dict('user'), 'direction': 'OUT' if t.sender_account_id == account.id
                                 else 'IN'} for t in suspicious],
        'alerts': [a.to_dict() for a in alerts],
        'actions': [a.to_dict() for a in actions],
        'other_cases': [c.to_dict() for c in other_cases],
    })
    return data


def history(page=1, size=50, case_id=None):
    query = InvestigationAction.query
    if case_id:
        query = query.filter_by(case_id=case_id)
    total = query.count()
    items = query.order_by(InvestigationAction.id.desc()).offset((page - 1) * size).limit(size).all()
    return {'items': [a.to_dict() for a in items],
            'meta': {'page': page, 'page_size': size, 'total': total, 'pages': max(1, -(-total // size))}}


def open_case_for_user(user):
    """What the customer may see about their own restriction (no internal detail)."""
    account = user.primary_account
    if account is None or account.status not in ('TEMPORARILY_BLOCKED', 'PERMANENTLY_BLOCKED', 'BLOCKED'):
        return None
    case = (InvestigationCase.query.filter_by(account_id=account.id)
            .order_by(InvestigationCase.id.desc()).first())
    return {'status': account.status, 'case_ref': case.case_ref if case else None,
            'opened_at': case.opened_at.isoformat(timespec='seconds') if case else None,
            'case_status': case.status if case else None}
