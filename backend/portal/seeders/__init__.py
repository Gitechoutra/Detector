"""
portal/seeders
==============
Master and configuration data, the predefined dummy accounts and their sample
transaction history. Every seeder inserts a row only when its natural key is
missing, so running them again never duplicates rows. The one exception is
seed_users, which also synchronises the dummy accounts' email, password and
role with backend/.env.

Run automatically by the migrations (`flask db upgrade`) or on demand with
`flask seed`.
"""
from portal.seeders.seed_fraud_rules import seed_fraud_rules
from portal.seeders.seed_locations import seed_locations
from portal.seeders.seed_risk_categories import seed_risk_categories
from portal.seeders.seed_roles import seed_roles
from portal.seeders.seed_scenarios import seed_scenarios
from portal.seeders.seed_settings import seed_settings
from portal.seeders.seed_transactions import seed_transactions
from portal.seeders.seed_users import seed_users
from portal.seeders.seed_watchlist import seed_watchlist

# Order matters: users need roles and locations; the watchlist and history need accounts.
SEEDERS = [seed_roles, seed_locations, seed_users, seed_fraud_rules, seed_risk_categories, seed_scenarios,
           seed_watchlist, seed_settings, seed_transactions]


def run_all_seeders(conn):
    for seeder in SEEDERS:
        seeder(conn)
