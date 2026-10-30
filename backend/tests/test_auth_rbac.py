from portal.extensions import db
from portal.models import Alert, SecurityEvent, User

from .conftest import login


def test_all_four_roles_can_log_in(client):
    expected = {'rahul@demo.bank': '/user', 'priya@demo.bank': '/receiver',
                'analyst@demo.bank': '/detection', 'frauder@demo.bank': '/frauder'}
    for email, dashboard in expected.items():
        res = client.post('/api/auth/login', json={'email': email, 'password': {
            'rahul@demo.bank': 'Rahul@123', 'priya@demo.bank': 'Priya@123', 'analyst@demo.bank': 'Detect@123',
            'frauder@demo.bank': 'Fraud@123'}[email], 'device_id': 'd1'})
        assert res.status_code == 200
        assert res.get_json()['data']['dashboard'] == dashboard


def test_wrong_password_rejected_and_counts_down(client):
    res = login(client, 'rahul@demo.bank', password='nope', expect=401)
    assert '4 attempt(s) left' in res.get_json()['error']['message']


def test_account_locks_after_five_failures(client, app):
    for _ in range(4):
        login(client, 'rahul@demo.bank', password='nope', expect=401)
    res = login(client, 'rahul@demo.bank', password='nope', expect=423)
    assert res.get_json()['error']['code'] == 'ACCOUNT_LOCKED'
    # Even the right password is refused while locked.
    login(client, 'rahul@demo.bank', expect=423)
    with app.app_context():
        user = User.query.filter_by(email='rahul@demo.bank').first()
        assert user.status == 'LOCKED'
        assert SecurityEvent.query.filter_by(user_id=user.id, event_type='ACCOUNT_LOCKED').count() == 1
        assert Alert.query.filter_by(user_id=user.id, alert_type='SECURITY', severity='HIGH').count() == 1
        db.session.remove()


def test_simulation_accounts_cannot_log_in(client):
    res = client.post('/api/auth/login', json={'email': 'sim.ananya@sim.fraudshield.local',
                                               'password': 'anything', 'device_id': 'x'})
    assert res.status_code == 401


def test_first_device_trusted_second_device_flagged(client, app):
    login(client, 'rahul@demo.bank', device='phone')
    login(client, 'rahul@demo.bank', device='stranger-laptop')
    with app.app_context():
        user = User.query.filter_by(email='rahul@demo.bank').first()
        events = {e.event_type for e in SecurityEvent.query.filter_by(user_id=user.id)}
        assert 'NEW_DEVICE_LOGIN' in events
        db.session.remove()


def test_role_based_access_control(client):
    user = login(client, 'rahul@demo.bank')
    receiver = login(client, 'priya@demo.bank')
    detection = login(client, 'analyst@demo.bank')
    frauder = login(client, 'frauder@demo.bank')

    forbidden = [
        (user, 'get', '/api/detection/transactions'),
        (user, 'get', '/api/frauder/context'),
        (user, 'get', '/api/receiver/dashboard'),
        (receiver, 'post', '/api/transactions/send'),
        (receiver, 'get', '/api/user/dashboard'),
        (receiver, 'get', '/api/alerts'),
        (detection, 'post', '/api/frauder/transfer'),
        (detection, 'post', '/api/transactions/send'),
        (frauder, 'get', '/api/detection/rules'),
        (frauder, 'get', '/api/user/dashboard'),
    ]
    for headers, method, path in forbidden:
        res = getattr(client, method)(path, headers=headers, json={})
        assert res.status_code == 403, (path, res.status_code)

    allowed = [(user, '/api/user/dashboard'), (receiver, '/api/receiver/dashboard'),
               (detection, '/api/detection/rules'), (detection, '/api/analytics/summary'),
               (frauder, '/api/frauder/context')]
    for headers, path in allowed:
        assert client.get(path, headers=headers).status_code == 200, path

    assert client.get('/api/user/dashboard').status_code == 401
