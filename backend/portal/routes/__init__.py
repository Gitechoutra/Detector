"""
portal/routes/__init__.py
=========================
One package per feature: <feature>/__init__.py creates the Blueprint and
<feature>/routes.py adds the views to it.
"""


def init_app(app):
    from .alerts import bp as alerts_bp
    from .analytics import bp as analytics_bp
    from .authentication import bp as authentication_bp
    from .demo import bp as demo_bp
    from .detection import bp as detection_bp
    from .meta import bp as meta_bp
    from .notifications import bp as notifications_bp
    from .receivers import bp as receivers_bp
    from .security import bp as security_bp
    from .frauder import bp as frauder_bp
    from .transactions import bp as transactions_bp
    from .users import bp as users_bp

    for bp in (authentication_bp, meta_bp, users_bp, receivers_bp, transactions_bp, detection_bp, alerts_bp,
               notifications_bp, analytics_bp, security_bp, frauder_bp, demo_bp):
        app.register_blueprint(bp)
    app.logger.info('Registered %d route packages', 12)
