"""Risk scoring: Risk(t) = min(100, Σ weight_i · hit_i(t)), mapped to a band.

evaluate() runs on the caller's session, inside the same DB transaction that
inserted the payment, so a transaction can never be committed without its
assessment and rule-hit evidence."""
import time

from portal.extensions import db
from portal.models import FraudRule, RiskAssessment, RiskCategory, TriggeredRule
from portal.helpers.fraud_rules import IDENTITY_RULES, RULE_FUNCTIONS


def decision_for(score):
    for band in RiskCategory.query.order_by(RiskCategory.min_score).all():
        if band.min_score <= score <= band.max_score:
            return band.code
    return 'BLOCKED'


def band_floor(code):
    band = RiskCategory.query.filter_by(code=code).first()
    return band.min_score if band else {'REVIEW': 40, 'BLOCKED': 70}.get(code, 0)


def transaction_context(txn):
    return {
        'id': txn.id,
        'sender_account_id': txn.sender_account_id,
        'receiver_account_id': txn.receiver_account_id,
        'sender_user_id': txn.sender_account.user_id,
        'amount': txn.amount,
        'txn_time': txn.txn_time,
        'device_id': txn.device_id,
        'ip_address': txn.ip_address,
        'location_id': txn.location_id,
    }


def evaluate(txn, assessment_type='INITIAL', step_up_verified=False, assessed_by=None, notes=None):
    """Runs every active rule against an already-flushed transaction and records
    the assessment. Returns dict(score, decision, hits, assessment)."""
    started = time.perf_counter()
    ctx = transaction_context(txn)
    all_rules = FraudRule.query.order_by(FraudRule.code).all()
    rules = [r for r in all_rules if r.is_active]

    hits, mitigations = [], []
    for rule in rules:
        fn = RULE_FUNCTIONS.get(rule.code)
        if fn is None:
            continue
        result = fn(ctx, rule.params)
        if result is None:
            continue
        reason, evidence = result
        if step_up_verified and rule.code in IDENTITY_RULES:
            mitigations.append({'code': rule.code, 'reason': reason,
                                'mitigated_by': 'Step-up verification (OTP + password) succeeded'})
            continue
        hits.append((rule, reason, evidence))

    # What every rule saw, fired or not, for the explainable result screen.
    fired = {rule.code: reason for rule, reason, _ in hits}
    mitigated = {m['code'] for m in mitigations}
    trace = []
    for rule in all_rules:
        seen = ctx.get('trace', {}).get(rule.code, {})
        status = ('DISABLED' if not rule.is_active else 'TRIGGERED' if rule.code in fired
                  else 'MITIGATED' if rule.code in mitigated else 'NOT_TRIGGERED')
        trace.append({'code': rule.code, 'name': rule.name, 'weight': rule.weight, 'status': status,
                      'observed': seen.get('observed'), 'threshold': seen.get('threshold'),
                      'reason': fired.get(rule.code)})

    score = min(100, sum(rule.weight for rule, _, _ in hits))
    decision = decision_for(score)
    latency = round((time.perf_counter() - started) * 1000, 2)

    assessment = RiskAssessment(
        transaction_id=txn.id, assessment_type=assessment_type, risk_score=score, decision=decision,
        rules_evaluated=len(rules), rules_triggered=len(hits), mitigations=mitigations or None, rule_trace=trace,
        latency_ms=latency, assessed_by=assessed_by.id if assessed_by else None, notes=notes)
    db.session.add(assessment)
    db.session.flush()

    for rule, reason, evidence in hits:
        db.session.add(TriggeredRule(
            transaction_id=txn.id, assessment_id=assessment.id, rule_id=rule.id, rule_code=rule.code,
            weight_applied=rule.weight, reason=reason[:255], evidence=evidence))
    db.session.flush()
    db.session.expire(txn, ['triggered_rules'])

    txn.risk_score = score
    txn.decision = decision
    return {
        'score': score,
        'decision': decision,
        'hits': [{'code': r.code, 'name': r.name, 'weight': r.weight, 'reason': reason}
                 for r, reason, _ in hits],
        'mitigations': mitigations,
        'trace': trace,
        'assessment': assessment,
    }
