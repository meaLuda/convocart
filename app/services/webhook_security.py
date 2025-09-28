"""
Webhook Security Service for Twilio Signature Validation
"""
import logging
import hmac
import hashlib
import base64
from typing import Dict, Any, Optional
from urllib.parse import urlencode, urlparse
from fastapi import Request, HTTPException, Depends
from twilio.request_validator import RequestValidator
from app.config import get_settings

logger = logging.getLogger(__name__)

class WebhookSecurityService:
    """
    Service for validating Twilio webhook signatures and ensuring webhook security
    """
    
    def __init__(self, auth_token: str):
        """
        Initialize the webhook security service with Twilio auth token
        
        Args:
            auth_token: Twilio auth token for signature validation
        """
        self.auth_token = auth_token
        self.request_validator = RequestValidator(auth_token)
    
    def validate_twilio_signature(
        self, 
        url: str, 
        form_data: Dict[str, Any], 
        signature: str
    ) -> bool:
        """
        Validate Twilio webhook signature using official RequestValidator
        
        Args:
            url: The full URL of the webhook endpoint
            form_data: Dictionary of form parameters sent by Twilio
            signature: The X-Twilio-Signature header value
            
        Returns:
            bool: True if signature is valid, False otherwise
        """
        try:
            # Convert form data to the format expected by RequestValidator
            form_params = {}
            for key, value in form_data.items():
                if isinstance(value, list):
                    # Handle multi-value parameters
                    form_params[key] = value[0] if value else ""
                else:
                    form_params[key] = str(value)
            
            # Validate the signature
            is_valid = self.request_validator.validate(url, form_params, signature)
            
            if not is_valid:
                logger.warning(f"Invalid Twilio signature for URL: {url}")
                logger.debug(f"Form data: {form_params}")
                logger.debug(f"Signature: {signature}")
            
            return is_valid
            
        except Exception as e:
            logger.error(f"Error validating Twilio signature: {str(e)}")
            return False
    
    def validate_request_origin(self, request: Request) -> bool:
        """
        Additional validation to ensure request comes from expected sources
        
        Args:
            request: FastAPI Request object
            
        Returns:
            bool: True if request origin is valid
        """
        try:
            # Check User-Agent header (Twilio sets a specific User-Agent)
            user_agent = request.headers.get("user-agent", "")
            if not user_agent.startswith("TwilioProxy/"):
                logger.warning(f"Unexpected User-Agent: {user_agent}")
                return False
            
            # Check for required Twilio headers
            required_headers = ["x-twilio-signature"]
            for header in required_headers:
                if header not in request.headers:
                    logger.warning(f"Missing required header: {header}")
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error validating request origin: {str(e)}")
            return False
    
    def extract_webhook_url(self, request: Request) -> str:
        """
        Extract the full webhook URL for signature validation
        
        Args:
            request: FastAPI Request object
            
        Returns:
            str: Full webhook URL including query parameters
        """
        # Reconstruct the full URL
        scheme = request.url.scheme
        netloc = request.url.netloc
        path = request.url.path
        query = request.url.query
        
        url = f"{scheme}://{netloc}{path}"
        if query:
            url += f"?{query}"
        
        return url

# Global webhook security service instance
_webhook_security_service: Optional[WebhookSecurityService] = None

def get_webhook_security_service() -> WebhookSecurityService:
    """
    Get or create webhook security service instance
    
    Returns:
        WebhookSecurityService: Configured webhook security service
    """
    global _webhook_security_service
    
    if _webhook_security_service is None:
        settings = get_settings()
        if not settings.twilio_auth_token:
            raise ValueError("Twilio auth token not configured")
        
        _webhook_security_service = WebhookSecurityService(settings.twilio_auth_token)
    
    return _webhook_security_service

async def validate_twilio_webhook(
    request: Request,
    webhook_security: WebhookSecurityService = Depends(get_webhook_security_service)
) -> Dict[str, Any]:
    """
    FastAPI dependency for validating Twilio webhook signatures
    Returns the parsed form data to avoid double-parsing in the route
    
    Args:
        request: FastAPI Request object
        webhook_security: Webhook security service
        
    Returns:
        Dict[str, Any]: Parsed form/JSON data if validation passes
        
    Raises:
        HTTPException: If webhook validation fails
    """
    try:
        settings = get_settings()
        
        # Skip validation if disabled (for development/testing)
        if not settings.twilio_webhook_auth_enabled:
            logger.warning("Twilio webhook authentication is DISABLED - this should not be used in production!")
            # Still parse and return the data
            return await _parse_webhook_data(request)
        
        # Validate request origin
        if not webhook_security.validate_request_origin(request):
            logger.error("Webhook request origin validation failed")
            raise HTTPException(
                status_code=403, 
                detail="Invalid request origin"
            )
        
        # Get the signature from headers
        signature = request.headers.get("x-twilio-signature")
        if not signature:
            logger.error("Missing X-Twilio-Signature header")
            raise HTTPException(
                status_code=403, 
                detail="Missing signature header"
            )
        
        # Parse the request data
        webhook_data = await _parse_webhook_data(request)
        
        # Only validate signature for form data (Twilio format)
        content_type = request.headers.get("content-type", "")
        if "application/x-www-form-urlencoded" in content_type:
            # Construct the webhook URL
            webhook_url = webhook_security.extract_webhook_url(request)
            
            # Validate the signature
            if not webhook_security.validate_twilio_signature(webhook_url, webhook_data, signature):
                logger.error("Twilio webhook signature validation failed")
                raise HTTPException(
                    status_code=403, 
                    detail="Invalid webhook signature"
                )
        else:
            logger.info(f"Skipping signature validation for content type: {content_type}")
        
        logger.info("Twilio webhook signature validation successful")
        return webhook_data
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Unexpected error in webhook validation: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail="Webhook validation error"
        )

async def _parse_webhook_data(request: Request) -> Dict[str, Any]:
    """
    Parse webhook data from request (JSON or form data)
    
    Args:
        request: FastAPI Request object
        
    Returns:
        Dict[str, Any]: Parsed data
    """
    content_type = request.headers.get("content-type", "")
    
    if "application/json" in content_type:
        return await request.json()
    elif "application/x-www-form-urlencoded" in content_type:
        form_data = await request.form()
        return dict(form_data)
    else:
        # Try JSON first, then form data as fallback
        try:
            return await request.json()
        except:
            form_data = await request.form()
            return dict(form_data)

# Security headers for webhook responses
WEBHOOK_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Content-Security-Policy": "default-src 'none'",
}

def add_security_headers(response_headers: Dict[str, str]) -> Dict[str, str]:
    """
    Add security headers to webhook responses
    
    Args:
        response_headers: Existing response headers
        
    Returns:
        Dict[str, str]: Updated headers with security headers
    """
    response_headers.update(WEBHOOK_SECURITY_HEADERS)
    return response_headers