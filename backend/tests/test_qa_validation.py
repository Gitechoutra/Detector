"""Input validation at the boundaries: every field the client controls is checked
on the server and rejected with a 4xx – never a crash, never a silent write."""
from decimal import Decimal

import pytest

from portal.extensions import db
from portal.models import LoginAttempt, Transaction, User

from .conftest import balance, login, send

BAD_LOCATIONS = ['abc', '1.5', '<script>', [], {}, '99999999999999999999', -1]


# ── location_id: login, register, send ─────────────────────────────────────

@pytest.mark.parametrize('location', BAD_LOCATIONS)
def test_login_with_a_bad_location_is_a_validation_error(client, location):
    res = client.post('/api/auth/login', json={'email': 'rahul@demo.bank', 'password': 'Rahul@123',
                                               'device_id': 'device-main', 'location_id': location})
    assert res.status_code == 422 and res.get_json()['error']['details']['field'] == 'location_id'


@pytest.mark.parametrize('location', BAD_LOCATIONS)
def test_unknown_user_login_with_a_bad_location_is_still_recorded(client, app, location):
    res = client.post('/api/auth/login', json={'email': 'nobody@demo.bank', 'password': 'whatever1',
                                               'device_id': 'd', 'location_id': location})
    assert res.status_code == 401 and res.get_json()['error']['code'] == 'INVALID_CREDENTIALS'
    with app.app_context():
        attempt = LoginAttempt.query.filter_by(email='nobody@demo.bank').one()
        assert attempt.success is False and attempt.location_id is None
        db.session.remove()


@pytest.mark.parametrize('location', BAD_LOCATIONS + [None, 0])
def test_register_with_a_bad_location_is_a_validation_error(client, app, location):
    res = client.post('/api/auth/register', json={
        'full_name': 'Test Person', 'email': 'tp@example.com', 'password': 'Passw0rd!', 'device_id': 'dev-tp',
        'location_id': location})
    assert res.status_code == 422 and res.get_json()['error']['details']['field'] == 'location_id'
    with app.app_context():
        assert User.query.filter_by(email='tp@example.com').count() == 0
        db.session.remove()


@pytest.mark.parametrize('location', BAD_LOCATIONS)
def test_send_with_a_bad_location_is_rejected_without_moving_money(client, app, location):
    rahul = login(client, 'rahul@demo.bank')
    res = send(client, rahul, 100, location_id=location)
    assert res.status_code == 422 and res.get_json()['error']['details']['field'] == 'location_id'
    assert balance(app, 'rahul@demo.bank') == Decimal('250000')
    with app.app_context():
        assert Transaction.query.count() == 0
        db.session.remove()


# ── amount ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('amount', [0, -1, '-0.01', 0.001, '0.999', 'abc', '', None, True, [], {}, 'NaN', 'Infinity',
                                    '-Infinity', '1e999999', '1E+7', 1000000.01, 10 ** 30, '1,000', ' '])
def test_invalid_amounts_are_rejected_without_a_record(client, app, amount):
    rahul = login(client, 'rahul@demo.bank')
    res = send(client, rahul, amount)
    assert res.status_code == 422 and res.get_json()['error']['details']['field'] == 'amount', res.get_json()
    assert balance(app, 'rahul@demo.bank') == Decimal('250000')
    with app.app_context():
        assert Transaction.query.count() == 0
        db.session.remove()


@pytest.mark.parametrize('amount, expected', [(1, Decimal('1')), ('1.00', Decimal('1')), ('99.99', Decimal('99.99'))])
def test_boundary_amounts_are_accepted(client, app, amount, expected):
    rahul = login(client, 'rahul@demo.bank')
    res = send(client, rahul, amount)
    assert res.status_code == 201 and res.get_json()['data']['status'] == 'COMPLETED', res.get_json()
    assert balance(app, 'rahul@demo.bank') == Decimal('250000') - expected


def test_exact_balance_can_be_sent_and_one_paisa_more_cannot(client, app):
    karan = login(client, 'karan@demo.bank')
    start = balance(app, 'karan@demo.bank')
    over = send(client, karan, str(start + Decimal('0.01')), upi='priya@fsbank')
    assert over.status_code in (409, 422) and balance(app, 'karan@demo.bank') == start
    exact = send(client, karan, str(start), upi='priya@fsbank')
    assert exact.status_code == 201
    data = exact.get_json()['data']
    if data['status'] == 'COMPLETED':
        assert balance(app, 'karan@demo.bank') == 0
    else:   # a rule held the large payment for the owner: nothing moves until they answer
        assert balance(app, 'karan@demo.bank') == start


# ── strings ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('remarks, ok_status', [('x' * 140, 201), ('x' * 141, 422), ('नमस्ते 🙏 café', 201),
                                                ("'; DROP TABLE transactions; --", 201), (123, 422)])
def test_remarks_length_unicode_and_injection(client, app, remarks, ok_status):
    rahul = login(client, 'rahul@demo.bank')
    res = send(client, rahul, 10, remarks=remarks)
    assert res.status_code == ok_status, res.get_json()
    if ok_status == 201:
        assert res.get_json()['data']['remarks'] == remarks.strip()
        with app.app_context():
            assert Transaction.query.count() == 1       # the table is intact
            db.session.remove()


def test_search_input_is_parameterised(client):
    rahul = login(client, 'rahul@demo.bank')
    send(client, rahul, 10, remarks='rent')
    for q in ["' OR '1'='1", '%', '_', '\\', '%%%%', "rent' --"]:
        res = client.get('/api/user/transactions', headers=rahul, query_string={'q': q})
        assert res.status_code == 200
        assert res.get_json()['data']['meta']['total'] <= 1


@pytest.mark.parametrize('field, value', [('email', 'not-an-email'), ('email', 'a@b'), ('password', 'short1'),
                                          ('password', 'lettersonly'), ('password', '12345678'), ('phone', '12345'),
                                          ('phone', '5123456789'), ('full_name', ''), ('full_name', 'x' * 101),
                                          ('role', 'DETECTION'), ('role', 'FRAUDER')])
def test_register_rejects_invalid_fields(client, app, field, value):
    body = {'full_name': 'Valid Name', 'email': 'valid@example.com', 'password': 'Passw0rd1', 'device_id': 'd1',
            'location_id': 1, 'phone': '9876543210', field: value}
    res = client.post('/api/auth/register', json=body)
    assert res.status_code == 422, res.get_json()
    with app.app_context():
        assert User.query.filter_by(email='valid@example.com').count() == 0
        db.session.remove()


def test_register_then_login_and_duplicate_email(client):
    body = {'full_name': 'New Person', 'email': 'New.Person@Example.com', 'password': 'Passw0rd1',
            'device_id': 'dnew', 'location_id': 1}
    res = client.post('/api/auth/register', json=body)
    assert res.status_code == 201
    data = res.get_json()['data']
    assert data['user']['role'] == 'USER' and data['account']['balance'] > 0
    again = client.post('/api/auth/register', json={**body, 'email': 'new.person@example.com'})
    assert again.status_code == 409 and again.get_json()['error']['code'] == 'EMAIL_TAKEN'
    me = client.get('/api/auth/me', headers={'Authorization': 'Bearer ' + data['token']})
    assert me.status_code == 200 and me.get_json()['data']['dashboard'] == '/user'


# ── non-string values where text is expected (each used to be a 500) ──────

NON_TEXT = [-1, 7, 1.5, True, False, [], ['YES'], {'a': 1}]


@pytest.mark.parametrize('value', NON_TEXT)
def test_yes_no_answer_must_be_text(client, app, value):
    rahul = login(client, 'rahul@demo.bank')
    held = send(client, rahul, 300, upi='quickcash@fsbank').get_json()['data']
    res = client.post(f'/api/transactions/{held["id"]}/confirmation', headers=rahul, json={'response': value})
    assert res.status_code == 422 and res.get_json()['error']['details']['field'] == 'response'
    with app.app_context():
        assert db.session.get(Transaction, held['id']).confirmation_status == 'PENDING'
        db.session.remove()


@pytest.mark.parametrize('field', ['decision', 'reason'])
@pytest.mark.parametrize('value', NON_TEXT)
def test_investigation_decision_fields_must_be_text(client, field, value):
    from .test_investigations import _high_risk
    _, analyst, _ = _high_risk(client)
    case_id = client.get('/api/detection/investigations', headers=analyst).get_json()['data']['items'][0]['id']
    body = {'decision': 'APPROVE', 'reason': 'Reviewed the evidence carefully.', 'confirm': True, field: value}
    res = client.post(f'/api/detection/investigations/{case_id}/decision', headers=analyst, json=body)
    assert res.status_code == 422 and res.get_json()['error']['details']['field'] == field


@pytest.mark.parametrize('value', NON_TEXT)
def test_watchlist_type_must_be_text(client, value):
    analyst = login(client, 'analyst@demo.bank')
    res = client.post('/api/detection/watchlist', headers=analyst,
                      json={'entity_type': value, 'entity_value': 'x@fsbank', 'reason': 'test'})
    assert res.status_code == 422


@pytest.mark.parametrize('field', ['upi_id', 'qr_payload', 'account_number', 'ifsc'])
@pytest.mark.parametrize('value', [[], {}, True])
def test_receiver_details_must_be_text(client, app, field, value):
    rahul = login(client, 'rahul@demo.bank')
    method = {'upi_id': 'UPI', 'qr_payload': 'QR'}.get(field, 'BANK_TRANSFER')
    body = {'payment_method': method, 'amount': 10, 'upi_id': 'priya@fsbank', 'account_number': '1', 'ifsc': 'X',
            field: value}
    res = client.post('/api/transactions/send', headers=rahul, json=body)
    assert 400 <= res.status_code < 500
    assert balance(app, 'rahul@demo.bank') == Decimal('250000')


def test_numeric_account_number_still_works(client, app):
    priya = client.get('/api/user/dashboard', headers=login(client, 'priya@demo.bank')).get_json()['data']['account']
    rahul = login(client, 'rahul@demo.bank')
    res = client.post('/api/transactions/send', headers=rahul, json={
        'payment_method': 'BANK_TRANSFER', 'account_number': int(priya['account_number']), 'ifsc': priya['ifsc'],
        'amount': 10})
    assert res.status_code == 201, res.get_json()


@pytest.mark.parametrize('key', [123, ['k'], {'k': 1}, True])
def test_idempotency_key_in_the_body_of_any_type(client, key):
    rahul = login(client, 'rahul@demo.bank')
    res = client.post('/api/transactions/send', headers=rahul,
                      json={'payment_method': 'UPI', 'upi_id': 'priya@fsbank', 'amount': 10, 'idempotency_key': key})
    assert res.status_code == 201
