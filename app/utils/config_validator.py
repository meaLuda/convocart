"""
Production Configuration Validator
Ensures all required environment variables are set for secure production deployment
"""
import os
import logging
import secrets
import string
from typing import List, Dict, Any
from app.config import get_settings

logger = logging.getLogger(__name__)

class ConfigValidator:
    """Validates configuration for production deployment"""
    
    @staticmethod
    def validate_production_config() -> Dict[str, Any]:
        """
        Comprehensive validation of production configuration
        Returns validation status and any issues found
        """
        issues = []
        warnings = []
        
        try:
            settings = get_settings()
        except Exception as e:
            return {
                "valid": False,
                "critical_issues": [f"Failed to load configuration: {str(e)}"],
                "warnings": [],
                "recommendations": ["Check .env file format and required variables"]
            }
        
        # Only enforce strict validation in production environment
        is_production = settings.environment == "production"
        
        # Check critical security settings
        if settings.debug and is_production:
            issues.append("DEBUG mode is enabled - must be False in production")
        
        # Validate required secrets (strict in production, warnings in development)
        required_secrets = [
            "SECRET_KEY",
            "SESSION_SECRET_KEY", 
            "ADMIN_USERNAME",
            "ADMIN_PASSWORD"
        ]
        
        for secret in required_secrets:
            value = getattr(settings, secret.lower(), None)
            if not value:
                if is_production:
                    issues.append(f"{secret} is not set - required for production")
                else:
                    warnings.append(f"{secret} is not set - should be configured for production")
            elif secret in ["SECRET_KEY", "SESSION_SECRET_KEY"]:
                if len(value) < 32:
                    if is_production:
                        issues.append(f"{secret} is too short - minimum 32 characters required")
                    else:
                        warnings.append(f"{secret} is too short - minimum 32 characters recommended")
                if value in ["default_secret_key", "your-session-secret-key-change-in-production"]:
                    if is_production:
                        issues.append(f"{secret} contains default/example value - must be changed")
                    else:
                        warnings.append(f"{secret} contains default/example value - should be changed for production")
        
        # Validate admin credentials strength
        if hasattr(settings, 'admin_password') and settings.admin_password:
            if len(settings.admin_password) < 12:
                if is_production:
                    issues.append("Admin password should be at least 12 characters")
                else:
                    warnings.append("Admin password should be at least 12 characters")
            if settings.admin_password.lower() in ["password", "admin", "convocart"]:
                if is_production:
                    issues.append("Admin password is too weak - avoid common words")
                else:
                    warnings.append("Admin password is too weak - avoid common words")
        
        # Check database configuration
        if not settings.database_url:
            issues.append("DATABASE_URL is not set")
        elif "password" in settings.database_url.lower() and "@localhost" in settings.database_url:
            warnings.append("Database appears to be localhost - ensure production DB is configured")
        
        # Check Twilio configuration
        twilio_required = ["twilio_account_sid", "twilio_auth_token", "twilio_whatsapp_number"]
        for field in twilio_required:
            if not getattr(settings, field, None):
                issues.append(f"{field.upper()} is not set - required for WhatsApp functionality")
        
        # Check security settings
        if not settings.session_cookie_secure and settings.environment == "production":
            warnings.append("Session cookies should be secure in production (HTTPS only)")
        
        # Check CORS settings
        if hasattr(settings, 'cors_origins') and "*" in settings.cors_origins:
            warnings.append("CORS allows all origins - consider restricting in production")
        
        # Validation summary
        is_valid = len(issues) == 0
        
        recommendations = []
        if issues:
            recommendations.append("Fix all critical issues before production deployment")
        if warnings:
            recommendations.append("Review warnings for additional security improvements")
        
        return {
            "valid": is_valid,
            "critical_issues": issues,
            "warnings": warnings,
            "recommendations": recommendations
        }
    
    @staticmethod
    def generate_secure_secrets() -> Dict[str, str]:
        """Generate secure random secrets for production"""
        return {
            "SECRET_KEY": ConfigValidator._generate_secret_key(64),
            "SESSION_SECRET_KEY": ConfigValidator._generate_secret_key(64),
            "ADMIN_PASSWORD": ConfigValidator._generate_admin_password()
        }
    
    @staticmethod
    def _generate_secret_key(length: int = 64) -> str:
        """Generate a cryptographically secure secret key"""
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*()_+-="
        return ''.join(secrets.choice(alphabet) for _ in range(length))
    
    @staticmethod
    def _generate_admin_password() -> str:
        """Generate a secure admin password"""
        # 16 character password with mixed case, numbers, and symbols
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        return ''.join(secrets.choice(alphabet) for _ in range(16))
    
    @staticmethod
    def create_production_env_template() -> str:
        """Create a template .env.production file with secure defaults"""
        secrets_dict = ConfigValidator.generate_secure_secrets()
        
        template = f"""# ConvoCart Production Environment Configuration
# CRITICAL: Set all required values before deployment

# Server Configuration
HOST=0.0.0.0
PORT=8000
DEBUG=false
ENVIRONMENT=production

# Security Keys (GENERATED - Change these values)
SECRET_KEY={secrets_dict['SECRET_KEY']}
SESSION_SECRET_KEY={secrets_dict['SESSION_SECRET_KEY']}

# Admin Credentials (CHANGE THESE)
ADMIN_USERNAME=admin
ADMIN_PASSWORD={secrets_dict['ADMIN_PASSWORD']}
ALGORITHM=HS256

# Database Configuration (PostgreSQL)
DATABASE_URL=postgresql://username:password@hostname:5432/database_name

# Twilio WhatsApp API (Required)
TWILIO_ACCOUNT_SID=your_twilio_account_sid
TWILIO_AUTH_TOKEN=your_twilio_auth_token
TWILIO_WHATSAPP_NUMBER=+1234567890
WEBHOOK_VERIFY_TOKEN=your_webhook_verify_token
TWILIO_WEBHOOK_AUTH_ENABLED=true
TWILIO_QUICK_REPLY_TEMPLATE_SID=your_template_sid

# AI Configuration (Optional)
GEMINI_API_KEY=your_gemini_api_key
AI_MODEL_NAME=gemini-2.0-flash-exp
AI_TEMPERATURE=0.3
AI_MAX_TOKENS=1000
ENABLE_AI_AGENT=true
AI_CONVERSATION_MEMORY=true
AI_DEBUG_MODE=false

# Redis Cache Configuration
REDIS_URL=redis://localhost:6379
REDIS_PASSWORD=
REDIS_DB=0
REDIS_MAX_CONNECTIONS=20
CACHE_TTL=300

# Session Security
SESSION_COOKIE_NAME=session_id
SESSION_COOKIE_MAX_AGE=3600
SESSION_COOKIE_SECURE=true
SESSION_COOKIE_HTTPONLY=true
SESSION_COOKIE_SAMESITE=lax
SESSION_COOKIE_DOMAIN=

# Security Headers
SECURITY_HEADERS_ENABLED=true
HSTS_MAX_AGE=31536000
CSP_POLICY=default-src 'self'; script-src 'self' 'unsafe-inline' cdnjs.cloudflare.com unpkg.com code.jquery.com cdn.jsdelivr.net cdn.datatables.net; style-src 'self' 'unsafe-inline' cdnjs.cloudflare.com cdn.jsdelivr.net cdn.datatables.net fonts.googleapis.com; img-src 'self' data:; font-src 'self' cdnjs.cloudflare.com fonts.gstatic.com; connect-src 'self' cdnjs.cloudflare.com

# CORS Configuration
CORS_ORIGINS=["https://yourdomain.com"]
CORS_ALLOW_CREDENTIALS=true
"""
        return template

def validate_config_on_startup():
    """Validate configuration during application startup"""
    validation_result = ConfigValidator.validate_production_config()
    
    if not validation_result["valid"]:
        logger.error("❌ CRITICAL CONFIGURATION ISSUES FOUND:")
        for issue in validation_result["critical_issues"]:
            logger.error(f"   • {issue}")
        
        if validation_result["warnings"]:
            logger.warning("⚠️ CONFIGURATION WARNINGS:")
            for warning in validation_result["warnings"]:
                logger.warning(f"   • {warning}")
        
        raise RuntimeError("Configuration validation failed. Fix issues before starting application.")
    
    if validation_result["warnings"]:
        logger.warning("⚠️ CONFIGURATION WARNINGS:")
        for warning in validation_result["warnings"]:
            logger.warning(f"   • {warning}")
    
    logger.info("✅ Configuration validation passed")
    return True