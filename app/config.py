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
    
    # SMTP Configuration (defaults to IMAP credentials for Gmail)
    # Port 465 with SSL works better in cloud environments than 587 with STARTTLS
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    smtp_use_tls: bool = True  # Use SSL/TLS directly (port 465)
    smtp_timeout: int = 30
    smtp_user: str = ""
    smtp_password: str = ""
    from_email: str = ""
    from_name: str = "Administración de Fincas"
    
    # Resend API (alternative to SMTP - recommended for cloud deployments)
    # Get API key from https://resend.com - 3000 emails/month free
    resend_api_key: str = ""
    # Webhook secret for verifying Resend Inbound webhooks (optional but recommended)
    resend_webhook_secret: str = ""
    
    # SendGrid API (another alternative - 100 emails/day free)
    # Get API key from https://sendgrid.com
    sendgrid_api_key: str = ""
    
    # Email provider: "smtp", "resend", or "sendgrid"
    email_provider: str = "smtp"
    
    @property
    def effective_smtp_user(self) -> str:
        """Get SMTP user, falling back to IMAP user"""
        return self.smtp_user or self.imap_user
    
    @property
    def effective_smtp_password(self) -> str:
        """Get SMTP password, falling back to IMAP password"""
        return self.smtp_password or self.imap_password
    
    @property
    def effective_from_email(self) -> str:
        """Get from email, falling back to IMAP user"""
        return self.from_email or self.imap_user
    
    # Worker settings
    poll_interval_seconds: int = 60
    
    # OpenAI Configuration
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    
    # Twilio Configuration (for WhatsApp)
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_number: str = "+14155238886"  # Sandbox number by default
    
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
