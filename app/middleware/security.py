"""
Security Middleware for FastAPI
Handles security headers, HTTPS redirection, and other security measures
"""
import logging
import time
from typing import Callable
from fastapi import Request, Response
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from app.config import get_settings

logger = logging.getLogger(__name__)

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add security headers to all responses
    """
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.settings = get_settings()
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Process the request
        response = await call_next(request)
        
        # Only add security headers if enabled
        if self.settings.security_headers_enabled:
            self._add_security_headers(response)
        
        return response
    
    def _add_security_headers(self, response: Response):
        """Add comprehensive security headers"""
        
        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        
        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"
        
        # XSS Protection (legacy but still useful)
        response.headers["X-XSS-Protection"] = "1; mode=block"
        
        # HTTP Strict Transport Security (HSTS)
        if self.settings.environment != "development":
            response.headers["Strict-Transport-Security"] = f"max-age={self.settings.hsts_max_age}; includeSubDomains; preload"
        
        # Content Security Policy
        response.headers["Content-Security-Policy"] = self.settings.csp_policy
        
        # Referrer Policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # Permissions Policy (formerly Feature Policy)
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=(), payment=(), "
            "usb=(), magnetometer=(), gyroscope=(), accelerometer=()"
        )
        
        # Cross-Origin Resource Policy
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        
        # Cross-Origin Embedder Policy
        response.headers["Cross-Origin-Embedder-Policy"] = "require-corp"
        
        # Cross-Origin Opener Policy
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        
        # Server Information Hiding
        response.headers["Server"] = "ConvoCart"
        
        # Prevent caching of sensitive pages
        if self._is_sensitive_path(response):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
    
    def _is_sensitive_path(self, response: Response) -> bool:
        """Check if the response is for a sensitive path that shouldn't be cached"""
        # For now, apply no-cache to all admin pages
        # In practice, you might want to be more specific
        return True

class HTTPSRedirectMiddleware(BaseHTTPMiddleware):
    """
    Middleware to redirect HTTP to HTTPS in production
    """
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.settings = get_settings()
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Only enforce HTTPS in production
        if (self.settings.environment == "production" and 
            request.url.scheme == "http" and 
            not self._is_health_check(request)):
            
            # Redirect to HTTPS
            https_url = request.url.replace(scheme="https")
            logger.info(f"Redirecting HTTP to HTTPS: {request.url} -> {https_url}")
            return RedirectResponse(url=str(https_url), status_code=301)
        
        return await call_next(request)
    
    def _is_health_check(self, request: Request) -> bool:
        """Check if this is a health check request that should bypass HTTPS redirect"""
        health_paths = ["/health", "/ping", "/status"]
        return request.url.path in health_paths

class RateLimitingMiddleware(BaseHTTPMiddleware):
    """
    Simple in-memory rate limiting middleware
    In production, use Redis-based rate limiting
    """
    
    def __init__(self, app: ASGIApp, requests_per_minute: int = 60):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.requests = {}  # In production, use Redis
        self.window_size = 60  # 60 seconds
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        client_ip = self._get_client_ip(request)
        current_time = int(time.time())
        window_start = current_time - (current_time % self.window_size)
        
        # Clean old entries
        self._cleanup_old_requests(window_start)
        
        # Check rate limit
        if self._is_rate_limited(client_ip, window_start):
            logger.warning(f"Rate limit exceeded for IP: {client_ip}")
            return Response(
                content="Rate limit exceeded. Please try again later.",
                status_code=429,
                headers={
                    "Retry-After": str(self.window_size),
                    "X-RateLimit-Limit": str(self.requests_per_minute),
                    "X-RateLimit-Remaining": "0"
                }
            )
        
        # Record request
        self._record_request(client_ip, window_start)
        
        response = await call_next(request)
        
        # Add rate limit headers
        remaining = self._get_remaining_requests(client_ip, window_start)
        response.headers["X-RateLimit-Limit"] = str(self.requests_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(window_start + self.window_size)
        
        return response
    
    def _get_client_ip(self, request: Request) -> str:
        """Get client IP, considering proxy headers"""
        # Check for forwarded headers (when behind a proxy)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        return request.client.host if request.client else "unknown"
    
    def _cleanup_old_requests(self, current_window: int):
        """Remove old request records"""
        keys_to_remove = []
        for key in self.requests:
            if "_" in key:
                window = int(key.split("_")[1])
                if window < current_window:
                    keys_to_remove.append(key)
        
        for key in keys_to_remove:
            del self.requests[key]
    
    def _is_rate_limited(self, client_ip: str, window: int) -> bool:
        """Check if client is rate limited"""
        key = f"{client_ip}_{window}"
        return self.requests.get(key, 0) >= self.requests_per_minute
    
    def _record_request(self, client_ip: str, window: int):
        """Record a request for rate limiting"""
        key = f"{client_ip}_{window}"
        self.requests[key] = self.requests.get(key, 0) + 1
    
    def _get_remaining_requests(self, client_ip: str, window: int) -> int:
        """Get remaining requests for the current window"""
        key = f"{client_ip}_{window}"
        used = self.requests.get(key, 0)
        return max(0, self.requests_per_minute - used)

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware for structured request logging
    """
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        
        # Log request
        client_ip = self._get_client_ip(request)
        logger.info(
            f"Request started",
            extra={
                "method": request.method,
                "url": str(request.url),
                "client_ip": client_ip,
                "user_agent": request.headers.get("user-agent"),
                "request_id": id(request)  # Simple request ID
            }
        )
        
        # Process request
        try:
            response = await call_next(request)
            
            # Calculate duration
            duration = time.time() - start_time
            
            # Log response
            logger.info(
                f"Request completed",
                extra={
                    "method": request.method,
                    "url": str(request.url),
                    "status_code": response.status_code,
                    "duration_ms": round(duration * 1000, 2),
                    "client_ip": client_ip,
                    "request_id": id(request)
                }
            )
            
            # Add response time header
            response.headers["X-Response-Time"] = f"{duration:.3f}s"
            
            return response
            
        except Exception as e:
            duration = time.time() - start_time
            logger.error(
                f"Request failed",
                extra={
                    "method": request.method,
                    "url": str(request.url),
                    "error": str(e),
                    "duration_ms": round(duration * 1000, 2),
                    "client_ip": client_ip,
                    "request_id": id(request)
                }
            )
            raise
    
    def _get_client_ip(self, request: Request) -> str:
        """Get client IP, considering proxy headers"""
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        return request.client.host if request.client else "unknown"

class SessionCleanupMiddleware(BaseHTTPMiddleware):
    """
    Middleware to periodically clean up expired sessions
    """
    
    def __init__(self, app: ASGIApp, cleanup_interval: int = 3600):
        super().__init__(app)
        self.cleanup_interval = cleanup_interval  # 1 hour
        self.last_cleanup = time.time()
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Check if cleanup is needed (every hour)
        current_time = time.time()
        if current_time - self.last_cleanup > self.cleanup_interval:
            try:
                from app.services.session_manager import get_session_manager
                session_manager = get_session_manager()
                session_manager.cleanup_expired_sessions()
                self.last_cleanup = current_time
            except Exception as e:
                logger.error(f"Error during session cleanup: {str(e)}")
        
        return await call_next(request)