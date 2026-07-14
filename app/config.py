import os
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings


def normalize_database_url(url: str) -> str:
    """Convert Vercel/Neon postgres:// URLs for SQLAlchemy + asyncpg."""
    normalized = url.strip()
    if normalized.startswith("postgres://"):
        normalized = "postgresql+asyncpg://" + normalized[len("postgres://") :]
    elif normalized.startswith("postgresql://") and "+asyncpg" not in normalized:
        normalized = "postgresql+asyncpg://" + normalized[len("postgresql://") :]
    return normalized


def resolve_database_url_from_env() -> str | None:
    """Pick up DATABASE_URL or Vercel/Neon Postgres integration vars."""
    for key in (
        "DATABASE_URL",
        "POSTGRES_URL",
        "POSTGRES_URL_NON_POOLING",
        "POSTGRES_PRISMA_URL",
    ):
        value = os.getenv(key)
        if value:
            return normalize_database_url(value)
    return None


def blob_configured() -> bool:
    return bool(
        os.getenv("BLOB_READ_WRITE_TOKEN")
        or (os.getenv("BLOB_STORE_ID") and os.getenv("VERCEL_OIDC_TOKEN"))
    )


def resolve_storage_backend() -> str:
    explicit = os.getenv("STORAGE_BACKEND", "").strip().lower()
    if explicit in {"local", "blob"}:
        return explicit
    if os.getenv("VERCEL") and blob_configured():
        return "blob"
    return "local"


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://berton:berton_dev@localhost:5432/berton_bottling"
    debug: bool = True
    secret_key: str = "change-this-in-production"
    upload_dir: str = "./uploads"
    compiled_output_dir: str = "./compiled_output"
    storage_backend: str = "local"
    blob_access: str = "private"

    manager_username: str = "manager"
    manager_password: str = "manager"
    operator_username: str = "operator"
    operator_password: str = "operator"

    operator_completed_run_days: int = 7
    operator_completed_run_limit: int = 10

    enable_dev_tools: bool = False

    pallet_tags_per_sheet: int = 1
    pallet_tag_dispatch: str = "browser"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @model_validator(mode="after")
    def apply_deployment_defaults(self) -> "Settings":
        resolved = resolve_database_url_from_env()
        if resolved:
            self.database_url = resolved
        elif not self.database_url.startswith("postgresql+asyncpg://"):
            self.database_url = normalize_database_url(self.database_url)

        if os.getenv("VERCEL"):
            if self.upload_dir in {"./uploads", "uploads"}:
                self.upload_dir = "/tmp/uploads"
            if self.compiled_output_dir in {"./compiled_output", "compiled_output"}:
                self.compiled_output_dir = "/tmp/compiled_output"
            if self.debug:
                self.debug = False

        if self.storage_backend == "local":
            self.storage_backend = resolve_storage_backend()

        return self

    @property
    def is_vercel(self) -> bool:
        return bool(os.getenv("VERCEL"))

    @property
    def is_production(self) -> bool:
        return self.is_vercel or not self.debug

    @property
    def blob_enabled(self) -> bool:
        return self.storage_backend == "blob" and blob_configured()


@lru_cache
def get_settings() -> Settings:
    return Settings()