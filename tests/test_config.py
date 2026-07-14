from app.config import normalize_database_url, resolve_database_url_from_env


def test_normalize_database_url_postgres_scheme():
    url = "postgres://user:pass@host/db?sslmode=require"
    assert normalize_database_url(url) == (
        "postgresql+asyncpg://user:pass@host/db?sslmode=require"
    )


def test_normalize_database_url_postgresql_scheme():
    url = "postgresql://user:pass@host/db"
    assert normalize_database_url(url) == (
        "postgresql+asyncpg://user:pass@host/db"
    )


def test_normalize_database_url_leaves_asyncpg():
    url = "postgresql+asyncpg://user:pass@host/db"
    assert normalize_database_url(url) == url


def test_resolve_database_url_prefers_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://primary/db")
    monkeypatch.setenv("POSTGRES_URL", "postgres://secondary/db")
    assert resolve_database_url_from_env() == (
        "postgresql+asyncpg://primary/db"
    )