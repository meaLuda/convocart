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

    # WhatsApp API settings
    whatsapp_api_url: str = Field(..., env="WHATSAPP_API_URL")
    whatsapp_phone_id: str = Field(..., env="WHATSAPP_PHONE_ID")
    whatsapp_phone_number: str = Field(..., env="WHATSAPP_PHONE_NUMBER")
    whatsapp_api_token: str = Field(..., env="WHATSAPP_API_TOKEN")
    webhook_verify_token: str = Field(..., env="WEBHOOK_VERIFY_TOKEN")

    # Turso Database settings
    turso_auth_token: str = Field(..., env="TURSO_AUTH_TOKEN")
    turso_database_url: str = Field(..., env="TURSO_DATABASE_URL")

    # Admin credentials
    admin_username: str = Field("ConvoCartAdmin", env="ADMIN_USERNAME")
    admin_password: str = Field("ConvoCartPassword", env="ADMIN_PASSWORD")
    algorithm: str = Field("HS256", env="ALGORITHM")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        env_prefix = "" # No prefix, directly use env var names
        
    
    
@lru_cache()
def get_settings() -> Settings:
    """Get application settings."""
    settings = Settings()
    print(f"DEBUG: Pydantic Settings Loaded: {settings.model_dump_json()}")
    return settings
