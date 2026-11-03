"""
portal/seeds.py
===============
`flask init-db`: one-step database setup for a fresh clone – creates the MySQL
database named in DATABASE_URL if it does not exist yet, then runs every
migration (tables, dummy accounts from .env, sample history, rules, settings).

`flask seed`: re-run the seeders without touching migrations, e.g. after
someone deleted a dummy login, and synchronise the dummy accounts with .env.

Both are safe to run any number of times and never delete data.
"""
import click
from flask import current_app
from flask.cli import with_appcontext
from flask_migrate import upgrade
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from portal.extensions import db
from portal.seeders import run_all_seeders


@click.command('init-db')
@with_appcontext
def init_db_command():
    url = make_url(current_app.config['SQLALCHEMY_DATABASE_URI'])
    server = create_engine(url.set(database=''))
    try:
        with server.connect() as conn:
            conn.execute(text(f'CREATE DATABASE IF NOT EXISTS `{url.database}` '
                              'CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci'))
    except Exception as exc:  # noqa: BLE001  (show a usable message instead of a stack trace)
        raise click.ClickException(f'Cannot reach MySQL at {url.host}:{url.port or 3306} as {url.username}: {exc}. '
                                   'Check DATABASE_URL in backend/.env.')
    finally:
        server.dispose()
    upgrade()
    counts = {t: db.session.execute(text(f'SELECT COUNT(*) FROM {t}')).scalar()
              for t in ('users', 'accounts', 'transactions', 'fraud_rules')}
    click.echo(f"Database `{url.database}` is ready: {counts['users']} users, {counts['accounts']} accounts, "
               f"{counts['transactions']} transactions, {counts['fraud_rules']} fraud rules.")


@click.command('seed')
@with_appcontext
def seed_command():
    run_all_seeders(db.session.connection())
    db.session.commit()
    click.echo('Seed data is up to date.')
