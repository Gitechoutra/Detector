from sqlalchemy import text

from portal.extensions import db


def _where(start=None, end=None, source=None, alias='t'):
    clauses, params = ['1=1'], {}
    if start:
        clauses.append(f'{alias}.txn_time >= :start')
        params['start'] = start
    if end:
        clauses.append(f'{alias}.txn_time < :end')
        params['end'] = end
    if source == 'manual':
        clauses.append(f'{alias}.is_simulated = 0')
    elif source == 'simulated':
        clauses.append(f'{alias}.is_simulated = 1')
    return ' AND '.join(clauses), params


def _rows(sql, params):
    return [dict(r) for r in db.session.execute(text(sql), params).mappings().all()]


def _f(value):
    return float(value) if value is not None else 0.0


def summary(start=None, end=None, source=None):
    where, params = _where(start, end, source)

    totals = db.session.execute(text(f"""
        SELECT COUNT(*) AS total,
               SUM(t.status = 'COMPLETED')    AS approved,
               SUM(t.status = 'UNDER_REVIEW') AS under_review,
               SUM(t.status = 'BLOCKED')      AS blocked,
               SUM(t.status IN ('DECLINED','CANCELLED','EXPIRED')) AS declined,
               SUM(ra.decision <> 'APPROVED') AS flagged,
               COALESCE(SUM(t.amount), 0)     AS volume,
               COALESCE(SUM(CASE WHEN t.status = 'BLOCKED' THEN t.amount END), 0) AS blocked_amount
        FROM transactions t
        JOIN risk_assessments ra ON ra.transaction_id = t.id AND ra.assessment_type = 'INITIAL'
        WHERE {where}"""), params).mappings().first()

    alert_where, alert_params = _where(start, end, source, alias='a')
    alert_where = alert_where.replace('a.txn_time', 'a.created_at')
    alerts = db.session.execute(text(f"""
        SELECT COUNT(*) AS total, SUM(a.status <> 'RESOLVED') AS open_alerts,
               SUM(a.severity = 'HIGH') AS high, SUM(a.resolution = 'CONFIRMED_FRAUD') AS confirmed
        FROM alerts a WHERE {alert_where}"""), alert_params).mappings().first()

    distribution = _rows(f"""
        SELECT LEAST(FLOOR(t.risk_score / 10), 9) AS bucket, COUNT(*) AS n
        FROM transactions t WHERE {where} AND t.risk_score IS NOT NULL
        GROUP BY bucket ORDER BY bucket""", params)
    buckets = {int(r['bucket']): r['n'] for r in distribution}

    top_rules = _rows(f"""
        SELECT tr.rule_code AS code, fr.name, COUNT(*) AS hits
        FROM triggered_rules tr
        JOIN risk_assessments ra ON ra.id = tr.assessment_id AND ra.assessment_type = 'INITIAL'
        JOIN transactions t ON t.id = tr.transaction_id
        JOIN fraud_rules fr ON fr.id = tr.rule_id
        WHERE {where}
        GROUP BY tr.rule_code, fr.name ORDER BY hits DESC""", params)

    by_method = _rows(f"""
        SELECT t.payment_method AS label, COUNT(*) AS total, SUM(ra.decision <> 'APPROVED') AS flagged
        FROM transactions t
        JOIN risk_assessments ra ON ra.transaction_id = t.id AND ra.assessment_type = 'INITIAL'
        WHERE {where} GROUP BY t.payment_method ORDER BY total DESC""", params)

    by_city = _rows(f"""
        SELECT l.city AS label, COUNT(*) AS total, SUM(ra.decision <> 'APPROVED') AS flagged
        FROM transactions t
        JOIN locations l ON l.id = t.location_id
        JOIN risk_assessments ra ON ra.transaction_id = t.id AND ra.assessment_type = 'INITIAL'
        WHERE {where} GROUP BY l.city ORDER BY total DESC LIMIT 10""", params)

    daily = _rows(f"""
        SELECT DATE(t.txn_time) AS day, COUNT(*) AS total, SUM(ra.decision <> 'APPROVED') AS flagged,
               COALESCE(SUM(t.amount), 0) AS amount
        FROM transactions t
        JOIN risk_assessments ra ON ra.transaction_id = t.id AND ra.assessment_type = 'INITIAL'
        WHERE {where} GROUP BY day ORDER BY day DESC LIMIT 14""", params)

    latencies = [float(r[0]) for r in db.session.execute(text(f"""
        SELECT t.latency_ms FROM transactions t WHERE {where} AND t.latency_ms IS NOT NULL
        ORDER BY t.id DESC LIMIT 2000"""), params).all()]

    return {
        'totals': {
            'total': totals['total'] or 0,
            'approved': int(totals['approved'] or 0),
            'under_review': int(totals['under_review'] or 0),
            'blocked': int(totals['blocked'] or 0),
            'declined': int(totals['declined'] or 0),
            'flagged': int(totals['flagged'] or 0),
            'volume': _f(totals['volume']),
            'blocked_amount': _f(totals['blocked_amount']),
            'alerts': alerts['total'] or 0,
            'open_alerts': int(alerts['open_alerts'] or 0),
            'high_alerts': int(alerts['high'] or 0),
            'confirmed_fraud': int(alerts['confirmed'] or 0),
        },
        'risk_distribution': [{'range': f'{b * 10}–{b * 10 + 9 if b < 9 else 100}', 'count': buckets.get(b, 0)}
                              for b in range(10)],
        'top_rules': top_rules,
        'by_method': [{**r, 'flagged': int(r['flagged'] or 0)} for r in by_method],
        'by_city': [{**r, 'flagged': int(r['flagged'] or 0)} for r in by_city],
        'daily': [{'day': str(r['day']), 'total': r['total'], 'flagged': int(r['flagged'] or 0),
                   'amount': _f(r['amount'])} for r in reversed(daily)],
        'latency': _latency(latencies),
        'rule_performance': rule_performance(),
        'detection_quality': detection_quality(start, end),
    }


def _percentile(values, pct):
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct / 100
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo), 2)


def _latency(values):
    return {'samples': len(values), 'p50_ms': _percentile(values, 50), 'p95_ms': _percentile(values, 95),
            'max_ms': round(max(values), 2) if values else None}


def rule_performance():
    """Per-rule precision from analyst outcomes, read from the v_rule_performance view."""
    rows = _rows('SELECT * FROM v_rule_performance ORDER BY code', {})
    for r in rows:
        resolved = int(r['confirmed_fraud'] or 0) + int(r['false_positive'] or 0)
        r['confirmed_fraud'] = int(r['confirmed_fraud'] or 0)
        r['false_positive'] = int(r['false_positive'] or 0)
        r['precision'] = round(r['confirmed_fraud'] / resolved, 3) if resolved else None
    return rows


def detection_quality(start=None, end=None):
    """Confusion matrix of the INITIAL decision against the ground-truth label
    carried by simulated transactions (flagged = REVIEW or BLOCKED)."""
    where, params = _where(start, end, 'simulated')
    row = db.session.execute(text(f"""
        SELECT SUM(t.is_fraud_label = 1 AND ra.decision <> 'APPROVED') AS tp,
               SUM(t.is_fraud_label = 0 AND ra.decision <> 'APPROVED') AS fp,
               SUM(t.is_fraud_label = 1 AND ra.decision =  'APPROVED') AS fn,
               SUM(t.is_fraud_label = 0 AND ra.decision =  'APPROVED') AS tn
        FROM transactions t
        JOIN risk_assessments ra ON ra.transaction_id = t.id AND ra.assessment_type = 'INITIAL'
        WHERE {where} AND t.is_fraud_label IS NOT NULL"""), params).mappings().first()
    tp, fp, fn, tn = (int(row[k] or 0) for k in ('tp', 'fp', 'fn', 'tn'))
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else None
    fpr = fp / (fp + tn) if fp + tn else None
    r = lambda v: round(v, 3) if v is not None else None  # noqa: E731
    return {'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn, 'precision': r(precision), 'recall': r(recall),
            'f1': r(f1), 'false_positive_rate': r(fpr), 'labelled': tp + fp + fn + tn}
