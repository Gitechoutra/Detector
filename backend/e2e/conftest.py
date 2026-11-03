"""Browser tests (Playwright). They start their own backend and Vite dev server on
spare ports against a dedicated <name>_e2e database built by the migrations, so
neither the real database nor a running dev server is touched.

Run: python -m pytest e2e          (from backend/, with the venv active)
Needs: pip install -r requirements-dev.txt && python -m playwright install chromium"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

BACKEND = Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / 'frontend'
API_PORT, WEB_PORT = 5055, 3055
ARTIFACTS = BACKEND / 'e2e' / 'artifacts'

PASSWORDS = {
    'rahul@demo.bank': 'Rahul@123', 'karan@demo.bank': 'Karan@123', 'priya@demo.bank': 'Priya@123',
    'quickcash@demo.bank': 'Quick@123', 'analyst@demo.bank': 'Detect@123', 'frauder@demo.bank': 'Fraud@123',
}


def _free(port):
    with socket.socket() as s:
        return s.connect_ex(('127.0.0.1', port)) != 0


def _wait(url, seconds=90):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            if requests.get(url, timeout=2).status_code < 500:
                return
        except requests.RequestException:
            pass
        time.sleep(0.5)
    raise RuntimeError(f'{url} did not come up')


@pytest.fixture(scope='session')
def e2e_env():
    base = make_url(dotenv_values(BACKEND / '.env')['DATABASE_URL'])
    url = base.set(database=f'{base.database}_e2e')
    assert url.database not in (base.database, f'{base.database}_test')
    server = create_engine(url.set(database=''))
    with server.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS `{url.database}`'))
        conn.execute(text(f'CREATE DATABASE `{url.database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci'))
    server.dispose()
    env = {**os.environ, 'DATABASE_URL': url.render_as_string(hide_password=False), 'FLASK_APP': 'app.py',
           'CORS_ORIGINS': f'http://127.0.0.1:{WEB_PORT}'}
    # Dummy accounts use the documented .env.example logins, whatever the developer's .env says.
    for key, value in dotenv_values(BACKEND / '.env.example').items():
        if key.startswith('SEED_'):
            env[key] = value
    subprocess.run([sys.executable, '-m', 'flask', 'db', 'upgrade'], cwd=BACKEND, env=env, check=True,
                   capture_output=True)
    return env


@pytest.fixture(scope='session')
def servers(e2e_env):
    assert _free(API_PORT) and _free(WEB_PORT), f'ports {API_PORT}/{WEB_PORT} are in use'
    ARTIFACTS.mkdir(exist_ok=True)
    api_log = open(ARTIFACTS / 'backend.log', 'w', encoding='utf-8')
    api = subprocess.Popen([sys.executable, '-m', 'flask', 'run', '--port', str(API_PORT), '--no-reload'],
                           cwd=BACKEND, env=e2e_env, stdout=api_log, stderr=subprocess.STDOUT)
    npx = 'npx.cmd' if os.name == 'nt' else 'npx'
    web_log = open(ARTIFACTS / 'frontend.log', 'w', encoding='utf-8')
    web = subprocess.Popen([npx, 'vite', '--port', str(WEB_PORT), '--strictPort', '--host', '127.0.0.1'],
                           cwd=FRONTEND, env={**os.environ, 'VITE_API_TARGET': f'http://127.0.0.1:{API_PORT}'},
                           stdout=web_log, stderr=subprocess.STDOUT)
    try:
        _wait(f'http://127.0.0.1:{API_PORT}/api/health')
        _wait(f'http://127.0.0.1:{WEB_PORT}/')
        yield {'api': f'http://127.0.0.1:{API_PORT}/api', 'web': f'http://127.0.0.1:{WEB_PORT}'}
    finally:
        for proc in (web, api):
            if os.name == 'nt':        # npx starts node as a child: kill the whole tree
                subprocess.run(['taskkill', '/F', '/T', '/PID', str(proc.pid)], capture_output=True)
            else:
                proc.terminate()
        api_log.close()
        web_log.close()


@pytest.fixture(autouse=True)
def fresh_data(e2e_env):
    """The same reset the API tests use, run against the e2e database."""
    code = ('import sys; sys.path.insert(0, "."); import logging; logging.disable(50)\n'
            'from portal import create_app\nfrom portal.extensions import db\nfrom tests.data_reset import reset_data\n'
            'app = create_app()\nwith app.app_context(): reset_data()')
    subprocess.run([sys.executable, '-c', code], cwd=BACKEND, env=e2e_env, check=True, capture_output=True)


@pytest.fixture(scope='session')
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


class Page:
    """A browser tab that records console errors, failed and 5xx requests."""

    def __init__(self, browser, base, width=1366, height=768):
        self.context = browser.new_context(viewport={'width': width, 'height': height})
        self.page = self.context.new_page()
        self.base = base
        self.errors = []
        self.page.on('console', lambda m: m.type == 'error' and self.errors.append(f'console: {m.text}'))
        self.page.on('pageerror', lambda e: self.errors.append(f'pageerror: {e}'))
        self.page.on('requestfailed', lambda r: '/api/' in r.url and self.errors.append(
            f'requestfailed: {r.method} {r.url} {r.failure}'))
        self.page.on('response', lambda r: r.status >= 500 and self.errors.append(
            f'http {r.status}: {r.request.method} {r.url}'))

    def goto(self, path):
        self.page.goto(self.base + path)
        self.page.wait_for_load_state('networkidle')

    def login(self, email):
        self.goto('/login')
        self.page.fill('input[type=email]', email)
        self.page.fill('input[type=password]', PASSWORDS[email])
        self.page.click('form button.btn-glow')
        self.page.wait_for_url(lambda u: '/login' not in u, timeout=15000)
        # Dashboard pages are code-split: the login screen stays up until the chunk has loaded.
        self.page.wait_for_selector('main.content', timeout=15000)
        self.page.wait_for_load_state('networkidle')

    def overflow(self):
        """Pixels the page is wider than the viewport (horizontal scroll)."""
        return self.page.evaluate('document.documentElement.scrollWidth - window.innerWidth')

    def shot(self, name):
        self.page.screenshot(path=str(ARTIFACTS / f'{name}.png'), full_page=True)

    def close(self):
        self.context.close()


@pytest.fixture
def open_page(browser, servers, request):
    pages = []

    def factory(width=1366, height=768):
        p = Page(browser, servers['web'], width, height)
        pages.append(p)
        return p

    yield factory
    failed = request.node.rep_call.failed if hasattr(request.node, 'rep_call') else False
    for i, p in enumerate(pages):
        if failed:                      # screenshot on failure
            p.shot(f'{request.node.name}-{i}'.replace('/', '_')[:150])
        p.close()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f'rep_{rep.when}', rep)


@pytest.fixture
def api(servers):
    """Direct API calls for test setup (the browser tests the UI)."""
    def login(email, device='e2e-setup'):
        res = requests.post(f"{servers['api']}/auth/login",
                            json={'email': email, 'password': PASSWORDS[email], 'device_id': device})
        res.raise_for_status()
        return {'Authorization': 'Bearer ' + res.json()['data']['token']}

    def call(method, path, headers, **kw):
        return requests.request(method, servers['api'] + path, headers=headers, timeout=20, **kw)

    return type('Api', (), {'login': staticmethod(login), 'call': staticmethod(call)})
