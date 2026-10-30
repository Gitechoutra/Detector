import uuid
from decimal import Decimal

from portal.extensions import db
from portal.models import Location, User

from .conftest import balance, send


def _city(app, name='Hyderabad'):
    with app.app_context():
        loc = Location.query.filter_by(city=name).first().id
        db.session.remove()
        return loc


def _email(prefix='sita'):
    # Registered users outlive the per-test reset (the audit trail references
    # them), so every test uses fresh addresses.
    return f'{prefix}{uuid.uuid4().hex[:8]}@example.com'


def _register(client, app, **overrides):
    body = {'full_name': 'Sita Ram', 'email': _email(), 'phone': '9876543210', 'password': 'Sita@2026',
            'role': 'USER', 'location_id': _city(app), 'device_id': 'sita-phone',
            'device_name': 'Chrome on Android', **overrides}
    return client.post('/api/auth/register', json=body)


def test_new_user_registers_logs_in_and_can_pay(client, app):
    email = _email()
    res = _register(client, app, email=email)
    assert res.status_code == 201, res.get_json()
    data = res.get_json()['data']
    assert data['dashboard'] == '/user' and data['account']['upi_id'] == email.split('@')[0] + '@fsbank'
    assert data['account']['balance'] == 50000
    headers = {'Authorization': 'Bearer ' + data['token']}
    assert send(client, headers, 1000).get_json()['data']['status'] == 'COMPLETED'
    assert balance(app, 'priya@demo.bank') == Decimal('26000')
    assert balance(app, email) == Decimal('49000')
    # The registration device is the first device, so it is trusted.
    assert client.get('/api/user/security', headers=headers).get_json()['data']['devices'][0]['is_trusted']


def test_new_receiver_starts_at_zero_and_can_be_paid(client, app):
    email = _email('shop')
    data = _register(client, app, email=email, role='RECEIVER', full_name='Corner Shop').get_json()['data']
    assert data['dashboard'] == '/receiver' and data['account']['balance'] == 0
    login = client.post('/api/auth/login', json={'email': 'rahul@demo.bank', 'password': 'Rahul@123',
                                                 'device_id': 'r1'}).get_json()['data']
    paid = send(client, {'Authorization': 'Bearer ' + login['token']}, 700, upi=data['account']['upi_id'])
    assert paid.get_json()['data']['status'] == 'COMPLETED'
    assert balance(app, email) == Decimal('700')


def test_registration_validation(client, app):
    email = _email()
    for bad in ({'role': 'DETECTION'}, {'role': 'FRAUDER'}, {'password': 'short1'}, {'password': 'onlyletters'},
                {'email': 'not-an-email'}, {'phone': '12345'}, {'location_id': None}):
        res = _register(client, app, **{'email': email, **bad})
        assert res.status_code == 422, (bad, res.get_json())
    assert _register(client, app, email='rahul@demo.bank').status_code == 409
    with app.app_context():
        assert User.query.filter_by(email=email).count() == 0
        db.session.remove()


def test_duplicate_email_and_unique_upi(client, app):
    local = 'sita' + uuid.uuid4().hex[:8]
    assert _register(client, app, email=f'{local}@example.com').status_code == 201
    assert _register(client, app, email=f'{local.upper()}@EXAMPLE.com').status_code == 409
    other = _register(client, app, email=f'{local}@other.org').get_json()['data']
    assert other['account']['upi_id'] == f'{local}2@fsbank'
