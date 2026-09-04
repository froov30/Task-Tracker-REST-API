"""
Application settings loaded from environment variables / .env file.

Priority order (highest → lowest):
  1. Real environment variables
  2. .env file in the project root
  3. Defaults defined here
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Database — override in tests via env var or dependency injection
    DATABASE_URL: str = "postgresql+asyncpg://taskuser:taskpass@localhost:5432/taskdb"

    # Application
    APP_TITLE: str = "Task Tracker REST API"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )


settings = Settings()
