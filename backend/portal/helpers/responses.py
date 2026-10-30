from flask import jsonify


def ok(data=None, message=None, status=200):
    body = {'success': True, 'data': data}
    if message:
        body['message'] = message
    return jsonify(body), status


def error(message, status=400, code='BAD_REQUEST', details=None):
    body = {'success': False, 'error': {'code': code, 'message': message}}
    if details:
        body['error']['details'] = details
    return jsonify(body), status


class ApiError(Exception):
    """Raised by services; blueprints turn it into an error() response."""

    def __init__(self, message, status=400, code='BAD_REQUEST', details=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.details = details

    def response(self):
        return error(self.message, self.status, self.code, self.details)
