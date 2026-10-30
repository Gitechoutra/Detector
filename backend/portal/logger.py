"""
portal/logger.py
================
Console + rotating file logging (logs/app.log, 10 MB x 5 files).
"""
import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
FORMAT = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')


def init_logger(app):
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        os.makedirs(LOG_DIR, exist_ok=True)
        file_handler = RotatingFileHandler(os.path.join(LOG_DIR, 'app.log'), maxBytes=10 * 1024 * 1024,
                                           backupCount=5, encoding='utf-8')
        file_handler.setFormatter(FORMAT)
        root.addHandler(file_handler)
        console = logging.StreamHandler()
        console.setFormatter(FORMAT)
        root.addHandler(console)
    app.logger.info('Logger initialised')
