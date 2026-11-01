"""DECISION_MODE=AUTO (the default): the risk band decides in the same request.
APPROVED band → completed, BLOCKED band → blocked, REVIEW band → held for the owner.

Payments are pinned to midday so R5 (odd hour) never adds to the score, and the
watch-listed receiver (R6) is re-weighted to land in each band."""
from datetime import datetime
from decimal import Decimal

from portal.extensions import db
from portal.helpers import analytics, payment_engine
from portal.models import Alert, FraudRule, User

from .conftest import balance

NOON = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)


def _pay(app, amount, upi='quickcash@fsbank', r6_weight=None, owner_must_confirm=False):
    with app.app_context():
        if r6_weight is not None:
            FraudRule.query.filter_by(code='R6').first().weight = r6_weight
            db.session.commit()
        rahul = User.query.filter_by(email='rahul@demo.bank').first()
        txn, _ = payment_engine.send_money(rahul, 'UPI', {'upi_id': upi}, Decimal(amount), txn_time=NOON,
                                           owner_must_confirm=owner_must_confirm)
        out = {'id': txn.id, 'status': txn.status, 'decision': txn.decision, 'score': txn.risk_score,
               'rules': sorted(r.rule_code for r in txn.triggered_rules), 'latency_ms': float(txn.latency_ms),
               'confirmation': txn.confirmation_status, 'reason': txn.final_reason or txn.risk_explanation,
               'blocked_alerts': Alert.query.filter_by(transaction_id=txn.id, alert_type='TRANSACTION_BLOCKED').count()}
        db.session.remove()
        return out


def test_low_score_with_a_rule_is_approved_automatically(app):
    t = _pay(app, 1000, r6_weight=20)
    assert t['rules'] == ['R6'] and t['score'] == 20 and t['decision'] == 'APPROVED'
    assert t['status'] == 'COMPLETED' and t['confirmation'] is None
    assert 'Approved automatically' in t['reason'] and 'R6' in t['reason']
    assert balance(app, 'rahul@demo.bank') == Decimal('249000')
    assert balance(app, 'quickcash@demo.bank') == Decimal('6000')


def test_review_band_waits_for_the_owner(app):
    t = _pay(app, 1000)
    assert t['score'] == 50 and t['decision'] == 'REVIEW'
    assert t['status'] == 'UNDER_REVIEW' and t['confirmation'] == 'PENDING'
    assert balance(app, 'rahul@demo.bank') == Decimal('250000')


def test_block_band_is_blocked_automatically(app):
    t = _pay(app, 1000, r6_weight=80)
    assert t['score'] == 80 and t['decision'] == 'BLOCKED'
    assert t['status'] == 'BLOCKED' and t['confirmation'] is None and t['blocked_alerts'] == 1
    assert 'Blocked automatically' in t['reason']
    assert balance(app, 'rahul@demo.bank') == Decimal('250000')
    assert balance(app, 'quickcash@demo.bank') == Decimal('5000')


def test_decision_is_made_within_the_request_in_milliseconds(app):
    t = _pay(app, 1000, r6_weight=80)
    assert t['status'] != 'PROCESSING' and t['latency_ms'] < 1000


def test_frauder_attempts_follow_the_score_too(app):
    assert _pay(app, 1000, r6_weight=80, owner_must_confirm=True)['status'] == 'BLOCKED'
    assert _pay(app, 1000, r6_weight=50, owner_must_confirm=True)['status'] == 'UNDER_REVIEW'


def test_overview_counts_each_outcome(app):
    _pay(app, 1000, r6_weight=20)          # auto-approved
    _pay(app, 1000, r6_weight=50)          # pending owner
    _pay(app, 1000, r6_weight=80)          # auto-blocked
    with app.app_context():
        totals = analytics.summary()['totals']
        db.session.remove()
    assert (totals['auto_approved'], totals['pending_owner'], totals['auto_blocked']) == (1, 1, 1)
    assert (totals['approved'], totals['under_review'], totals['blocked']) == (1, 1, 1)
