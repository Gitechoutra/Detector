"""Fraud investigation queue: a payment at the blocking threshold stops, the
sender is TEMPORARILY_BLOCKED and a case opens; a detective approves the account
(access restored) or blocks it permanently. Every action is in an append-only history."""
from decimal import Decimal

import pytest
from sqlalchemy import text

from portal.extensions import db
from portal.models import Account, InvestigationAction, InvestigationCase

from .conftest import answer, balance, login, send
from .test_frauder import fr  # noqa: F401  (fixture)


def _high_risk(client, amount=1000, weight=80):
    """Rahul pays the watch-listed QuickCash with R6 weighted to reach the threshold."""
    analyst = login(client, 'analyst@demo.bank')
    client.put('/api/detection/rules/R6', headers=analyst, json={'weight': weight})
    rahul = login(client, 'rahul@demo.bank')
    res = send(client, rahul, amount, upi='quickcash@fsbank')
    assert res.status_code == 201, res.get_json()
    return rahul, analyst, res.get_json()['data']


def _status(app, upi='rahul@fsbank'):
    with app.app_context():
        status = Account.query.filter_by(upi_id=upi).one().status
        db.session.remove()
        return status


def _queue(client, analyst, view='open', **params):
    return client.get('/api/detection/investigations', headers=analyst, query_string={'view': view, **params}).get_json()['data']


def _decide(client, analyst, case_id, decision, reason='Reviewed the evidence carefully.', confirm=True):
    return client.post(f'/api/detection/investigations/{case_id}/decision', headers=analyst,
                       json={'decision': decision, 'reason': reason, 'confirm': confirm})


# ── 2.1 Temporary block on detection ────────────────────────────────────────

def test_threshold_payment_is_stopped_restricted_and_queued(client, app):
    rahul, analyst, txn = _high_risk(client, 2500)
    assert txn['status'] == 'BLOCKED' and txn['money_moved'] is False
    assert balance(app, 'rahul@demo.bank') == Decimal('250000')
    assert balance(app, 'quickcash@demo.bank') == Decimal('5000')
    assert _status(app) == 'TEMPORARILY_BLOCKED'

    queue = _queue(client, analyst, 'pending')
    case = queue['items'][0]
    assert queue['meta']['total'] == 1 and case['status'] == 'TEMPORARILY_BLOCKED'
    assert case['customer']['name'] == 'Rahul Sharma' and case['account']['masked_number'].startswith('•••• ')
    assert case['transaction']['txn_ref'] == txn['txn_ref'] and case['transaction']['amount'] == 2500
    assert case['risk_score'] == 80 and [f['code'] for f in case['risk_factors']] == ['R6']
    assert case['risk_factors'][0]['weight'] == 80 and 'blocking threshold' in case['detection_reason']

    notes = client.get('/api/notifications', headers=rahul).get_json()['data']['items']
    assert any('temporarily restricted' in n['title'] for n in notes)
    dash = client.get('/api/user/dashboard', headers=rahul).get_json()['data']
    assert dash['restriction']['status'] == 'TEMPORARILY_BLOCKED' and dash['restriction']['case_ref'] == case['case_ref']


def test_restricted_account_cannot_send_by_any_route(client, app, fr):
    rahul, analyst, _ = _high_risk(client)
    priya = client.get('/api/user/dashboard', headers=login(client, 'priya@demo.bank')).get_json()['data']['account']
    for body in ({'payment_method': 'UPI', 'upi_id': 'priya@fsbank', 'amount': 10},
                 {'payment_method': 'QR', 'qr_payload': priya['qr_payload'], 'amount': 10},
                 {'payment_method': 'BANK_TRANSFER', 'account_number': priya['account_number'], 'ifsc': priya['ifsc'],
                  'amount': 10}):
        res = client.post('/api/transactions/send', headers=rahul, json=body)
        assert res.status_code == 423 and res.get_json()['error']['code'] == 'ACCOUNT_TEMPORARILY_BLOCKED'
    attempt = client.post('/api/frauder/transfer', headers=fr.headers, json={
        'victim_id': fr.ids['rahul'], 'receiver_id': fr.ids['priya'], 'amount': 10})
    assert attempt.status_code == 423
    # A restricted account can still receive money.
    assert send(client, login(client, 'karan@demo.bank'), 100, upi='rahul@fsbank').status_code == 201
    assert balance(app, 'priya@demo.bank') == Decimal('25000')


def test_payment_held_before_the_restriction_cannot_be_completed(client, app):
    rahul = login(client, 'rahul@demo.bank')
    analyst = login(client, 'analyst@demo.bank')
    held = send(client, rahul, 500, upi='quickcash@fsbank').get_json()['data']          # R6 50 → held for owner
    assert held['status'] == 'UNDER_REVIEW'
    client.put('/api/detection/rules/R6', headers=analyst, json={'weight': 80})
    assert send(client, rahul, 600, upi='quickcash@fsbank').get_json()['data']['status'] == 'BLOCKED'
    result = answer(client, rahul, held['id'], 'YES').get_json()['data']
    assert result['outcome'] == 'blocked' and 'restricted' in result['transaction']['final_reason']
    assert balance(app, 'quickcash@demo.bank') == Decimal('5000')


# ── Scenario 1: fraud confirmed → permanently blocked ───────────────────────

def test_scenario_fraud_confirmed_permanent_block(client, app):
    rahul, analyst, txn = _high_risk(client)
    case = _queue(client, analyst)['items'][0]
    started = client.post(f"/api/detection/investigations/{case['id']}/start", headers=analyst)
    assert started.status_code == 200 and started.get_json()['data']['status'] == 'UNDER_INVESTIGATION'
    assert _queue(client, analyst, 'under_investigation')['meta']['total'] == 1
    assert client.post(f"/api/detection/investigations/{case['id']}/start", headers=analyst).status_code == 409

    res = _decide(client, analyst, case['id'], 'PERMANENT_BLOCK', 'Confirmed mule activity with QuickCash.')
    assert res.status_code == 200
    data = res.get_json()['data']
    assert data['status'] == 'PERMANENTLY_BLOCKED' and data['decided_by'] == 'Detection Officer'
    assert _status(app) == 'PERMANENTLY_BLOCKED'
    assert _queue(client, analyst, 'open')['meta']['total'] == 0
    assert _queue(client, analyst, 'permanently_blocked')['meta']['total'] == 1
    assert _queue(client, analyst, 'resolved')['meta']['total'] == 1

    # No future transactions, in either direction, by any route.
    assert send(client, rahul, 10, upi='priya@fsbank').get_json()['error']['code'] == 'ACCOUNT_PERMANENTLY_BLOCKED'
    assert send(client, login(client, 'karan@demo.bank'), 10, upi='rahul@fsbank').status_code == 409
    # The decision cannot be changed afterwards.
    again = _decide(client, analyst, case['id'], 'APPROVE', 'Changing my mind about this.')
    assert again.status_code == 409 and again.get_json()['error']['code'] == 'CASE_ALREADY_DECIDED'
    assert _status(app) == 'PERMANENTLY_BLOCKED'
    notes = client.get('/api/notifications', headers=rahul).get_json()['data']['items']
    assert any(n['title'] == 'Your account has been permanently blocked' for n in notes)
    assert balance(app, 'rahul@demo.bank') == Decimal('250000')


# ── Scenario 2: legitimate → approved, access restored ──────────────────────

def test_scenario_legitimate_account_approved(client, app):
    rahul, analyst, txn = _high_risk(client, 3000)
    case = _queue(client, analyst)['items'][0]
    res = _decide(client, analyst, case['id'], 'APPROVE', 'Customer verified the payment by phone.')
    assert res.status_code == 200 and res.get_json()['data']['status'] == 'APPROVED'
    assert 'active again' in res.get_json()['message']
    assert _status(app) == 'ACTIVE'
    assert _queue(client, analyst, 'approved')['meta']['total'] == 1

    # The stopped payment stays stopped; new payments work again.
    detail = client.get(f"/api/user/transactions/{txn['id']}", headers=rahul).get_json()['data']
    assert detail['status'] == 'BLOCKED' and balance(app, 'quickcash@demo.bank') == Decimal('5000')
    assert send(client, rahul, 100, upi='priya@fsbank').get_json()['data']['status'] == 'COMPLETED'
    notes = client.get('/api/notifications', headers=rahul).get_json()['data']['items']
    assert any(n['title'] == 'Your account access has been restored' for n in notes)


# ── Scenario 3: pending → stays restricted ─────────────────────────────────

def test_scenario_pending_case_keeps_the_account_restricted(client, app):
    rahul, analyst, _ = _high_risk(client)
    for _ in range(2):
        assert send(client, rahul, 10, upi='priya@fsbank').status_code == 423
    assert _status(app) == 'TEMPORARILY_BLOCKED'
    case = _queue(client, analyst)['items'][0]
    client.post(f"/api/detection/investigations/{case['id']}/start", headers=analyst)
    assert send(client, rahul, 10, upi='priya@fsbank').status_code == 423       # still restricted during review


# ── 2.6 Validation, authorization, audit ────────────────────────────────────

def test_decisions_are_validated_on_the_server(client):
    _, analyst, _ = _high_risk(client)
    case_id = _queue(client, analyst)['items'][0]['id']
    assert _decide(client, analyst, case_id, 'DELETE').status_code == 422
    assert _decide(client, analyst, case_id, 'APPROVE', reason='short').status_code == 422
    res = _decide(client, analyst, case_id, 'APPROVE', confirm=False)
    assert res.status_code == 422 and res.get_json()['error']['code'] == 'CONFIRMATION_REQUIRED'
    assert _decide(client, analyst, 999999, 'APPROVE').status_code == 404


def test_only_detectives_can_see_or_decide_cases(client, fr):
    rahul, analyst, _ = _high_risk(client)
    case_id = _queue(client, analyst)['items'][0]['id']
    for headers in (rahul, fr.headers, login(client, 'priya@demo.bank')):
        assert client.get('/api/detection/investigations', headers=headers).status_code == 403
        assert client.get(f'/api/detection/investigations/{case_id}', headers=headers).status_code == 403
        assert _decide(client, headers, case_id, 'APPROVE').status_code == 403
        assert client.post(f'/api/detection/investigations/{case_id}/start', headers=headers).status_code == 403
    assert client.get('/api/detection/investigations').status_code == 401


def test_every_action_is_recorded_and_append_only(client, app):
    _, analyst, _ = _high_risk(client)
    case_id = _queue(client, analyst)['items'][0]['id']
    client.post(f'/api/detection/investigations/{case_id}/start', headers=analyst)
    _decide(client, analyst, case_id, 'APPROVE', 'Customer verified the payment by phone.')
    actions = client.get(f'/api/detection/investigations/{case_id}', headers=analyst).get_json()['data']['actions']
    assert [a['action'] for a in actions] == ['CASE_OPENED', 'REVIEW_STARTED', 'APPROVE']
    final = actions[-1]
    assert final['detective'] == 'Detection Officer' and final['reason'] == 'Customer verified the payment by phone.'
    assert (final['previous_account_status'], final['new_account_status']) == ('TEMPORARILY_BLOCKED', 'ACTIVE')
    assert (final['previous_case_status'], final['new_case_status']) == ('UNDER_INVESTIGATION', 'APPROVED')
    history = client.get('/api/detection/investigations/history', headers=analyst).get_json()['data']
    assert history['meta']['total'] == 3
    with app.app_context():
        for sql in ('UPDATE investigation_actions SET reason = NULL', 'DELETE FROM investigation_actions'):
            with pytest.raises(Exception, match='append-only'):
                db.session.execute(text(sql))
            db.session.rollback()
        db.session.remove()


def test_no_duplicate_case_for_the_same_event(client, app):
    _, analyst, txn = _high_risk(client)
    from portal.helpers import investigations
    from portal.models import Transaction
    with app.app_context():
        t = db.session.get(Transaction, txn['id'])
        first = investigations.open_case(t, t.sender_account, 'HIGH_RISK_PAYMENT', 'again')
        db.session.commit()
        assert InvestigationCase.query.count() == 1 and first.transaction_id == txn['id']
        assert InvestigationAction.query.filter_by(action='CASE_OPENED').count() == 1
        db.session.remove()


def test_queue_search_sort_and_views(client, app):
    _, analyst, txn = _high_risk(client)
    data = _queue(client, analyst, 'all', q=txn['txn_ref'])
    assert data['meta']['total'] == 1 and data['counts']['pending'] == 1 and data['counts']['resolved'] == 0
    assert _queue(client, analyst, 'all', q='nobody-like-this')['meta']['total'] == 0
    for sort in ('newest', 'oldest', 'risk', 'amount'):
        assert _queue(client, analyst, 'all', sort=sort)['meta']['total'] == 1
    assert client.get('/api/detection/investigations', headers=analyst, query_string={'view': 'nope'}).status_code == 422
    assert client.get('/api/detection/investigations', headers=analyst, query_string={'sort': 'nope'}).status_code == 422


def test_case_detail_has_everything_needed_to_decide(client, app):
    rahul = login(client, 'rahul@demo.bank')
    send(client, rahul, 300, upi='quickcash@fsbank')                  # an earlier suspicious payment
    _, analyst, txn = _high_risk(client)
    case_id = _queue(client, analyst)['items'][0]['id']
    d = client.get(f'/api/detection/investigations/{case_id}', headers=analyst).get_json()['data']
    assert d['transaction_detail']['txn_ref'] == txn['txn_ref'] and d['customer_detail']['email'] == 'rahul@demo.bank'
    assert d['account_detail']['status'] == 'TEMPORARILY_BLOCKED' and d['risk_score'] == 80
    assert len(d['rule_trace']) == 9 and any(r['status'] == 'TRIGGERED' for r in d['rule_trace'])
    assert d['previous_suspicious'] and d['alerts'] and d['actions'][0]['action'] == 'CASE_OPENED'


# ── Receivers blocked after an owner's NO are cases too ─────────────────────

def test_receiver_blocked_after_no_is_a_case_and_approval_restores_it(client, app):
    rahul = login(client, 'rahul@demo.bank')
    held = send(client, rahul, 700, upi='quickcash@fsbank').get_json()['data']
    answer(client, rahul, held['id'], 'NO')
    assert _status(app, 'quickcash@fsbank') == 'BLOCKED'
    analyst = login(client, 'analyst@demo.bank')
    case = _queue(client, analyst)['items'][0]
    assert case['case_type'] == 'RECEIVER_REPORTED' and case['customer']['name'] == 'QuickCash Services'
    _decide(client, analyst, case['id'], 'APPROVE', 'Merchant verified with KYC documents.')
    assert _status(app, 'quickcash@fsbank') == 'ACTIVE'
    blocks = client.get('/api/detection/receiver-blocks', headers=analyst).get_json()['data']
    assert blocks[0]['status'] == 'LIFTED'


def test_lifting_a_receiver_block_decides_its_case(client, app):
    rahul = login(client, 'rahul@demo.bank')
    held = send(client, rahul, 700, upi='quickcash@fsbank').get_json()['data']
    answer(client, rahul, held['id'], 'NO')
    analyst = login(client, 'analyst@demo.bank')
    block = client.get('/api/detection/receiver-blocks', headers=analyst).get_json()['data'][0]
    res = client.post(f"/api/detection/receiver-blocks/{block['id']}/lift", headers=analyst,
                      json={'reason': 'Merchant verified by phone'})
    assert res.status_code == 200 and _status(app, 'quickcash@fsbank') == 'ACTIVE'
    assert _queue(client, analyst, 'approved')['meta']['total'] == 1


def test_frauder_reset_closes_open_cases_but_keeps_decisions(client, app, fr):
    analyst = login(client, 'analyst@demo.bank')
    client.put('/api/detection/rules/R6', headers=analyst, json={'weight': 80})
    open_attempt = client.post('/api/frauder/transfer', headers=fr.headers, json={
        'victim_id': fr.ids['rahul'], 'receiver_id': fr.ids['quickcash'], 'amount': 1000}).get_json()['data']
    decided = client.post('/api/frauder/transfer', headers=fr.headers, json={
        'victim_id': fr.ids['karan'], 'receiver_id': fr.ids['quickcash'], 'amount': 1000}).get_json()['data']
    assert open_attempt['status'] == decided['status'] == 'BLOCKED'
    karan_case = _queue(client, analyst, 'all', q=decided['txn_ref'])['items'][0]
    _decide(client, analyst, karan_case['id'], 'PERMANENT_BLOCK', 'Account takeover confirmed by analyst.')
    client.post('/api/frauder/reset', headers=fr.headers, json={'confirm': 'RESET'})
    assert _status(app) == 'ACTIVE'                                    # Rahul's open case was closed by the reset
    assert _status(app, 'karan@fsbank') == 'PERMANENTLY_BLOCKED'       # a detective's decision is never undone
    counts = _queue(client, analyst, 'all')['counts']
    assert counts['open'] == 0 and counts['permanently_blocked'] == 1
    with app.app_context():
        assert InvestigationAction.query.filter_by(action='CLOSED_BY_RESET').count() == 1
        db.session.remove()


# ── Part 1: dashboard cards open real transaction lists ─────────────────────

def test_dashboard_cards_and_their_views(client, app):
    rahul = login(client, 'rahul@demo.bank')
    send(client, rahul, 100, upi='priya@fsbank')                                         # successful
    held = send(client, rahul, 200, upi='quickcash@fsbank').get_json()['data']           # pending → NO → cancelled
    answer(client, rahul, held['id'], 'NO')
    send(client, rahul, 250, upi='amit@fsbank')                                          # successful
    send(client, login(client, 'karan@demo.bank'), 50, upi='rahul@fsbank')              # received
    pending = send(client, rahul, 300, upi='quickcash@fsbank')                           # QuickCash blocked → 409
    assert pending.status_code == 409
    stats = client.get('/api/user/dashboard', headers=rahul).get_json()['data']['stats']
    assert (stats['total'], stats['successful'], stats['failed'], stats['blocked'], stats['pending']) == (4, 3, 1, 0, 0)

    def view(name, **params):
        return client.get('/api/user/transactions', headers=rahul, query_string={'view': name, **params}).get_json()['data']
    assert view('all')['meta']['total'] == 4
    assert view('successful')['meta']['total'] == 3
    failed = view('failed')['items']
    assert len(failed) == 1 and failed[0]['final_reason'] == 'Account owner denied initiating this transaction.'
    assert view('received')['summary'] == {'view': 'received', 'count': 1, 'amount': 50.0}
    assert view('sent')['summary']['amount'] == 350.0
    assert view('all', q='Priya')['meta']['total'] == 1
    assert view('all', q=held['txn_ref'])['items'][0]['id'] == held['id']
    amounts = [t['amount'] for t in view('all', sort='amount_desc')['items']]
    assert amounts == sorted(amounts, reverse=True)
    assert view('all', page_size=2)['meta']['pages'] == 2
    assert client.get('/api/user/transactions', headers=rahul, query_string={'view': 'x'}).status_code == 422


def test_blocked_view_shows_reasons_and_rules(client, app):
    rahul, _, txn = _high_risk(client)
    items = client.get('/api/user/transactions', headers=rahul, query_string={'view': 'blocked'}).get_json()['data']['items']
    assert items[0]['id'] == txn['id'] and items[0]['rules'][0]['code'] == 'R6'
    assert 'temporarily restricted' in items[0]['final_reason']


# ── Detection overview cards open lists that match their numbers ───────────

def test_overview_cards_match_the_lists_they_open(client, app):
    rahul = login(client, 'rahul@demo.bank')
    send(client, rahul, 100, upi='priya@fsbank')                                  # approved
    held = send(client, rahul, 200, upi='quickcash@fsbank').get_json()['data']    # flagged (R6 50) → held
    answer(client, rahul, held['id'], 'NO')
    analyst = login(client, 'analyst@demo.bank')
    alert = client.get('/api/alerts', headers=analyst).get_json()['data']['items'][0]
    client.patch(f"/api/alerts/{alert['id']}", headers=analyst, json={'action': 'RESOLVE', 'resolution': 'CONFIRMED_FRAUD',
                                                                      'notes': 'confirmed'})
    totals = client.get('/api/analytics/summary', headers=analyst).get_json()['data']['totals']

    def count(path, **params):
        return client.get(path, headers=analyst, query_string=params).get_json()['data']['meta']['total']
    assert count('/api/detection/transactions') == totals['total']
    assert count('/api/detection/transactions', status='COMPLETED') == totals['approved']
    assert count('/api/detection/transactions', status='UNDER_REVIEW') == totals['under_review']
    assert count('/api/detection/transactions', status='BLOCKED') == totals['blocked']
    assert count('/api/detection/transactions', flagged='1') == totals['flagged'] == 1
    assert count('/api/alerts') == totals['alerts']
    assert count('/api/alerts', status='RESOLVED', resolution='CONFIRMED_FRAUD') == totals['confirmed_fraud']
    slow = client.get('/api/detection/transactions', headers=analyst, query_string={'sort': 'latency'}).get_json()['data']
    latencies = [t['latency_ms'] for t in slow['items']]
    assert latencies == sorted(latencies, reverse=True)
    assert client.get('/api/detection/transactions', headers=analyst, query_string={'sort': ''}).status_code == 200
    assert client.get('/api/detection/transactions', headers=analyst, query_string={'sort': 'x'}).status_code == 422
