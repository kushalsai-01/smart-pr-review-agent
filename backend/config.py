from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    openai_api_key: str
    github_token: str
    github_webhook_secret: str
    github_app_client_id: str
    github_app_client_secret: str


@lru_cache
def get_settings() -> Settings:
    """Returns the cached application settings instance."""
    return Settings()
