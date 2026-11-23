from paddock.config import load_settings


def test_settings_have_defaults(monkeypatch):
    monkeypatch.delenv("PADDOCK_DATABASE_URL", raising=False)
    monkeypatch.delenv("PADDOCK_CACHE_DIR", raising=False)
    settings = load_settings()
    assert settings.database_url.endswith(":5434/paddock")
    assert settings.cache_dir.as_posix() == "data/raw"
