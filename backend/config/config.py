import os
from datetime import timedelta

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/
load_dotenv(os.path.join(BASE_DIR, '.env'))


def _flag(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in ('1', 'true', 'yes', 'on')


def _required(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f'{name} is not set. Copy .env.example to .env and fill it in.')
    return value


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY')
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=int(os.environ.get('JWT_ACCESS_MINUTES', 480)))

    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 1800,
        'pool_size': 10,
        'max_overflow': 20,
    }

    CORS_ORIGINS = [o.strip() for o in os.environ.get('CORS_ORIGINS', 'http://localhost:5173').split(',')]
    DEMO_MODE_ENABLED = _flag('DEMO_MODE_ENABLED', False)
    JSON_SORT_KEYS = False

    @classmethod
    def validate(cls):
        _required('DATABASE_URL')
        _required('SECRET_KEY')
        _required('JWT_SECRET_KEY')


def _test_database_url():
    """pytest never touches the real database: it uses <name>_test on the same
    server (e.g. bank -> bank_test), created and dropped by the test suite."""
    if os.environ.get('TEST_DATABASE_URL'):
        return os.environ['TEST_DATABASE_URL']
    if not os.environ.get('DATABASE_URL'):
        return None
    from sqlalchemy.engine import make_url
    url = make_url(os.environ['DATABASE_URL'])
    return url.set(database=f'{url.database}_test').render_as_string(hide_password=False)


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = _test_database_url()
    DEMO_MODE_ENABLED = True

    @classmethod
    def validate(cls):
        _required('DATABASE_URL')
        _required('JWT_SECRET_KEY')
