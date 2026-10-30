"""Models, one module per table. The schema itself is created by the Alembic
migrations in migrations/versions; these classes must stay in step with them."""
from portal.models.utils import DT3, DT6, iso, money, now  # noqa: F401
from portal.models.roles import Role  # noqa: F401
from portal.models.locations import Location  # noqa: F401
from portal.models.users import User  # noqa: F401
from portal.models.accounts import Account  # noqa: F401
from portal.models.devices import Device  # noqa: F401
from portal.models.login_attempts import LoginAttempt  # noqa: F401
from portal.models.security_events import SecurityEvent  # noqa: F401
from portal.models.fraud_rules import FraudRule  # noqa: F401
from portal.models.risk_categories import RiskCategory  # noqa: F401
from portal.models.transactions import Transaction  # noqa: F401
from portal.models.risk_assessments import RiskAssessment  # noqa: F401
from portal.models.triggered_rules import TriggeredRule  # noqa: F401
from portal.models.verification_challenges import VerificationChallenge  # noqa: F401
from portal.models.watchlist import WatchlistEntry  # noqa: F401
from portal.models.alerts import Alert  # noqa: F401
from portal.models.notifications import Notification  # noqa: F401
from portal.models.fraud_scenarios import FraudScenario  # noqa: F401
from portal.models.simulation_runs import SimulationRun  # noqa: F401
from portal.models.simulation_events import SimulationEvent  # noqa: F401
from portal.models.audit_logs import AuditLog  # noqa: F401
from portal.models.system_settings import SystemSetting  # noqa: F401
