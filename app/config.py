# app/config.py
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(override=True)
from pydantic import Field
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Server settings
    host: str = Field(..., env="HOST")
    port: int = Field(..., env="PORT")
    debug: bool = Field(False, env="DEBUG")
    secret_key: str = Field("default_secret_key", env="SECRET_KEY")

    # Twilio WhatsApp API settings
    twilio_account_sid: str = Field(..., env="TWILIO_ACCOUNT_SID")
    twilio_auth_token: str = Field(..., env="TWILIO_AUTH_TOKEN")
    twilio_whatsapp_number: str = Field(..., env="TWILIO_WHATSAPP_NUMBER")
    webhook_verify_token: str = Field(..., env="WEBHOOK_VERIFY_TOKEN")
    
    # Twilio webhook validation (optional - for additional security)
    twilio_webhook_auth_enabled: bool = Field(False, env="TWILIO_WEBHOOK_AUTH_ENABLED")
    
    # Twilio Content API template SIDs for interactive messages
    twilio_quick_reply_template_sid: str = Field("", env="TWILIO_QUICK_REPLY_TEMPLATE_SID")
    
    # Legacy WhatsApp API settings (keep for backwards compatibility)
    whatsapp_api_url: str = Field("", env="WHATSAPP_API_URL")
    whatsapp_phone_id: str = Field("", env="WHATSAPP_PHONE_ID")
    whatsapp_phone_number: str = Field("", env="WHATSAPP_PHONE_NUMBER")
    whatsapp_business_id: str = Field("", env="WHATSAPP_BUSINESS_ID")
    whatsapp_api_token: str = Field("", env="WHATSAPP_API_TOKEN")

    # Database settings
    database_url: str = Field(..., env="DATABASE_URL")

    # Admin credentials
    admin_username: str = Field("ConvoCartAdmin", env="ADMIN_USERNAME")
    admin_password: str = Field("ConvoCartPassword", env="ADMIN_PASSWORD")
    algorithm: str = Field("HS256", env="ALGORITHM")
    
    # AI/Gemini settings
    gemini_api_key: str = Field("", env="GEMINI_API_KEY")
    ai_model_name: str = Field("gemini-2.0-flash-exp", env="AI_MODEL_NAME")
    ai_temperature: float = Field(0.3, env="AI_TEMPERATURE")
    ai_max_tokens: int = Field(1000, env="AI_MAX_TOKENS")
    
    # LangGraph settings
    enable_ai_agent: bool = Field(True, env="ENABLE_AI_AGENT")
    ai_conversation_memory: bool = Field(True, env="AI_CONVERSATION_MEMORY")
    ai_debug_mode: bool = Field(False, env="AI_DEBUG_MODE")
    
    # Redis Cache settings
    redis_url: str = Field("redis://localhost:6379", env="REDIS_URL")
    redis_password: str = Field("", env="REDIS_PASSWORD")
    redis_db: int = Field(0, env="REDIS_DB")
    redis_max_connections: int = Field(20, env="REDIS_MAX_CONNECTIONS")
    cache_ttl: int = Field(300, env="CACHE_TTL")  # Default 5 minutes
    
    # Session Security settings
    session_secret_key: str = Field("your-session-secret-key-change-in-production", env="SESSION_SECRET_KEY")
    session_cookie_name: str = Field("session_id", env="SESSION_COOKIE_NAME")
    session_cookie_max_age: int = Field(3600, env="SESSION_COOKIE_MAX_AGE")  # 1 hour
    session_cookie_secure: bool = Field(True, env="SESSION_COOKIE_SECURE")
    session_cookie_httponly: bool = Field(True, env="SESSION_COOKIE_HTTPONLY")
    session_cookie_samesite: str = Field("lax", env="SESSION_COOKIE_SAMESITE")
    session_cookie_domain: str = Field("", env="SESSION_COOKIE_DOMAIN")
    
    # Security Headers
    security_headers_enabled: bool = Field(True, env="SECURITY_HEADERS_ENABLED")
    hsts_max_age: int = Field(31536000, env="HSTS_MAX_AGE")  # 1 year
    csp_policy: str = Field("default-src 'self'; script-src 'self' 'unsafe-inline' cdnjs.cloudflare.com unpkg.com code.jquery.com cdn.jsdelivr.net cdn.datatables.net; style-src 'self' 'unsafe-inline' cdnjs.cloudflare.com cdn.jsdelivr.net cdn.datatables.net fonts.googleapis.com; img-src 'self' data:; font-src 'self' cdnjs.cloudflare.com fonts.gstatic.com; connect-src 'self' cdnjs.cloudflare.com", env="CSP_POLICY")
    
    # Environment
    environment: str = Field("development", env="ENVIRONMENT")
    
    # CORS settings
    cors_origins: list = Field(["http://localhost", "http://localhost:8000"], env="CORS_ORIGINS")
    cors_allow_credentials: bool = Field(True, env="CORS_ALLOW_CREDENTIALS")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        env_prefix = "" # No prefix, directly use env var names
        extra = "ignore"  # Ignore extra fields that aren't defined
        
    
    
@lru_cache()
def get_settings() -> Settings:
    """Get application settings."""
    settings = Settings()
    print(f"DEBUG: Pydantic Settings Loaded: {settings.model_dump_json()}")
    return settings
