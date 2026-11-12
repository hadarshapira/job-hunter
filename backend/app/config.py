from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://jobhunter:jobhunter@localhost:5433/jobhunter"
    redis_url: str = "redis://localhost:6380/0"
    secret_key: str = "dev-secret-change-me"
    # OAuth client ID from Google Cloud Console (empty = Google sign-in hidden)
    google_client_id: str = ""
    signup_enabled: bool = True
    cookie_secure: bool = False
    session_days: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
