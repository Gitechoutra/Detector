"""Shared column types and helpers for the model modules."""
from datetime import datetime

from sqlalchemy.dialects.mysql import DATETIME

DT3 = DATETIME(fsp=3)
DT6 = DATETIME(fsp=6)


def now():
    return datetime.now()


def money(value):
    return float(value) if value is not None else None


def iso(value):
    return value.isoformat(timespec='seconds') if value else None
