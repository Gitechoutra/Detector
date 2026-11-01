"""Tests run against TEST_DATABASE_URL (default: bank_test), which is dropped,
recreated and migrated with `flask db upgrade` logic at the start of the
session. The real `bank` database is never touched."""
from decimal import Decimal

import pytest
from flask_migrate import upgrade
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from portal import create_app
from config.config import TestConfig
from portal.extensions import db
from portal.models import Account, SystemSetting, User
from portal.seeders.seed_settings import SETTINGS
from portal.helpers import demo


@pytest.fixture(scope='session')
def app():
    url = make_url(TestConfig.SQLALCHEMY_DATABASE_URI)
    assert url.database and url.database != 'bank', 'Tests must not run against the main database'
    server = create_engine(url.set(database=''))
    with server.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS `{url.database}`'))
        conn.execute(text(f'CREATE DATABASE `{url.database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci'))
    server.dispose()

    app = create_app(TestConfig)
    with app.app_context():
        upgrade()
    yield app


@pytest.fixture(autouse=True)
def fresh_data(app):
    with app.app_context():
        demo.reset()
        for key, value, _ in SETTINGS:          # tests may change the confirmation policy
            db.session.get(SystemSetting, key).setting_value = value
        db.session.commit()
        db.session.remove()
    yield
    with app.app_context():
        db.session.remove()


@pytest.fixture
def owner_confirm(app):
    """The pre-AUTO policy: any triggered rule is held for the owner's YES/NO."""
    with app.app_context():
        db.session.get(SystemSetting, 'DECISION_MODE').setting_value = 'OWNER_CONFIRM'
        db.session.commit()
        db.session.remove()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def ctx(app):
    with app.app_context():
        yield
        db.session.remove()


PASSWORDS = {
    'rahul@demo.bank': 'Rahul@123', 'karan@demo.bank': 'Karan@123', 'priya@demo.bank': 'Priya@123',
    'amit@demo.bank': 'Amit@123', 'quickcash@demo.bank': 'Quick@123', 'analyst@demo.bank': 'Detect@123',
    'frauder@demo.bank': 'Fraud@123', 'suresh@demo.bank': 'Suresh@123',
}


def login(client, email, device='device-main', password=None, location_id=None, expect=200):
    res = client.post('/api/auth/login', json={
        'email': email, 'password': password or PASSWORDS[email], 'device_id': device,
        'device_name': f'Test browser {device}', 'location_id': location_id})
    assert res.status_code == expect, res.get_json()
    if expect != 200:
        return res
    return {'Authorization': 'Bearer ' + res.get_json()['data']['token']}


def send(client, headers, amount, upi='priya@fsbank', key=None, **extra):
    body = {'payment_method': 'UPI', 'upi_id': upi, 'amount': amount, **extra}
    hdrs = dict(headers)
    if key:
        hdrs['Idempotency-Key'] = key
    return client.post('/api/transactions/send', json=body, headers=hdrs)


def balance(app, email):
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        value = Account.query.filter_by(user_id=user.id).first().balance
        db.session.remove()
        return Decimal(value)
