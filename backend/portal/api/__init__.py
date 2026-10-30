"""
portal/api/__init__.py
======================
API-wide behaviour shared by every route package: CORS, JWT error responses
and JSON error handlers, so every failure has the same {success, error} shape.
"""
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from portal.extensions import db, jwt
from portal.helpers.responses import error


def init_app(app):
    CORS(app, resources={r'/api/*': {'origins': app.config['CORS_ORIGINS']}},
         allow_headers=['Content-Type', 'Authorization', 'Idempotency-Key'])

    @jwt.unauthorized_loader
    def _missing(reason):
        return error('Please log in to continue.', 401, 'AUTH_REQUIRED')

    @jwt.invalid_token_loader
    def _invalid(reason):
        return error('Your session is invalid. Please log in again.', 401, 'TOKEN_INVALID')

    @jwt.expired_token_loader
    def _expired(header, payload):
        return error('Your session has expired. Please log in again.', 401, 'TOKEN_EXPIRED')

    @app.errorhandler(404)
    def _not_found(e):
        return error('Resource not found.', 404, 'NOT_FOUND')

    @app.errorhandler(405)
    def _method(e):
        return error('Method not allowed.', 405, 'METHOD_NOT_ALLOWED')

    @app.errorhandler(Exception)
    def _unhandled(e):
        if isinstance(e, HTTPException):
            return error(e.description or e.name, e.code, e.name.upper().replace(' ', '_'))
        db.session.rollback()
        app.logger.exception('Unhandled error')
        return error('Something went wrong on the server.', 500, 'SERVER_ERROR')

    app.logger.info('Initialised API error handling')
