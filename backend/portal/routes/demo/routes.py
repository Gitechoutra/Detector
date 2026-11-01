"""Viva / Demo Mode. Public endpoints, available only while DEMO_MODE_ENABLED=true."""

from portal.helpers import demo
from portal.helpers.responses import ApiError, ok
from portal.helpers.security import demo_mode_required
from portal.helpers.validators import json_body
from . import bp



@bp.get('/info')
@demo_mode_required
def info():
    return ok(demo.info())


@bp.post('/unlock')
@demo_mode_required
def unlock():
    was_locked = demo.unlock_demo_user(json_body().get('email'))
    return ok({'was_locked': was_locked}, 'Demo account unlocked. You can sign in again.')


@bp.post('/reset-attempts')
@demo_mode_required
def reset_simulation():
    if json_body().get('confirm') != 'RESET':
        raise ApiError('Send {"confirm": "RESET"} to reset the fraud attempts.', 422, 'CONFIRMATION_REQUIRED')
    counts = demo.reset_simulation(actor=demo.frauder_user())
    return ok({'cleared': counts}, 'Fraud attempts reset. Money moved by Frauder transfers was reversed; '
                                   'genuine payments are untouched.')


@bp.post('/reset')
@demo_mode_required
def reset():
    data = json_body()
    if data.get('confirm') != 'RESET':
        raise ApiError('Send {"confirm": "RESET"} to reset the demo data.', 422, 'CONFIRMATION_REQUIRED')
    counts = demo.reset(restore_rules=data.get('restore_rules', True) is not False)
    return ok({'cleared': counts}, 'Demo data reset. Balances, watchlist and rules are restored.')
