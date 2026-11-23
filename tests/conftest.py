from collections.abc import Iterator

import psycopg
import pytest

from paddock.config import load_settings
from paddock.db.connection import apply_schema, connect

ALL_TABLES = "bio_sections, results, riders, events, seasons"


@pytest.fixture
def db() -> Iterator[psycopg.Connection]:
    """A connection to the test database with the schema applied and every table empty."""
    with connect(load_settings().test_database_url) as conn:
        apply_schema(conn)
        conn.execute(f"TRUNCATE {ALL_TABLES} RESTART IDENTITY CASCADE")
        conn.commit()
        yield conn
