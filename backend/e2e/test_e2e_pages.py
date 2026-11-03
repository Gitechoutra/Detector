"""Every page of every role at seven screen sizes: it renders, it makes no failed or
5xx API call, it logs no console error, and it never scrolls sideways."""
import pytest

VIEWPORTS = [(1920, 1080), (1440, 900), (1366, 768), (1024, 768), (768, 1024), (390, 844), (360, 800)]

PAGES = {
    'rahul@demo.bank': ['/user', '/user/send', '/user/qr', '/user/received', '/user/activity/all',
                        '/user/activity/successful', '/user/activity/failed', '/user/activity/blocked',
                        '/user/activity/pending', '/user/activity/awaiting', '/user/notifications', '/user/security'],
    'analyst@demo.bank': ['/detection', '/detection/monitor', '/detection/investigations', '/detection/alerts',
                          '/detection/rules', '/detection/watchlist', '/detection/engine', '/detection/security',
                          '/detection/investigations/{case}', '/detection/transactions/{txn}'],
    'frauder@demo.bank': ['/frauder', '/frauder/records', '/frauder/history'],
}
PUBLIC = ['/', '/login', '/register']


@pytest.fixture
def data(api):
    """Something on every page: a completed, a held and a blocked payment, and an open case."""
    rahul = api.login('rahul@demo.bank')
    analyst = api.login('analyst@demo.bank')
    api.call('POST', '/transactions/send', rahul, json={'payment_method': 'UPI', 'upi_id': 'priya@fsbank', 'amount': 120})
    held = api.call('POST', '/transactions/send', rahul,
                    json={'payment_method': 'UPI', 'upi_id': 'quickcash@fsbank', 'amount': 300}).json()['data']
    karan = api.login('karan@demo.bank')
    api.call('PUT', '/detection/rules/R6', analyst, json={'weight': 80})
    api.call('POST', '/transactions/send', karan, json={'payment_method': 'UPI', 'upi_id': 'quickcash@fsbank', 'amount': 500})
    api.call('PUT', '/detection/rules/R6', analyst, json={'weight': 50})
    case = api.call('GET', '/detection/investigations', analyst).json()['data']['items'][0]['id']
    return {'case': case, 'txn': held['id']}


@pytest.mark.parametrize('width, height', VIEWPORTS, ids=[f'{w}x{h}' for w, h in VIEWPORTS])
@pytest.mark.parametrize('email', list(PAGES), ids=['user', 'detection', 'frauder'])
def test_every_page_renders_cleanly(open_page, data, email, width, height):
    tab = open_page(width, height)
    tab.login(email)
    problems = []
    for path in PAGES[email]:
        path = path.format(**data)
        tab.errors.clear()
        tab.goto(path)
        text = tab.page.inner_text('body')
        if len(text.strip()) < 40:
            problems.append(f'{path}: page is (nearly) empty')
        if 'Something went wrong' in text:
            problems.append(f'{path}: shows a server error')
        if tab.overflow() > 1:
            tab.shot(f'overflow-{email.split("@")[0]}-{path.strip("/").replace("/", "_")}-{width}x{height}')
            problems.append(f'{path}: {tab.overflow()}px horizontal overflow')
        problems += [f'{path}: {e}' for e in tab.errors]
    assert not problems, '\n'.join(problems)


@pytest.mark.parametrize('width, height', VIEWPORTS, ids=[f'{w}x{h}' for w, h in VIEWPORTS])
def test_public_pages(open_page, width, height):
    tab = open_page(width, height)
    for path in PUBLIC:
        tab.goto(path)
        assert tab.overflow() <= 1, f'{path}: {tab.overflow()}px horizontal overflow at {width}x{height}'
    assert not tab.errors, tab.errors


@pytest.mark.parametrize('path', ['/user', '/user/send', '/detection', '/detection/investigations', '/frauder'])
def test_protected_pages_send_anonymous_visitors_to_login(open_page, path):
    tab = open_page()
    tab.goto(path)
    assert '/login' in tab.page.url


def test_a_customer_cannot_open_detective_pages(open_page, data):
    tab = open_page()
    tab.login('rahul@demo.bank')
    tab.goto(f'/detection/investigations/{data["case"]}')
    assert '/login' in tab.page.url and 'role=DETECTION' in tab.page.url
    assert 'Rahul' not in tab.page.inner_text('body') or 'Sign in as' in tab.page.inner_text('body')
