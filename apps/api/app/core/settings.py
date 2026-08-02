from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: str = "development"
    database_url: str = "postgresql+psycopg://cmp:cmp@localhost:5432/cmp"
    db_connect_timeout_seconds: int = Field(default=5, gt=0)
    enable_dev_auth: bool = False
    test_database_url: str | None = None


settings = Settings()
