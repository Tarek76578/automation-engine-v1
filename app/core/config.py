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
    ollama_base_url: str = ""
    ollama_model: str = "llama3.2:3b"
    default_agent: str = "automation"
    action_webhook_allowlist: str = ""
    meta_page_id: str = ""
    meta_page_access_token: str = ""
    meta_graph_api_version: str = "v23.0"
    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_redirect_uri: str = ""
    meta_oauth_config_id: str = "947332841072287"
    meta_oauth_scopes: str = "pages_show_list,pages_read_engagement,pages_manage_posts,pages_messaging"
    meta_webhook_verify_token: str = ""
    meta_oauth_encryption_key: str = ""
    meta_messenger_auto_reply: bool = False
    meta_messenger_context_messages: int = 12

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
