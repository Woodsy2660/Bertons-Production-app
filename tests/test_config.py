import pytest

from app.config import (
    DEFAULT_SECRET_KEY,
    Settings,
    normalize_database_url,
    resolve_database_url_from_env,
)


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


def test_cookie_https_only_false_for_local_production(monkeypatch):
    """LAN Docker with DEBUG=false must not force Secure cookies (HTTP tablets)."""
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("SESSION_HTTPS_ONLY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    settings = Settings(
        debug=False,
        secret_key="a" * 32,
        manager_password="strong-manager-pass",
        operator_password="strong-operator-pass",
        session_https_only=None,
    )
    assert settings.is_production is True
    assert settings.cookie_https_only is False


def test_cookie_https_only_true_on_vercel(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("SESSION_HTTPS_ONLY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    settings = Settings(
        debug=True,  # Vercel path forces debug False in validator
        secret_key="a" * 32,
        manager_password="strong-manager-pass",
        operator_password="strong-operator-pass",
        session_https_only=None,
    )
    assert settings.is_vercel is True
    assert settings.is_production is True
    assert settings.cookie_https_only is True


def test_cookie_https_only_explicit_override(monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    settings = Settings(
        debug=False,
        secret_key="a" * 32,
        manager_password="strong-manager-pass",
        operator_password="strong-operator-pass",
        session_https_only=True,
    )
    assert settings.cookie_https_only is True


def test_production_rejects_default_secret_key(monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(
            debug=False,
            secret_key=DEFAULT_SECRET_KEY,
            manager_password="strong-manager-pass",
            operator_password="strong-operator-pass",
        )


def test_production_rejects_weak_passwords(monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="MANAGER_PASSWORD"):
        Settings(
            debug=False,
            secret_key="a" * 32,
            manager_password="manager",
            operator_password="strong-operator-pass",
        )


def test_dev_allows_default_secrets(monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    settings = Settings(
        debug=True,
        secret_key=DEFAULT_SECRET_KEY,
        manager_password="manager",
        operator_password="operator",
    )
    assert settings.cookie_https_only is False
