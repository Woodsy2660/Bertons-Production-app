from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://berton:berton_dev@localhost:5432/berton_bottling"
    debug: bool = True
    secret_key: str = "change-this-in-production"
    upload_dir: str = "./uploads"
    compiled_output_dir: str = "./compiled_output"

    manager_username: str = "manager"
    manager_password: str = "manager"
    operator_username: str = "operator"
    operator_password: str = "operator"

    operator_completed_run_days: int = 7
    operator_completed_run_limit: int = 10

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
