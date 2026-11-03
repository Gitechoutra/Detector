"""The main journeys, clicked through in a real browser."""
import re
from decimal import Decimal

from .conftest import PASSWORDS


def _balance(api, email):
    return Decimal(str(api.call('GET', '/user/dashboard', api.login(email)).json()['data']['account']['balance']))


def _send_held_payment(tab):
    """Rahul pays the watch-listed QuickCash, which a rule holds for his YES/NO."""
    tab.goto('/user/send')
    tab.page.fill('input[placeholder="name@fsbank"]', 'quickcash@fsbank')
    tab.page.fill('input.input-amount', '300')
    tab.page.click('button.btn-primary.btn-lg')
    tab.page.wait_for_selector('text=NO, I DID NOT INITIATE THIS TRANSACTION', timeout=15000)


def test_login_errors_and_logout(open_page):
    tab = open_page()
    tab.goto('/login')
    tab.page.fill('input[type=email]', 'rahul@demo.bank')
    tab.page.fill('input[type=password]', 'wrong-password')
    tab.page.click('form button.btn-glow')
    tab.page.wait_for_selector('text=Invalid email or password')
    assert '/login' in tab.page.url
    tab.page.fill('input[type=password]', PASSWORDS['rahul@demo.bank'])
    tab.page.click('form button.btn-glow')
    tab.page.wait_for_url(re.compile(r'/user$'))
    tab.page.click('button[title="Log out"]')
    tab.page.wait_for_url(re.compile(r'/(login|)$'))
    tab.goto('/user')
    assert '/login' in tab.page.url
    assert not [e for e in tab.errors if 'http 5' in e], tab.errors


def test_answering_no_stops_the_payment(open_page, api):
    """The reported bug: NO, I DID NOT INITIATE THIS TRANSACTION used to answer 500."""
    tab = open_page()
    tab.login('rahul@demo.bank')
    _send_held_payment(tab)
    tab.goto('/user')
    tab.page.click('text=NO, I DID NOT INITIATE THIS TRANSACTION')
    tab.page.wait_for_selector('text=/no money has been transferred|receiver account has been flagged/i', timeout=15000)
    assert not tab.errors, tab.errors
    assert _balance(api, 'rahul@demo.bank') == Decimal('250000')
    lookup = api.call('POST', '/user/receivers/lookup', api.login('karan@demo.bank'),
                      json={'payment_method': 'UPI', 'upi_id': 'quickcash@fsbank'})
    assert lookup.status_code == 409                          # the receiver is now blocked


def test_answering_no_from_the_notifications_page(open_page, api):
    tab = open_page()
    tab.login('rahul@demo.bank')
    _send_held_payment(tab)
    tab.goto('/user/notifications')
    button = tab.page.locator('text=NO, I DID NOT INITIATE THIS TRANSACTION')
    assert button.count() >= 1, 'the security notification offers no NO button'
    with tab.page.expect_response(lambda r: r.url.endswith('/confirmation')) as answered:
        button.first.click()
    assert answered.value.status == 200
    tab.page.wait_for_load_state('networkidle')
    assert not tab.errors, tab.errors
    rahul = api.login('rahul@demo.bank')
    latest = api.call('GET', '/user/transactions', rahul).json()['data']['items'][0]
    assert latest['status'] == 'CANCELLED'
    assert _balance(api, 'rahul@demo.bank') == Decimal('250000')


def test_yes_and_otp_complete_the_payment(open_page, api):
    tab = open_page()
    tab.login('rahul@demo.bank')
    _send_held_payment(tab)
    tab.goto('/user')
    tab.page.click('text=YES, I INITIATED THIS TRANSACTION')
    tab.page.click('text=Use this code')
    tab.page.click('text=Verify & authorize')
    tab.page.wait_for_selector('text=/successfully authorized/i', timeout=15000)
    assert not tab.errors, tab.errors
    assert _balance(api, 'rahul@demo.bank') == Decimal('249700')


def test_double_clicking_send_pays_once(open_page, api):
    tab = open_page()
    tab.login('karan@demo.bank')
    tab.goto('/user/send')
    tab.page.fill('input[placeholder="name@fsbank"]', 'priya@fsbank')
    tab.page.fill('input.input-amount', '75')
    before = _balance(api, 'karan@demo.bank')
    tab.page.dblclick('button.btn-primary.btn-lg')
    tab.page.wait_for_load_state('networkidle')
    tab.page.wait_for_timeout(1000)
    assert _balance(api, 'karan@demo.bank') == before - 75
    assert not tab.errors, tab.errors


def test_invalid_amount_is_explained_not_sent(open_page, api):
    tab = open_page()
    tab.login('karan@demo.bank')
    before = _balance(api, 'karan@demo.bank')
    tab.goto('/user/send')
    tab.page.fill('input[placeholder="name@fsbank"]', 'priya@fsbank')
    tab.page.fill('input.input-amount', '99999999')
    tab.page.click('button.btn-primary.btn-lg')
    tab.page.wait_for_selector('text=/Maximum amount|Insufficient balance/i', timeout=10000)
    assert _balance(api, 'karan@demo.bank') == before


def _restricted_case(api):
    analyst = api.login('analyst@demo.bank')
    api.call('PUT', '/detection/rules/R6', analyst, json={'weight': 80})
    api.call('POST', '/transactions/send', api.login('rahul@demo.bank'),
             json={'payment_method': 'UPI', 'upi_id': 'quickcash@fsbank', 'amount': 900})
    api.call('PUT', '/detection/rules/R6', analyst, json={'weight': 50})
    return api.call('GET', '/detection/investigations', analyst).json()['data']['items'][0]


def _decide_in_ui(tab, case_id, button, reason):
    tab.goto(f'/detection/investigations/{case_id}')
    tab.page.click('text=Start investigation')
    tab.page.wait_for_load_state('networkidle')
    tab.page.click(f'text={button}')
    confirm = tab.page.locator('.modal button.btn-success, .modal button.btn-danger').last
    assert confirm.is_disabled()                              # no reason, no confirmation yet
    tab.page.fill('textarea', 'too short')
    tab.page.check('input[type=checkbox]')
    assert confirm.is_disabled()                              # reason under 10 characters
    tab.page.fill('textarea', reason)
    assert confirm.is_enabled()
    confirm.click()
    tab.page.wait_for_selector('text=Decisions are final', timeout=15000)


def test_detective_approves_and_the_customer_can_pay_again(open_page, api):
    case = _restricted_case(api)
    tab = open_page()
    tab.login('analyst@demo.bank')
    _decide_in_ui(tab, case['id'], 'Approve account', 'Customer confirmed the payment by phone.')
    assert not tab.errors, tab.errors
    res = api.call('POST', '/transactions/send', api.login('rahul@demo.bank'),
                   json={'payment_method': 'UPI', 'upi_id': 'priya@fsbank', 'amount': 10})
    assert res.status_code == 201


def test_detective_blocks_permanently_and_the_customer_sees_it(open_page, api):
    case = _restricted_case(api)
    tab = open_page()
    tab.login('analyst@demo.bank')
    _decide_in_ui(tab, case['id'], 'Permanently block', 'Confirmed account takeover from a new device.')
    customer = open_page()
    customer.login('rahul@demo.bank')
    customer.page.wait_for_selector('text=/permanently blocked/i', timeout=10000)
    customer.goto('/user/send')
    customer.page.fill('input[placeholder="name@fsbank"]', 'priya@fsbank')
    customer.page.fill('input.input-amount', '10')
    customer.page.click('button.btn-primary.btn-lg')
    customer.page.wait_for_selector('text=/permanently blocked/i', timeout=10000)
    assert _balance(api, 'rahul@demo.bank') == Decimal('250000')


def test_investigation_queue_search_and_views(open_page, api):
    case = _restricted_case(api)
    tab = open_page()
    tab.login('analyst@demo.bank')
    tab.goto('/detection/investigations')
    assert case['case_ref'] in tab.page.inner_text('body')
    search = tab.page.locator('input[type=search], input[placeholder*="earch"]').first
    search.fill('no-such-case-xyz')
    tab.page.wait_for_load_state('networkidle')
    tab.page.wait_for_timeout(600)
    assert case['case_ref'] not in tab.page.inner_text('body')
    assert not tab.errors, tab.errors


def test_session_revoked_elsewhere_sends_the_tab_to_login(open_page, api):
    tab = open_page()
    tab.login('rahul@demo.bank')
    token = tab.page.evaluate("JSON.parse(sessionStorage.getItem('fs_session')).token")
    api.call('POST', '/auth/logout', {'Authorization': 'Bearer ' + token})
    tab.goto('/user/activity/all')
    tab.page.wait_for_url(re.compile(r'/login'), timeout=10000)
