"""
portal/seeders
==============
Master and configuration data. Every seeder inserts a row only when its natural
key is missing, so running them again never duplicates rows and never
overwrites values someone has changed since. No transactions are seeded.

Run automatically by migration 0002 (`flask db upgrade`) or on demand with
`flask seed`.
"""
from portal.seeders.seed_fraud_rules import seed_fraud_rules
from portal.seeders.seed_locations import seed_locations
from portal.seeders.seed_risk_categories import seed_risk_categories
from portal.seeders.seed_roles import seed_roles
from portal.seeders.seed_scenarios import seed_scenarios
from portal.seeders.seed_settings import seed_settings
from portal.seeders.seed_users import seed_users
from portal.seeders.seed_watchlist import seed_watchlist

# Order matters: users need roles and locations; the watchlist needs accounts.
SEEDERS = [seed_roles, seed_locations, seed_users, seed_fraud_rules, seed_risk_categories, seed_scenarios,
           seed_watchlist, seed_settings]


def run_all_seeders(conn):
    for seeder in SEEDERS:
        seeder(conn)
