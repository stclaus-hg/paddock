from importlib.resources import files

import psycopg

SCHEMA_FILE = "schema.sql"


def connect(url: str) -> psycopg.Connection:
    return psycopg.connect(url)


def apply_schema(conn: psycopg.Connection) -> None:
    """Create the extension, types, tables and views that do not exist yet."""
    schema = files("paddock.db").joinpath(SCHEMA_FILE).read_text(encoding="utf-8")
    conn.execute(schema.encode())
    conn.commit()
