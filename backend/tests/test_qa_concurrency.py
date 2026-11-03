"""Races: parallel payments, parallel answers and parallel detective decisions.
Each thread has its own client and DB session, so the row locks are really exercised."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from sqlalchemy import text

from portal.extensions import db
from portal.helpers import payment_engine
from portal.models import Account, InvestigationAction, InvestigationCase, Transaction

from .conftest import balance, login, otp_from, send
from .test_investigations import _decide, _high_risk


def _parallel(fn, n):
    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(fn, range(n)))


def _totals(app):
    with app.app_context():
        total = db.session.query(db.func.sum(Account.balance)).scalar()
        db.session.remove()
        return Decimal(total)


def test_parallel_payments_never_overdraw_or_create_money(client, app):
    """Karan has ₹20,000 (no rule fires between these regular accounts): six parallel
    ₹5,000 payments can complete at most four times."""
    start_total = _totals(app)
    karan_start = balance(app, 'karan@demo.bank')
    headers = login(client, 'karan@demo.bank')
    amount = (karan_start / 4).quantize(Decimal('0.01'))

    def pay(_):
        return app.test_client().post('/api/transactions/send', headers=headers,
                                      json={'payment_method': 'UPI', 'upi_id': 'priya@fsbank', 'amount': str(amount)})

    results = _parallel(pay, 6)
    assert all(r.status_code in (201, 422) for r in results), [r.get_json() for r in results]
    with app.app_context():
        done = Transaction.query.filter_by(status='COMPLETED').count()
        db.session.remove()
    assert done <= 4
    assert balance(app, 'karan@demo.bank') == karan_start - amount * done >= 0
    assert _totals(app) == start_total             # money is moved, never created or lost


def test_parallel_submissions_with_one_idempotency_key_debit_once(client, app):
    rahul = login(client, 'rahul@demo.bank')

    def pay(_):
        return app.test_client().post('/api/transactions/send', headers={**rahul, 'Idempotency-Key': 'same-key-1'},
                                      json={'payment_method': 'UPI', 'upi_id': 'priya@fsbank', 'amount': 700})

    results = _parallel(pay, 5)
    assert all(r.status_code in (200, 201) for r in results), [r.get_json() for r in results]
    assert len({r.get_json()['data']['id'] for r in results}) == 1
    assert balance(app, 'rahul@demo.bank') == Decimal('250000') - 700


def test_parallel_correct_otps_authorize_once(client, app):
    rahul = login(client, 'rahul@demo.bank')
    held = send(client, rahul, 900, upi='quickcash@fsbank').get_json()['data']
    otp = otp_from(client.post(f'/api/transactions/{held["id"]}/confirmation', headers=rahul,
                               json={'response': 'YES'}))

    def confirm(_):
        return app.test_client().post(f'/api/transactions/{held["id"]}/verification/confirm', headers=rahul,
                                      json={'otp': otp})

    results = _parallel(confirm, 4)
    assert sum(r.status_code == 200 for r in results) == 1, [r.get_json() for r in results]
    assert all(r.status_code in (200, 409) for r in results)
    assert balance(app, 'rahul@demo.bank') == Decimal('250000') - 900


def test_parallel_yes_and_no_answers_count_once(client, app):
    rahul = login(client, 'rahul@demo.bank')
    held = send(client, rahul, 400, upi='quickcash@fsbank').get_json()['data']

    def answer(i):
        return app.test_client().post(f'/api/transactions/{held["id"]}/confirmation', headers=rahul,
                                      json={'response': 'YES' if i % 2 else 'NO'})

    results = _parallel(answer, 6)
    assert sum(r.status_code == 200 for r in results) == 1, [r.get_json() for r in results]
    assert balance(app, 'rahul@demo.bank') == Decimal('250000')


def test_two_detectives_cannot_both_decide_a_case(client, app):
    rahul, analyst, txn = _high_risk(client)
    case_id = client.get('/api/detection/investigations', headers=analyst).get_json()['data']['items'][0]['id']

    def decide(i):
        return _decide(app.test_client(), analyst, case_id, 'APPROVE' if i % 2 else 'PERMANENT_BLOCK')

    results = _parallel(decide, 6)
    assert sum(r.status_code == 200 for r in results) == 1, [r.get_json() for r in results]
    assert all(r.status_code in (200, 409) for r in results)
    with app.app_context():
        case = db.session.get(InvestigationCase, case_id)
        final = InvestigationAction.query.filter(InvestigationAction.case_id == case_id,
                                                 InvestigationAction.action.in_(('APPROVE', 'PERMANENT_BLOCK'))).all()
        account = db.session.get(Account, case.account_id)
        assert len(final) == 1 and final[0].action == case.decision
        assert account.status == ('ACTIVE' if case.decision == 'APPROVE' else 'PERMANENTLY_BLOCKED')
        db.session.remove()


def test_restriction_landing_between_check_and_lock_still_stops_the_money(client, app, monkeypatch):
    """The sender passes the early status check, then another request restricts the
    account before this one takes its row locks: the locked re-check must refuse."""
    rahul = login(client, 'rahul@demo.bank')
    real = payment_engine.resolve_receiver

    def restrict_meanwhile(method, data):
        with db.engine.connect() as other:          # a separate connection = another request
            other.execute(text("UPDATE accounts SET status = 'TEMPORARILY_BLOCKED' WHERE upi_id = 'rahul@fsbank'"))
            other.commit()
        return real(method, data)

    monkeypatch.setattr(payment_engine, 'resolve_receiver', restrict_meanwhile)
    res = send(client, rahul, 100)
    assert res.status_code in (201, 423)
    if res.status_code == 201:
        assert res.get_json()['data']['status'] != 'COMPLETED'
    assert balance(app, 'rahul@demo.bank') == Decimal('250000')
    assert balance(app, 'priya@demo.bank') == Decimal('25000')


def test_receiver_blocked_between_check_and_lock_receives_nothing(client, app, monkeypatch):
    rahul = login(client, 'rahul@demo.bank')
    real = payment_engine.resolve_receiver

    def block_meanwhile(method, data):
        account = real(method, data)
        with db.engine.connect() as other:
            other.execute(text("UPDATE accounts SET status = 'BLOCKED' WHERE upi_id = 'priya@fsbank'"))
            other.commit()
        return account

    monkeypatch.setattr(payment_engine, 'resolve_receiver', block_meanwhile)
    res = send(client, rahul, 100)
    assert res.status_code in (201, 409)
    if res.status_code == 201:
        assert res.get_json()['data']['status'] != 'COMPLETED'
    assert balance(app, 'rahul@demo.bank') == Decimal('250000')
    assert balance(app, 'priya@demo.bank') == Decimal('25000')
