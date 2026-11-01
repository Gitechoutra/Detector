import pytest
"""Each of the nine rules, fired in isolation, plus scoring and configuration."""
from datetime import timedelta
from decimal import Decimal

from portal.extensions import db
from portal.models import Account, Device, FraudRule, Location, User, now
from portal.helpers.payment_engine import respond_to_confirmation, send_money

from .conftest import login, send

# Written for the owner-confirmation policy (DECISION_MODE=OWNER_CONFIRM);
# the automatic policy is covered by test_auto_decisions.py.
pytestmark = pytest.mark.usefixtures('owner_confirm')


def _pay(email, amount, upi='priya@fsbank', when=None, city=None, device=None):
    user = User.query.filter_by(email=email).first()
    loc = Location.query.filter_by(city=city).first().id if city else user.home_location_id
    txn, _ = send_money(user, 'UPI', {'upi_id': upi}, Decimal(str(amount)), device_id=device, ip='127.0.0.1',
                        location_id=loc, txn_time=when)
    return txn


def _trusted_device(email):
    user = User.query.filter_by(email=email).first()
    device = Device(user_id=user.id, fingerprint='trusted-' + email, device_name='Own phone', is_trusted=True)
    db.session.add(device)
    db.session.commit()
    return device.id


def _codes(txn):
    return {h.rule_code for h in txn.latest_hits()}


def test_r1_high_amount_against_history(ctx):
    dev = _trusted_device('rahul@demo.bank')
    for days in (20, 15, 10):
        _pay('rahul@demo.bank', 1000, when=now() - timedelta(days=days), device=dev)
    txn = _pay('rahul@demo.bank', 6000, device=dev)
    assert _codes(txn) == {'R1'} and txn.decision == 'APPROVED' and txn.risk_score == 30


def test_r1_no_history_absolute_threshold(ctx):
    dev = _trusted_device('rahul@demo.bank')
    assert _codes(_pay('rahul@demo.bank', 99999, device=dev)) == set()
    assert 'R1' in _codes(_pay('rahul@demo.bank', 100000, upi='amit@fsbank', device=dev))


def test_r2_velocity(ctx):
    dev = _trusted_device('rahul@demo.bank')
    results = [_codes(_pay('rahul@demo.bank', 100, device=dev)) for _ in range(6)]
    assert all('R2' not in r for r in results[:5]) and 'R2' in results[5]


def test_r3_impossible_travel(ctx):
    dev = _trusted_device('rahul@demo.bank')
    _pay('rahul@demo.bank', 200, when=now() - timedelta(minutes=5), city='Mumbai', device=dev)
    txn = _pay('rahul@demo.bank', 300, city='Delhi', device=dev)
    hit = [h for h in txn.latest_hits() if h.rule_code == 'R3'][0]
    assert hit.evidence['from'] == 'Mumbai' and hit.evidence['to'] == 'Delhi' and hit.evidence['distance_km'] > 1000


def test_r3_same_city_or_slow_travel_does_not_fire(ctx):
    dev = _trusted_device('rahul@demo.bank')
    _pay('rahul@demo.bank', 200, when=now() - timedelta(minutes=45), city='Mumbai', device=dev)
    assert 'R3' not in _codes(_pay('rahul@demo.bank', 300, city='Delhi', device=dev))


def test_r4_new_device_high_amount(client, app):
    login(client, 'rahul@demo.bank', device='usual')
    headers = login(client, 'rahul@demo.bank', device='brand-new')
    small = send(client, headers, 20000).get_json()['data']
    assert 'R4' not in {r['code'] for r in small['rules']}
    big = send(client, headers, 30000, upi='amit@fsbank').get_json()['data']
    assert 'R4' in {r['code'] for r in big['rules']}


def test_r5_odd_hour(ctx):
    dev = _trusted_device('rahul@demo.bank')
    at = now().replace(hour=2, minute=30) - timedelta(days=1)
    assert _codes(_pay('rahul@demo.bank', 15000, when=at, device=dev)) == {'R5'}
    assert _codes(_pay('rahul@demo.bank', 15000, when=at.replace(hour=11), device=dev)) == set()


def test_r6_watchlist_account_and_upi(client):
    headers = login(client, 'rahul@demo.bank')
    by_upi = send(client, headers, 100, upi='quickcash@fsbank').get_json()['data']
    assert {r['code'] for r in by_upi['rules']} == {'R6'}


def test_r7_structuring(ctx):
    dev = _trusted_device('rahul@demo.bank')
    results = [_codes(_pay('rahul@demo.bank', 46000, device=dev)) for _ in range(3)]
    assert 'R7' not in results[0] and 'R7' not in results[1] and 'R7' in results[2]


def test_r8_dormant_reactivation(ctx):
    dev = _trusted_device('rahul@demo.bank')
    account = User.query.filter_by(email='rahul@demo.bank').first().primary_account
    account.last_txn_at = now() - timedelta(days=200)
    db.session.commit()
    first = _pay('rahul@demo.bank', 30000, device=dev)
    assert 'R8' in _codes(first) and first.status == 'UNDER_REVIEW'
    # Once the owner authorizes it, the completed payment reactivates the account.
    respond_to_confirmation(User.query.filter_by(email='rahul@demo.bank').first(), first.id, 'YES')
    assert 'R8' not in _codes(_pay('rahul@demo.bank', 30000, device=dev))


def test_r9_failed_logins_before_transfer(client):
    login(client, 'rahul@demo.bank', device='phone')
    for _ in range(3):
        login(client, 'rahul@demo.bank', device='attacker', password='guess', expect=401)
    headers = login(client, 'rahul@demo.bank', device='attacker')
    data = send(client, headers, 6000).get_json()['data']
    assert {r['code'] for r in data['rules']} == {'R9'} and data['status'] == 'UNDER_REVIEW'


def test_r9_cleared_by_owner_signing_in_on_trusted_device(client):
    login(client, 'rahul@demo.bank', device='phone')
    for _ in range(3):
        login(client, 'rahul@demo.bank', device='phone', password='typo', expect=401)
    headers = login(client, 'rahul@demo.bank', device='phone')   # the owner, on their own phone
    data = send(client, headers, 6000).get_json()['data']
    assert data['rules'] == [] and data['status'] == 'COMPLETED'


def test_r9_unusual_login_location(client, app):
    with app.app_context():
        kolkata = Location.query.filter_by(city='Kolkata').first().id
        db.session.remove()
    login(client, 'rahul@demo.bank', device='phone')
    headers = login(client, 'rahul@demo.bank', device='phone', location_id=kolkata)
    data = send(client, headers, 6000).get_json()['data']
    assert 'R9' in {r['code'] for r in data['rules']}


def test_score_is_capped_at_100_and_blocks(client, app):
    with app.app_context():
        Account.query.filter_by(upi_id='rahul@fsbank').first().last_txn_at = now() - timedelta(days=365)
        db.session.commit()
        db.session.remove()
    login(client, 'rahul@demo.bank', device='phone')
    for _ in range(3):
        login(client, 'rahul@demo.bank', device='attacker', password='x', expect=401)
    headers = login(client, 'rahul@demo.bank', device='attacker')
    data = send(client, headers, 120000, upi='quickcash@fsbank').get_json()['data']
    analyst = login(client, 'analyst@demo.bank')
    detail = client.get(f"/api/detection/transactions/{data['id']}", headers=analyst).get_json()['data']
    assert {'R1', 'R4', 'R6', 'R8', 'R9'} <= {r['code'] for r in detail['rules']}
    assert sum(r['weight'] for r in detail['rules']) > 100
    # Score 100 is in the BLOCKED band, but every flagged payment waits for its owner.
    assert data['risk_score'] == 100 and data['decision'] == 'BLOCKED'
    assert data['display_status'] == 'USER_CONFIRMATION_PENDING'


def test_disabled_rule_does_not_fire_and_weights_are_configurable(client):
    analyst = login(client, 'analyst@demo.bank')
    headers = login(client, 'rahul@demo.bank')
    client.put('/api/detection/rules/R6', headers=analyst, json={'is_active': False})
    assert send(client, headers, 100, upi='quickcash@fsbank').get_json()['data']['status'] == 'COMPLETED'
    client.put('/api/detection/rules/R6', headers=analyst, json={'is_active': True, 'weight': 35})
    data = send(client, headers, 100, upi='quickcash@fsbank').get_json()['data']
    assert data['risk_score'] == 35 and data['status'] == 'UNDER_REVIEW'


def test_rule_parameters_are_validated_and_applied(client):
    analyst = login(client, 'analyst@demo.bank')
    bad = client.put('/api/detection/rules/R4', headers=analyst, json={'params': {'amount_threshold': -1}})
    assert bad.status_code == 422
    wrong_keys = client.put('/api/detection/rules/R4', headers=analyst, json={'params': {'foo': 1}})
    assert wrong_keys.status_code == 422
    assert client.put('/api/detection/rules/R4', headers=analyst,
                      json={'params': {'amount_threshold': 1000}}).status_code == 200
    login(client, 'rahul@demo.bank', device='usual')
    headers = login(client, 'rahul@demo.bank', device='other')
    data = send(client, headers, 2000).get_json()['data']
    assert 'R4' in {r['code'] for r in data['rules']}


def test_score_bands_are_configurable(client):
    analyst = login(client, 'analyst@demo.bank')
    res = client.put('/api/detection/risk-categories', headers=analyst, json={'review_min': 60, 'blocked_min': 90})
    assert res.status_code == 200
    headers = login(client, 'rahul@demo.bank')
    data = send(client, headers, 100, upi='quickcash@fsbank').get_json()['data']
    assert data['risk_score'] == 50 and data['decision'] == 'APPROVED' and data['status'] == 'UNDER_REVIEW'


def test_every_rule_seeded_with_defaults(ctx):
    rules = {r.code: r for r in FraudRule.query.all()}
    assert sorted(rules) == [f'R{i}' for i in range(1, 10)]
    assert {c: r.weight for c, r in rules.items()} == {'R1': 30, 'R2': 25, 'R3': 35, 'R4': 20, 'R5': 10,
                                                       'R6': 50, 'R7': 15, 'R8': 20, 'R9': 45}
