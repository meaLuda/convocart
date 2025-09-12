"""
Rate Limiter Service for API calls
Prevents hitting Gemini API rate limits and implements exponential backoff
"""
import asyncio
import time
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from functools import wraps
from collections import defaultdict, deque

logger = logging.getLogger(__name__)

class RateLimiter:
    """
    Token bucket rate limiter with exponential backoff
    Handles both RPM (Requests Per Minute) and TPM (Tokens Per Minute) limits
    """
    
    def __init__(
        self,
        requests_per_minute: int = 15,  # Conservative for Gemini 2.0 Flash
        tokens_per_minute: int = 32000,  # Gemini Flash TPM limit
        requests_per_day: int = 1500,   # Conservative daily limit
        max_retries: int = 3,
        base_delay: float = 1.0
    ):
        self.rpm_limit = requests_per_minute
        self.tpm_limit = tokens_per_minute
        self.rpd_limit = requests_per_day
        self.max_retries = max_retries
        self.base_delay = base_delay
        
        # Rate limiting state
        self.request_times = deque()
        self.token_usage = deque()
        self.daily_requests = defaultdict(int)
        self.last_request_time = 0
        self._lock = asyncio.Lock()
        
        logger.info(f"RateLimiter initialized: {requests_per_minute} RPM, {tokens_per_minute} TPM, {requests_per_day} RPD")
    
    async def wait_if_needed(self, estimated_tokens: int = 1000) -> bool:
        """
        Check if we need to wait before making a request
        Returns True if request can proceed, False if daily limit exceeded
        """
        async with self._lock:
            now = time.time()
            today = datetime.now().strftime('%Y-%m-%d')
            
            # Clean old request times (older than 1 minute)
            minute_ago = now - 60
            while self.request_times and self.request_times[0] < minute_ago:
                self.request_times.popleft()
            
            # Clean old token usage (older than 1 minute)
            while self.token_usage and self.token_usage[0][0] < minute_ago:
                self.token_usage.popleft()
            
            # Check daily limit
            if self.daily_requests[today] >= self.rpd_limit:
                logger.warning(f"Daily request limit ({self.rpd_limit}) exceeded")
                return False
            
            # Check RPM limit
            if len(self.request_times) >= self.rpm_limit:
                sleep_time = 60 - (now - self.request_times[0])
                if sleep_time > 0:
                    logger.info(f"Rate limit hit, waiting {sleep_time:.2f} seconds")
                    await asyncio.sleep(sleep_time)
                    return await self.wait_if_needed(estimated_tokens)
            
            # Check TPM limit
            current_tokens = sum(tokens for _, tokens in self.token_usage)
            if current_tokens + estimated_tokens > self.tpm_limit:
                # Find when oldest tokens will expire
                if self.token_usage:
                    sleep_time = 60 - (now - self.token_usage[0][0])
                    if sleep_time > 0:
                        logger.info(f"Token limit hit, waiting {sleep_time:.2f} seconds")
                        await asyncio.sleep(sleep_time)
                        return await self.wait_if_needed(estimated_tokens)
            
            # Record this request
            self.request_times.append(now)
            self.token_usage.append((now, estimated_tokens))
            self.daily_requests[today] += 1
            self.last_request_time = now
            
            return True
    
    def get_current_usage(self) -> Dict[str, Any]:
        """Get current rate limiting statistics"""
        now = time.time()
        today = datetime.now().strftime('%Y-%m-%d')
        
        # Count requests in last minute
        minute_ago = now - 60
        recent_requests = sum(1 for t in self.request_times if t > minute_ago)
        
        # Count tokens in last minute
        recent_tokens = sum(tokens for t, tokens in self.token_usage if t > minute_ago)
        
        return {
            "requests_this_minute": recent_requests,
            "rpm_limit": self.rpm_limit,
            "tokens_this_minute": recent_tokens,
            "tpm_limit": self.tpm_limit,
            "requests_today": self.daily_requests[today],
            "daily_limit": self.rpd_limit,
            "last_request": datetime.fromtimestamp(self.last_request_time).isoformat() if self.last_request_time else None
        }

def rate_limited_api_call(
    rate_limiter: RateLimiter,
    estimated_tokens: int = 1000,
    max_retries: int = 3
):
    """
    Decorator for rate-limited API calls with exponential backoff
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt in range(max_retries + 1):
                try:
                    # Wait if rate limit would be exceeded
                    can_proceed = await rate_limiter.wait_if_needed(estimated_tokens)
                    if not can_proceed:
                        raise Exception("Daily API quota exceeded")
                    
                    # Make the API call
                    result = await func(*args, **kwargs)
                    return result
                    
                except Exception as e:
                    error_msg = str(e).lower()
                    
                    # Check if this is a rate limit error (429)
                    is_rate_limit_error = (
                        '429' in error_msg or 
                        'rate limit' in error_msg or 
                        'quota exceeded' in error_msg or
                        'too many requests' in error_msg
                    )
                    
                    if is_rate_limit_error and attempt < max_retries:
                        # Exponential backoff with jitter
                        delay = rate_limiter.base_delay * (2 ** attempt)
                        jitter = delay * 0.1  # 10% jitter
                        sleep_time = delay + jitter
                        
                        logger.warning(f"Rate limit hit (attempt {attempt + 1}), retrying in {sleep_time:.2f}s")
                        await asyncio.sleep(sleep_time)
                        continue
                    
                    # Non-rate-limit error or max retries exceeded
                    logger.error(f"API call failed after {attempt + 1} attempts: {e}")
                    raise e
            
        return wrapper
    return decorator

# Global rate limiter instance
_global_rate_limiter = None

def get_rate_limiter() -> RateLimiter:
    """Get or create global rate limiter instance"""
    global _global_rate_limiter
    if _global_rate_limiter is None:
        from app.config import get_settings
        settings = get_settings()
        
        # Adjust limits based on environment
        rpm = 15 if not settings.debug else 5  # More conservative in production
        _global_rate_limiter = RateLimiter(
            requests_per_minute=rpm,
            tokens_per_minute=32000,
            requests_per_day=1500
        )
    
    return _global_rate_limiter

async def test_rate_limiter():
    """Test function for rate limiter"""
    limiter = get_rate_limiter()
    
    for i in range(20):
        can_proceed = await limiter.wait_if_needed(1000)
        if can_proceed:
            print(f"Request {i+1}: Proceeded")
            usage = limiter.get_current_usage()
            print(f"  Usage: {usage['requests_this_minute']}/{usage['rpm_limit']} RPM")
        else:
            print(f"Request {i+1}: Daily limit exceeded")
            break

if __name__ == "__main__":
    asyncio.run(test_rate_limiter())