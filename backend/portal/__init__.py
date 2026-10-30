"""
portal/__init__.py
==================
Application factory: config → logger → database/migrations → JWT → API
handlers → routes → seed CLI.
"""
import os

from flask import Flask

from config.config import Config
from portal.extensions import db, jwt, migrate  # noqa: F401  (db re-exported: `from portal import db`)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def create_app(config_class=Config):
    config_class.validate()
    app = Flask(__name__)
    app.config.from_object(config_class)

    from portal.logger import init_logger
    init_logger(app)

    import portal.models  # noqa: F401  (registers every model with SQLAlchemy / Alembic)
    db.init_app(app)
    migrate.init_app(app, db, directory=os.path.join(BASE_DIR, 'migrations'))
    jwt.init_app(app)
    app.logger.info('Initialised %d models', len(db.metadata.tables))

    from portal import api, routes
    api.init_app(app)
    routes.init_app(app)

    from portal.seeds import seed_command
    app.cli.add_command(seed_command)

    app.logger.info('FraudShield app initialised')
    return app
