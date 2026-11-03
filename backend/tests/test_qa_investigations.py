"""Investigation edge cases beyond the main A–D scenarios: what a permanently
blocked or approved account can do afterwards, repeated and late actions, two
open cases on one account, and the queue's paging and validation."""
from decimal import Decimal

import pytest

from portal.extensions import db
from portal.models import InvestigationAction, InvestigationCase, WatchlistEntry

from .conftest import answer, balance, login, send
from .test_investigations import _decide, _high_risk, _queue, _status


def _case_id(client, analyst, view='open'):
    return _queue(client, analyst, view)['items'][0]['id']


def test_permanently_blocked_account_can_neither_send_nor_receive(client, app):
    rahul, analyst, _ = _high_risk(client)
    assert _decide(client, analyst, _case_id(client, analyst), 'PERMANENT_BLOCK').status_code == 200
    assert _status(app) == 'PERMANENTLY_BLOCKED'

    res = send(client, rahul, 10)
    assert res.status_code == 403 and res.get_json()['error']['code'] == 'ACCOUNT_PERMANENTLY_BLOCKED'
    incoming = send(client, login(client, 'karan@demo.bank'), 10, upi='rahul@fsbank')
    assert incoming.status_code == 409 and incoming.get_json()['error']['code'] == 'RECEIVER_BLOCKED'
    lookup = client.post('/api/user/receivers/lookup', headers=login(client, 'karan@demo.bank'),
                         json={'payment_method': 'UPI', 'upi_id': 'rahul@fsbank'})
    assert lookup.status_code == 409
    assert balance(app, 'rahul@demo.bank') == Decimal('250000')


def test_permanently_blocked_customer_can_still_sign_in_and_see_why(client):
    _, analyst, _ = _high_risk(client)
    _decide(client, analyst, _case_id(client, analyst), 'PERMANENT_BLOCK')
    rahul = login(client, 'rahul@demo.bank')                     # a fresh session after the decision
    dash = client.get('/api/user/dashboard', headers=rahul).get_json()['data']
    assert dash['restriction']['status'] == 'PERMANENTLY_BLOCKED' and dash['restriction']['case_ref']
    notes = client.get('/api/notifications', headers=rahul).get_json()['data']['items']
    assert any(n['title'] == 'Your account has been permanently blocked' for n in notes)


def test_approved_account_can_pay_again_and_gets_a_notification(client, app):
    rahul, analyst, _ = _high_risk(client)
    client.put('/api/detection/rules/R6', headers=analyst, json={'weight': 50})     # back to the default
    assert _decide(client, analyst, _case_id(client, analyst), 'APPROVE').status_code == 200
    assert _status(app) == 'ACTIVE'
    res = send(client, rahul, 10)
    assert res.status_code == 201 and res.get_json()['data']['status'] == 'COMPLETED'
    titles = [n['title'] for n in client.get('/api/notifications', headers=rahul).get_json()['data']['items']]
    assert 'Your account access has been restored' in titles


def test_the_stopped_payment_is_never_released_by_an_approval(client, app):
    rahul, analyst, txn = _high_risk(client, 2500)
    _decide(client, analyst, _case_id(client, analyst), 'APPROVE')
    detail = client.get(f'/api/user/transactions/{txn["id"]}', headers=rahul).get_json()['data']
    assert detail['status'] == 'BLOCKED'
    assert balance(app, 'rahul@demo.bank') == Decimal('250000')
    assert balance(app, 'quickcash@demo.bank') == Decimal('5000')


@pytest.mark.parametrize('first', ['APPROVE', 'PERMANENT_BLOCK'])
def test_a_decided_case_cannot_be_decided_or_started_again(client, app, first):
    _, analyst, _ = _high_risk(client)
    case_id = _case_id(client, analyst)
    assert _decide(client, analyst, case_id, first).status_code == 200
    before = _status(app)
    for decision in ('APPROVE', 'PERMANENT_BLOCK'):
        res = _decide(client, analyst, case_id, decision)
        assert res.status_code == 409 and res.get_json()['error']['code'] == 'CASE_ALREADY_DECIDED'
    assert client.post(f'/api/detection/investigations/{case_id}/start', headers=analyst).status_code == 409
    assert _status(app) == before
    with app.app_context():
        assert InvestigationAction.query.filter_by(case_id=case_id, action=first).count() == 1
        db.session.remove()


def test_starting_a_review_twice_is_refused_and_logged_once(client, app):
    _, analyst, _ = _high_risk(client)
    case_id = _case_id(client, analyst)
    assert client.post(f'/api/detection/investigations/{case_id}/start', headers=analyst).status_code == 200
    again = client.post(f'/api/detection/investigations/{case_id}/start', headers=analyst)
    assert again.status_code == 409 and again.get_json()['error']['code'] == 'CASE_NOT_PENDING'
    assert _queue(client, analyst, 'under_investigation')['meta']['total'] == 1
    assert _queue(client, analyst, 'pending')['meta']['total'] == 0
    assert _status(app) == 'TEMPORARILY_BLOCKED'                # reviewing does not lift anything


@pytest.mark.parametrize('reason, ok', [('x' * 9, False), ('  ' + 'x' * 9 + '  ', False), ('x' * 10, True),
                                        ('x' * 2000, True), ('नमस्ते दुनिया 🙏🙏', True)])
def test_decision_reason_length_and_unicode(client, app, reason, ok):
    _, analyst, _ = _high_risk(client)
    case_id = _case_id(client, analyst)
    res = _decide(client, analyst, case_id, 'APPROVE', reason=reason)
    assert (res.status_code == 200) is ok, res.get_json()
    if ok:
        with app.app_context():
            stored = db.session.get(InvestigationCase, case_id).decision_reason
            assert stored == reason.strip()[:500]
            db.session.remove()


@pytest.mark.parametrize('confirm', [False, 'true', 1, None, 'yes'])
def test_decision_needs_an_explicit_boolean_confirmation(client, app, confirm):
    _, analyst, _ = _high_risk(client)
    res = _decide(client, analyst, _case_id(client, analyst), 'PERMANENT_BLOCK', confirm=confirm)
    assert res.status_code == 422 and res.get_json()['error']['code'] == 'CONFIRMATION_REQUIRED'
    assert _status(app) == 'TEMPORARILY_BLOCKED'


def test_unknown_case_is_404_everywhere(client):
    analyst = login(client, 'analyst@demo.bank')
    for res in (client.get('/api/detection/investigations/999999', headers=analyst),
                client.post('/api/detection/investigations/999999/start', headers=analyst),
                _decide(client, analyst, 999999, 'APPROVE')):
        assert res.status_code == 404


def test_sender_case_and_receiver_case_on_one_account(client, app):
    """Rahul's own payment gets him restricted (sender case), and then a payer denies
    a payment to him (receiver case). Approving one case keeps the other restriction."""
    rahul, analyst, _ = _high_risk(client)
    client.put('/api/detection/rules/R6', headers=analyst, json={'weight': 50})
    analyst_id = _case_id(client, analyst)

    with app.app_context():                                       # Karan → Rahul is then held
        db.session.add(WatchlistEntry(
            entity_type='UPI', entity_value='rahul@fsbank', reason='test', source='MANUAL'))
        db.session.commit()
        db.session.remove()
    karan = login(client, 'karan@demo.bank')
    held = send(client, karan, 100, upi='rahul@fsbank').get_json()['data']
    assert held['status'] == 'UNDER_REVIEW'
    assert answer(client, karan, held['id'], 'NO').status_code == 200
    assert _queue(client, analyst, 'open')['meta']['total'] == 2
    assert _status(app) == 'TEMPORARILY_BLOCKED'

    _decide(client, analyst, analyst_id, 'APPROVE')               # the sender case
    assert _status(app) == 'BLOCKED'                              # still cannot receive
    assert send(client, rahul, 10).status_code == 201             # but may send again
    receiver_case = _case_id(client, analyst)
    _decide(client, analyst, receiver_case, 'APPROVE')
    assert _status(app) == 'ACTIVE'


def test_permanent_block_closes_the_accounts_other_open_cases(client, app):
    rahul, analyst, _ = _high_risk(client)
    with app.app_context():
        db.session.add(WatchlistEntry(
            entity_type='UPI', entity_value='rahul@fsbank', reason='test', source='MANUAL'))
        db.session.commit()
        db.session.remove()
    client.put('/api/detection/rules/R6', headers=analyst, json={'weight': 50})
    karan = login(client, 'karan@demo.bank')
    held = send(client, karan, 100, upi='rahul@fsbank').get_json()['data']
    answer(client, karan, held['id'], 'NO')
    cases = _queue(client, analyst, 'open')['items']
    assert len(cases) == 2
    _decide(client, analyst, cases[0]['id'], 'PERMANENT_BLOCK')
    assert _queue(client, analyst, 'open')['meta']['total'] == 0
    assert _status(app) == 'PERMANENTLY_BLOCKED'
    with app.app_context():
        other = db.session.get(InvestigationCase, cases[1]['id'])
        assert other.status == 'RESOLVED' and cases[0]['case_ref'] in other.decision_reason
        db.session.remove()


@pytest.mark.parametrize('params, status', [({'view': 'nope'}, 422), ({'sort': 'nope'}, 422),
                                            ({'page': 999}, 200), ({'page': -3}, 200), ({'page_size': 100000}, 200),
                                            ({'q': "' OR 1=1 --"}, 200), ({'q': '%'}, 200)])
def test_queue_parameters(client, params, status):
    _, analyst, _ = _high_risk(client)
    res = client.get('/api/detection/investigations', headers=analyst, query_string=params)
    assert res.status_code == status
    if status == 200:
        data = res.get_json()['data']
        assert data['meta']['page_size'] <= 100 and data['meta']['page'] >= 1
        if params.get('page') == 999 or "'" in str(params.get('q', '')):
            assert data['items'] == []


@pytest.mark.parametrize('sort', ['newest', 'oldest', 'risk', 'amount'])
@pytest.mark.parametrize('view', ['pending', 'under_investigation', 'open', 'permanently_blocked', 'approved',
                                  'resolved', 'all'])
def test_every_view_and_sort_works(client, view, sort):
    _, analyst, _ = _high_risk(client)
    res = client.get('/api/detection/investigations', headers=analyst, query_string={'view': view, 'sort': sort})
    assert res.status_code == 200
    data = res.get_json()['data']
    assert data['meta']['total'] == data['counts'][view] == len(data['items'])


def test_counts_match_each_view_after_decisions(client, app):
    _, analyst, _ = _high_risk(client)
    _decide(client, analyst, _case_id(client, analyst), 'PERMANENT_BLOCK')
    data = _queue(client, analyst, 'all')
    assert data['counts']['permanently_blocked'] == 1 and data['counts']['resolved'] == 1
    assert data['counts']['open'] == data['counts']['pending'] == 0
    history = client.get('/api/detection/investigations/history', headers=analyst).get_json()['data']
    assert [a['action'] for a in history['items']][:2] == ['PERMANENT_BLOCK', 'CASE_OPENED']
