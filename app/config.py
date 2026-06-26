import os
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings


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

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @model_validator(mode="after")
    def apply_deployment_defaults(self) -> "Settings":
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