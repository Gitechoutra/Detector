"""Insert-if-missing helpers. Seeders work on a plain SQLAlchemy Connection so
the same code runs inside an Alembic migration and from `flask seed`."""
import sqlalchemy as sa


def exists(conn, table, column, value):
    return conn.execute(sa.text(f'SELECT 1 FROM {table} WHERE {column} = :v LIMIT 1'), {'v': value}).first()


def insert(conn, table, row):
    cols = ', '.join(row)
    params = ', '.join(f':{c}' for c in row)
    conn.execute(sa.text(f'INSERT INTO {table} ({cols}) VALUES ({params})'), row)


def id_of(conn, table, column, value):
    return conn.execute(sa.text(f'SELECT id FROM {table} WHERE {column} = :v'), {'v': value}).scalar()
