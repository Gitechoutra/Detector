"""
portal/seeds.py
===============
`flask seed`: re-run the master-data seeders without touching migrations,
e.g. after someone deleted a demo login. Safe to run any number of times.
"""
import click
from flask.cli import with_appcontext

from portal.extensions import db
from portal.seeders import run_all_seeders


@click.command('seed')
@with_appcontext
def seed_command():
    run_all_seeders(db.session.connection())
    db.session.commit()
    click.echo('Seed data is up to date.')
