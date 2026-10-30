from portal.seeders.utils import exists, insert

LOCATIONS = [
    ('Mumbai', 'Maharashtra', 19.076000, 72.877700), ('Delhi', 'Delhi', 28.704100, 77.102500),
    ('Bengaluru', 'Karnataka', 12.971600, 77.594600), ('Hyderabad', 'Telangana', 17.385000, 78.486700),
    ('Chennai', 'Tamil Nadu', 13.082700, 80.270700), ('Kolkata', 'West Bengal', 22.572600, 88.363900),
    ('Pune', 'Maharashtra', 18.520400, 73.856700), ('Ahmedabad', 'Gujarat', 23.022500, 72.571400),
    ('Jaipur', 'Rajasthan', 26.912400, 75.787300), ('Lucknow', 'Uttar Pradesh', 26.846700, 80.946200),
    ('Visakhapatnam', 'Andhra Pradesh', 17.686800, 83.218500), ('Kochi', 'Kerala', 9.931200, 76.267300),
]


def seed_locations(conn):
    for city, state, lat, lng in LOCATIONS:
        if not exists(conn, 'locations', 'city', city):
            insert(conn, 'locations', {'city': city, 'state': state, 'latitude': lat, 'longitude': lng})
