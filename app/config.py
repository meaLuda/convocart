# app/config.py
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(override=True)

# Server settings
HOST = os.getenv("HOST")
PORT = int(os.getenv("PORT"))
DEBUG = bool(int(os.getenv("DEBUG")))
SECRET_KEY = os.getenv("SECRET_KEY", "default_secret_key")

# WhatsApp API settings
WHATSAPP_API_URL = os.getenv("WHATSAPP_API_URL")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
WHATSAPP_PHONE_NUMBER = os.getenv("WHATSAPP_PHONE_NUMBER")
WHATSAPP_API_TOKEN = os.getenv("WHATSAPP_API_TOKEN")
WEBHOOK_VERIFY_TOKEN = os.getenv("WEBHOOK_VERIFY_TOKEN")

# Database settings
DATABASE_URL = os.getenv("DATABASE_URL")

# Admin credentials
SUPER_ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
SUPER_ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")


