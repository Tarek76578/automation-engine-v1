from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Automation Engine"
    environment: str = "development"
    log_level: str = "INFO"
    database_url: str = ""
    redis_url: str = ""
    redis_visibility_timeout_seconds: int = 300
    redis_reclaim_batch_size: int = 100
    n8n_base_url: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    google_api_key: str = ""
    default_agent: str = "automation"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
