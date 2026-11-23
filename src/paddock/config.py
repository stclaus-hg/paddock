import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DATABASE_URL = "postgresql://paddock:paddock@localhost:5434/paddock"  #: docker-compose `db`, host port 5434
DEFAULT_TEST_DATABASE_URL = "postgresql://paddock:paddock@localhost:5434/paddock_test"  #: see docker/init-test-db.sql
DEFAULT_CACHE_DIR = "data/raw"  #: downloaded Wikipedia HTML, keyed by revision id (git-ignored)
DEFAULT_MANIFEST_PATH = "snapshot/manifest.json"  #: committed list of pinned Wikipedia revisions


@dataclass(frozen=True)
class Settings:
    database_url: str
    test_database_url: str
    cache_dir: Path
    manifest_path: Path


def load_settings() -> Settings:
    return Settings(
        database_url=os.environ.get("PADDOCK_DATABASE_URL", DEFAULT_DATABASE_URL),
        test_database_url=os.environ.get("PADDOCK_TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL),
        cache_dir=Path(os.environ.get("PADDOCK_CACHE_DIR", DEFAULT_CACHE_DIR)),
        manifest_path=Path(os.environ.get("PADDOCK_MANIFEST", DEFAULT_MANIFEST_PATH)),
    )
