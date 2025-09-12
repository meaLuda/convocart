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
    
    # Legacy WhatsApp API settings (keep for backwards compatibility)
    whatsapp_api_url: str = Field("", env="WHATSAPP_API_URL")
    whatsapp_phone_id: str = Field("", env="WHATSAPP_PHONE_ID")
    whatsapp_phone_number: str = Field("", env="WHATSAPP_PHONE_NUMBER")
    whatsapp_business_id: str = Field("", env="WHATSAPP_BUSINESS_ID")
    whatsapp_api_token: str = Field("", env="WHATSAPP_API_TOKEN")

    # Turso Database settings
    turso_auth_token: str = Field(..., env="TURSO_AUTH_TOKEN")
    turso_database_url: str = Field(..., env="TURSO_DATABASE_URL")

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
