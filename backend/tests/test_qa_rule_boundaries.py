"""Each rule exactly at, just below and just above its configured threshold, and
the score bands at 69 / 70. The rules, weights and thresholds are the seeded
defaults – these tests check the engine honours them, they do not change them."""
from datetime import timedelta
from decimal import Decimal

import pytest

from portal.extensions import db
from portal.models import Account, User, now

from .conftest import balance, login, send
from .test_rules import _codes, _pay, _trusted_device

pytestmark = pytest.mark.usefixtures('owner_confirm')


@pytest.mark.parametrize('amount, fires', [('5000.00', False), ('5000.01', True)])
def test_r1_fires_only_above_five_times_the_average(ctx, amount, fires):
    dev = _trusted_device('rahul@demo.bank')
    for days in (20, 15, 10):
        _pay('rahul@demo.bank', 1000, when=now() - timedelta(days=days), device=dev)
    assert ('R1' in _codes(_pay('rahul@demo.bank', amount, device=dev))) is fires


@pytest.mark.parametrize('amount, fires', [('99999.99', False), ('100000.00', True)])
def test_r1_without_history_fires_from_the_absolute_threshold(ctx, amount, fires):
    dev = _trusted_device('rahul@demo.bank')
    assert ('R1' in _codes(_pay('rahul@demo.bank', amount, device=dev))) is fires


def test_r2_sixth_payment_in_ten_minutes_fires_but_not_when_spread_out(ctx):
    dev = _trusted_device('rahul@demo.bank')
    start = now() - timedelta(minutes=30)
    spaced = [_codes(_pay('rahul@demo.bank', 100, when=start + timedelta(minutes=3 * i), device=dev))
              for i in range(6)]
    assert all('R2' not in c for c in spaced)       # never more than 5 inside any 10-minute window


@pytest.mark.parametrize('amount, fires', [(25000, False), ('25000.01', True)])
def test_r4_new_device_fires_only_above_the_amount(client, amount, fires):
    login(client, 'rahul@demo.bank', device='usual')
    headers = login(client, 'rahul@demo.bank', device='brand-new')
    data = send(client, headers, amount).get_json()['data']
    assert ('R4' in {r['code'] for r in data['rules']}) is fires


@pytest.mark.parametrize('hour, minute, amount, fires', [
    (0, 0, '10000.01', True), (4, 59, '10000.01', True), (5, 0, '10000.01', False), (23, 59, '10000.01', False),
    (2, 0, '10000.00', False)])
def test_r5_hour_window_and_amount(ctx, hour, minute, amount, fires):
    dev = _trusted_device('rahul@demo.bank')
    at = (now() - timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    assert ('R5' in _codes(_pay('rahul@demo.bank', amount, when=at, device=dev))) is fires


# The band is 10 % *below* the ₹50,000 threshold: ₹45,000.00 – ₹49,999.99.
@pytest.mark.parametrize('amount, fires', [('44999.99', False), ('45000.00', True), ('49999.99', True),
                                           ('50000.00', False)])
def test_r7_structuring_band_edges(ctx, amount, fires):
    dev = _trusted_device('rahul@demo.bank')
    for _ in range(2):
        _pay('rahul@demo.bank', '46000', device=dev)
    assert ('R7' in _codes(_pay('rahul@demo.bank', amount, device=dev))) is fires


@pytest.mark.parametrize('idle_days, amount, fires', [(179, 30000, False), (180, 30000, True),
                                                      (200, '24999.99', False), (200, 25000, True)])
def test_r8_dormancy_and_amount_thresholds(ctx, idle_days, amount, fires):
    dev = _trusted_device('rahul@demo.bank')
    account = User.query.filter_by(email='rahul@demo.bank').first().primary_account
    account.last_txn_at = now() - timedelta(days=idle_days, hours=1)
    db.session.commit()
    assert ('R8' in _codes(_pay('rahul@demo.bank', amount, device=dev))) is fires


@pytest.mark.parametrize('failures, amount, fires, failure_signal', [
    (2, 6000, True, False),            # fires on the new-device signal alone, not on 2 failures
    (3, 6000, True, True), (3, '4999.99', False, False), (3, 5000, True, True)])
def test_r9_failed_login_count_and_minimum_amount(client, failures, amount, fires, failure_signal):
    login(client, 'rahul@demo.bank', device='phone')
    for _ in range(failures):
        login(client, 'rahul@demo.bank', device='attacker', password='guess', expect=401)
    headers = login(client, 'rahul@demo.bank', device='attacker')
    data = send(client, headers, amount).get_json()['data']
    analyst = login(client, 'analyst@demo.bank')
    rules = client.get(f"/api/detection/transactions/{data['id']}", headers=analyst).get_json()['data']['rules']
    r9 = [r for r in rules if r['code'] == 'R9']
    assert bool(r9) is fires
    assert bool(r9 and 'failed logins' in r9[0]['reason']) is failure_signal


@pytest.mark.parametrize('weight, status, restricted', [(39, 'UNDER_REVIEW', False), (40, 'UNDER_REVIEW', False),
                                                        (69, 'UNDER_REVIEW', False), (70, 'BLOCKED', True),
                                                        (100, 'BLOCKED', True)])
def test_score_bands_at_their_edges(client, app, weight, status, restricted):
    """Any score is held for the owner; from the blocking floor (70) it is stopped and
    the sender restricted. Nothing is debited either way."""
    analyst = login(client, 'analyst@demo.bank')
    assert client.put('/api/detection/rules/R6', headers=analyst, json={'weight': weight}).status_code == 200
    rahul = login(client, 'rahul@demo.bank')
    data = send(client, rahul, 100, upi='quickcash@fsbank').get_json()['data']
    assert data['risk_score'] == weight and data['status'] == status
    assert data['decision'] == ('BLOCKED' if weight >= 70 else 'REVIEW' if weight >= 40 else 'APPROVED')
    assert balance(app, 'rahul@demo.bank') == Decimal('250000')
    with app.app_context():
        account = Account.query.filter_by(upi_id='rahul@fsbank').one()
        assert (account.status == 'TEMPORARILY_BLOCKED') is restricted
        db.session.remove()


def test_weights_add_up_and_cap_at_100(client):
    analyst = login(client, 'analyst@demo.bank')
    client.put('/api/detection/rules/R6', headers=analyst, json={'weight': 30})
    client.put('/api/detection/rules/R4', headers=analyst, json={'weight': 25})
    login(client, 'rahul@demo.bank', device='usual')
    headers = login(client, 'rahul@demo.bank', device='fresh')
    data = send(client, headers, 30000, upi='quickcash@fsbank').get_json()['data']
    rules = client.get(f"/api/detection/transactions/{data['id']}", headers=analyst).get_json()['data']['rules']
    assert {'R4', 'R6'} <= {r['code'] for r in rules}
    assert data['risk_score'] == min(100, sum(r['weight'] for r in rules))


@pytest.mark.parametrize('weight', [-1, 101, 'abc', None, 1.5, True])
def test_rule_weight_must_be_0_to_100(client, weight):
    analyst = login(client, 'analyst@demo.bank')
    res = client.put('/api/detection/rules/R6', headers=analyst, json={'weight': weight})
    assert res.status_code == 422, res.get_json()


@pytest.mark.parametrize('body', [{'review_min': 70, 'blocked_min': 70}, {'review_min': 0, 'blocked_min': 50},
                                  {'review_min': 50, 'blocked_min': 101}, {'review_min': 'x', 'blocked_min': 80},
                                  {'review_min': 80, 'blocked_min': 60}, {}])
def test_invalid_score_bands_are_refused(client, body):
    analyst = login(client, 'analyst@demo.bank')
    res = client.put('/api/detection/risk-categories', headers=analyst, json=body)
    assert res.status_code == 422, res.get_json()
