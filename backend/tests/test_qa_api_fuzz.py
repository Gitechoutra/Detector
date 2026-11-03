"""Every API endpoint, called by every role and anonymously, with hostile input:
malformed JSON, wrong types, boundary and injection strings. A client mistake must
come back as a 4xx with the standard error shape, never a 500."""
import re

import pytest

from portal.extensions import db
from portal.models import InvestigationCase

from .conftest import login, send

ROLES = {'anon': None, 'user': 'rahul@demo.bank', 'detection': 'analyst@demo.bank', 'frauder': 'frauder@demo.bank'}

HOSTILE_VALUES = [None, '', ' ', 'abc', -1, 0, 1.5, 10 ** 30, '1e999999', 'NaN', 'Infinity', True, [], {},
                  "' OR 1=1 --", '<script>alert(1)</script>', 'ü' * 300, '9' * 400]
FIELDS = ['amount', 'upi_id', 'payment_method', 'location_id', 'response', 'otp', 'email', 'password', 'device_id',
          'decision', 'reason', 'confirm', 'weight', 'params', 'is_active', 'entity_type', 'entity_value', 'status',
          'victim_id', 'receiver_id', 'qr_payload', 'account_number', 'ifsc', 'full_name', 'phone', 'note', 'bands',
          'scope', 'account_id', 'period', 'remarks', 'idempotency_key', 'device_type', 'target_location']
QUERY = {'page': 'x', 'page_size': '-5', 'view': 'nope', 'sort': 'nope', 'date_from': '2026-13-45',
         'date_to': 'yesterday', 'status': "' OR 1=1 --", 'user_id': 'abc', 'q': '%_\\' * 30, 'unread': '1',
         'risk_level': 'X', 'source': 'x', 'flagged': '1', 'case_id': 'abc', 'account_id': 'z', 'limit': 'many'}


def _rules(app):
    rules = []
    for r in app.url_map.iter_rules():
        if not r.rule.startswith('/api/'):
            continue
        for method in sorted(r.methods - {'HEAD', 'OPTIONS'}):
            rules.append((method, r.rule))
    # Logout revokes the token every later call uses, so it goes last.
    return sorted(rules, key=lambda m_r: (m_r[1] == '/api/auth/logout', m_r))


def _paths(rule, ids):
    if '<' not in rule:
        return [rule]
    return [re.sub(r'<(int:)?[a-z_]+>', str(i), rule) for i in ids]


def _bodies():
    yield None                                      # no body
    yield 'not json at all'                         # malformed
    yield []                                        # JSON, but not an object
    yield {}
    for value in HOSTILE_VALUES:
        yield {f: value for f in FIELDS}


@pytest.fixture
def tokens(client):
    return {role: (login(client, email) if email else {}) for role, email in ROLES.items()}


def _call(client, method, path, headers, body):
    kwargs = {'headers': dict(headers)}
    if isinstance(body, str):
        kwargs['data'], kwargs['content_type'] = body, 'application/json'
    elif body is not None:
        kwargs['json'] = body
    return client.open(path, method=method, **kwargs)


def test_no_endpoint_returns_500_on_hostile_input(client, app, tokens):
    # Real ids too, so handlers get past the "not found" check with bad bodies.
    rahul = tokens['user']
    held = send(client, rahul, 500, upi='quickcash@fsbank').get_json()['data']['id']
    with app.app_context():
        case_id = db.session.query(db.func.max(InvestigationCase.id)).scalar() or 1
    ids = [held, case_id, 99999999999]

    failures, authorised = [], 0
    for method, rule in _rules(app):
        for path in _paths(rule, ids):
            for role, headers in tokens.items():
                probe = _call(client, method, path, headers, {})
                if probe.status_code in (401, 403):
                    continue                     # this role never reaches the handler
                bodies = list(_bodies()) if method != 'GET' else [None]
                for body in bodies:
                    res = _call(client, method, path, headers, body)
                    authorised += res.status_code not in (401, 403)
                    if res.status_code >= 500:
                        failures.append((method, path, role, repr(body)[:80], res.status_code))
                    elif res.status_code >= 400:
                        payload = res.get_json(silent=True)
                        assert payload and payload.get('success') is False and payload['error'].get('code'), \
                            (method, path, role, res.status_code, res.data[:200])
                if method == 'GET':
                    res = client.get(path, headers=headers, query_string=QUERY)
                    if res.status_code >= 500:
                        failures.append((method, path + ' ?hostile-query', role, '', res.status_code))
    by_endpoint = {}
    for method, path, role, body, _ in failures:
        by_endpoint.setdefault((method, re.sub(r'/\d+', '/<id>', path), role), []).append(body)
    assert not failures, '\n'.join(f'{k}: {len(v)} bodies, e.g. {v[0]}' for k, v in sorted(by_endpoint.items()))
    assert authorised > 1000, f'only {authorised} calls got past authentication – the fuzz is not reaching handlers'


def test_anonymous_requests_are_rejected_everywhere_but_public_routes(client, app):
    public = {'/api/auth/login', '/api/auth/register', '/api/health', '/api/meta/locations',
              '/api/meta/risk-categories'}
    for method, rule in _rules(app):
        if rule in public:
            continue
        path = _paths(rule, [1])[0]
        res = client.open(path, method=method, json={})
        assert res.status_code == 401, (method, path, res.status_code)
        assert res.get_json()['error']['code'] == 'AUTH_REQUIRED'


@pytest.mark.parametrize('token', ['Bearer abc.def.ghi', 'Bearer ', 'Basic dXNlcjpwYXNz', 'Bearer ' + 'a' * 5000,
                                   'Bearer eyJhbGciOiJub25lIn0.eyJzdWIiOiIxIn0.'])
def test_forged_or_malformed_tokens_are_rejected(client, token):
    res = client.get('/api/user/dashboard', headers={'Authorization': token})
    assert res.status_code in (401, 422) and res.get_json()['success'] is False


def test_wrong_http_method_is_405_json(client):
    res = client.delete('/api/auth/login')
    assert res.status_code == 405 and res.get_json()['error']['code'] == 'METHOD_NOT_ALLOWED'
    res = client.get('/api/does-not-exist')
    assert res.status_code == 404 and res.get_json()['error']['code'] == 'NOT_FOUND'
