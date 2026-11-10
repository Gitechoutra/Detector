from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from flask import request

from portal.helpers.responses import ApiError


def json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError('Request body must be a JSON object.', 400, 'INVALID_JSON')
    return data


def require_str(data, field, max_len=255, label=None, required=True):
    value = data.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ApiError(f'{label or field} is required.', 422, 'VALIDATION_ERROR', {'field': field})
        return None
    if not isinstance(value, str):
        raise ApiError(f'{label or field} must be text.', 422, 'VALIDATION_ERROR', {'field': field})
    value = value.strip()
    if len(value) > max_len:
        raise ApiError(f'{label or field} must be at most {max_len} characters.', 422,
                       'VALIDATION_ERROR', {'field': field})
    return value


def parse_amount(value, minimum=Decimal('1'), maximum=Decimal('1000000')):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ApiError('Enter a valid amount.', 422, 'VALIDATION_ERROR', {'field': 'amount'})
    if not amount.is_finite() or amount != amount.quantize(Decimal('0.01')):
        raise ApiError('Amount can have at most 2 decimal places.', 422, 'VALIDATION_ERROR', {'field': 'amount'})
    if amount < minimum:
        raise ApiError(f'Minimum amount is ₹{minimum}.', 422, 'VALIDATION_ERROR', {'field': 'amount'})
    if amount > maximum:
        raise ApiError(f'Maximum amount per transaction is ₹{maximum:,.0f}.', 422,
                       'VALIDATION_ERROR', {'field': 'amount'})
    return amount


def parse_int(value, field, minimum=None, maximum=None):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ApiError(f'{field} must be a whole number.', 422, 'VALIDATION_ERROR', {'field': field})
    if minimum is not None and number < minimum or maximum is not None and number > maximum:
        raise ApiError(f'{field} must be between {minimum} and {maximum}.', 422,
                       'VALIDATION_ERROR', {'field': field})
    return number


def page_args(default_size=20, max_size=100):
    page = max(1, request.args.get('page', 1, type=int) or 1)
    size = min(max_size, max(1, request.args.get('page_size', default_size, type=int) or default_size))
    return page, size


def date_range_args():
    """Optional ?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD (to is inclusive)."""
    start = end = None
    try:
        if request.args.get('date_from'):
            start = datetime.strptime(request.args['date_from'], '%Y-%m-%d')
        if request.args.get('date_to'):
            end = datetime.strptime(request.args['date_to'], '%Y-%m-%d') + timedelta(days=1)
    except ValueError:
        raise ApiError('Dates must be in YYYY-MM-DD format.', 422, 'VALIDATION_ERROR')
    return start, end


def paginate(query, page, size):
    total = query.order_by(None).count()
    items = query.limit(size).offset((page - 1) * size).all()
    return items, {'page': page, 'page_size': size, 'total': total,
                   'pages': max(1, -(-total // size))}
