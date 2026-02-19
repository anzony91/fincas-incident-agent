"""
Application configuration using Pydantic Settings
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )
    
    # Database
    database_url: str = "postgresql+asyncpg://fincas:fincas123@localhost:5432/fincas_db"
    
    @field_validator("database_url")
    @classmethod
    def fix_database_url(cls, v: str) -> str:
        """Convert postgresql:// to postgresql+asyncpg:// for async support"""
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v
    
    # IMAP Configuration
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""
    
    # SMTP Configuration
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    from_email: str = ""
    from_name: str = "Administración de Fincas"
    
    # Worker settings
    poll_interval_seconds: int = 60
    
    # OpenAI Configuration
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    
    # Application
    app_name: str = "Fincas Incident Agent"
    debug: bool = False
    log_level: str = "INFO"
    
    # Attachments
    attachments_path: str = "./data/attachments"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()
