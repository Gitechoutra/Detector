from portal.extensions import db


class SystemSetting(db.Model):
    __tablename__ = 'system_settings'
    setting_key = db.Column(db.String(60), primary_key=True)
    setting_value = db.Column(db.String(255), nullable=False)
    description = db.Column(db.String(255))
