from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://jobhunter:jobhunter@localhost:5433/jobhunter"
    redis_url: str = "redis://localhost:6380/0"
    secret_key: str = "dev-secret-change-me"
    # OAuth client ID from Google Cloud Console (empty = Google sign-in hidden)
    google_client_id: str = ""
    # Same Web client's secret; needed only for Gmail tracking (empty = Gmail hidden)
    google_client_secret: str = ""
    # Address Google sends Gmail sign-in back to, e.g. https://myhost.ts.net (empty = taken from the request)
    public_url: str = ""
    signup_enabled: bool = True
    jsearch_api_key: str = ""
    # Reuse a JSearch result for this long before spending another request on the same query
    jsearch_cache_hours: int = 20
    # Each JSearch query = 1 request of the free 200/month; stop when this many are left
    jsearch_min_quota: int = 15
    # AI match grades (empty key = only the rule-based grade)
    anthropic_api_key: str = ""
    ai_model: str = "claude-sonnet-5-5"
    ai_effort: str = "medium"  # how hard the model thinks: low | medium | high
    cookie_secure: bool = False
    session_days: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
