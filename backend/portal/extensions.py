"""
portal/extensions.py
====================
Shared Flask extension instances, imported by models, helpers and the app factory.
"""
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
migrate = Migrate()
jwt = JWTManager()
