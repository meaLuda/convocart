"""
API Usage Monitoring Service
Tracks API usage, quotas, and provides analytics for Gemini API calls
"""
import asyncio
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import Column, Integer, String, DateTime, Float, Boolean, Text, JSON
from sqlalchemy.ext.declarative import declarative_base
from collections import defaultdict
import json

from app.database import Base
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

class APIUsageLog(Base):
    """Model to track API usage"""
    __tablename__ = "api_usage_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    api_provider = Column(String(50), nullable=False)  # 'gemini', 'whatsapp', etc.
    api_method = Column(String(100), nullable=False)   # 'chat_completion', 'send_message', etc.
    customer_id = Column(Integer, nullable=True)
    group_id = Column(Integer, nullable=True)
    
    # Request details
    tokens_used = Column(Integer, default=0)
    estimated_tokens = Column(Integer, default=0)
    response_tokens = Column(Integer, default=0)
    
    # Response details
    success = Column(Boolean, default=True)
    response_time_ms = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)
    error_code = Column(String(20), nullable=True)
    
    # Cost tracking
    estimated_cost = Column(Float, default=0.0)
    
    # Additional metadata
    api_metadata = Column(JSON, nullable=True)

class APIMonitor:
    """
    Service to monitor and track API usage across all providers
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.settings = settings
        
        # Pricing per 1000 tokens (USD)
        self.pricing = {
            "gemini-2.0-flash-exp": {
                "input": 0.000075,    # $0.075 per 1M tokens
                "output": 0.0003      # $0.30 per 1M tokens
            },
            "gemini-1.5-flash": {
                "input": 0.000075,
                "output": 0.0003
            }
        }
        
        # Daily limits
        self.daily_limits = {
            "gemini_requests": 1500,
            "gemini_tokens": 1500000,  # 1.5M tokens per day
            "whatsapp_messages": 1000  # Conservative limit
        }
        
    async def log_api_call(
        self,
        api_provider: str,
        api_method: str,
        success: bool = True,
        tokens_used: int = 0,
        estimated_tokens: int = 0,
        response_tokens: int = 0,
        response_time_ms: Optional[float] = None,
        error_message: Optional[str] = None,
        error_code: Optional[str] = None,
        customer_id: Optional[int] = None,
        group_id: Optional[int] = None,
        metadata: Optional[Dict] = None
    ) -> APIUsageLog:
        """
        Log an API call for monitoring and analytics
        """
        try:
            # Calculate estimated cost
            estimated_cost = self._calculate_cost(api_provider, tokens_used, response_tokens)
            
            log_entry = APIUsageLog(
                api_provider=api_provider,
                api_method=api_method,
                customer_id=customer_id,
                group_id=group_id,
                tokens_used=tokens_used,
                estimated_tokens=estimated_tokens,
                response_tokens=response_tokens,
                success=success,
                response_time_ms=response_time_ms,
                error_message=error_message,
                error_code=error_code,
                estimated_cost=estimated_cost,
                api_metadata=metadata
            )
            
            self.db.add(log_entry)
            self.db.commit()
            
            # Check for usage alerts
            await self._check_usage_alerts(api_provider)
            
            return log_entry
            
        except Exception as e:
            logger.error(f"Error logging API call: {str(e)}")
            self.db.rollback()
            raise e
    
    def _calculate_cost(self, api_provider: str, input_tokens: int, output_tokens: int) -> float:
        """Calculate estimated cost based on token usage"""
        if api_provider not in ["gemini", "gemini-2.0-flash-exp"]:
            return 0.0
        
        model_key = "gemini-2.0-flash-exp" if api_provider == "gemini" else api_provider
        pricing = self.pricing.get(model_key, {"input": 0, "output": 0})
        
        input_cost = (input_tokens / 1000) * pricing["input"]
        output_cost = (output_tokens / 1000) * pricing["output"]
        
        return input_cost + output_cost
    
    async def get_usage_stats(
        self,
        days: int = 1,
        api_provider: Optional[str] = None,
        group_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get usage statistics for specified period
        """
        try:
            start_date = datetime.utcnow() - timedelta(days=days)
            
            query = self.db.query(APIUsageLog).filter(
                APIUsageLog.timestamp >= start_date
            )
            
            if api_provider:
                query = query.filter(APIUsageLog.api_provider == api_provider)
            
            if group_id:
                query = query.filter(APIUsageLog.group_id == group_id)
            
            logs = query.all()
            
            # Calculate statistics
            total_calls = len(logs)
            successful_calls = len([log for log in logs if log.success])
            failed_calls = total_calls - successful_calls
            total_tokens = sum(log.tokens_used for log in logs)
            total_cost = sum(log.estimated_cost for log in logs)
            
            avg_response_time = 0
            if logs:
                response_times = [log.response_time_ms for log in logs if log.response_time_ms]
                avg_response_time = sum(response_times) / len(response_times) if response_times else 0
            
            # Group by API provider
            provider_stats = defaultdict(lambda: {
                "calls": 0, "tokens": 0, "cost": 0.0, "errors": 0
            })
            
            for log in logs:
                provider = log.api_provider
                provider_stats[provider]["calls"] += 1
                provider_stats[provider]["tokens"] += log.tokens_used
                provider_stats[provider]["cost"] += log.estimated_cost
                if not log.success:
                    provider_stats[provider]["errors"] += 1
            
            # Daily breakdown
            daily_stats = defaultdict(lambda: {"calls": 0, "tokens": 0, "cost": 0.0})
            for log in logs:
                day_key = log.timestamp.strftime('%Y-%m-%d')
                daily_stats[day_key]["calls"] += 1
                daily_stats[day_key]["tokens"] += log.tokens_used
                daily_stats[day_key]["cost"] += log.estimated_cost
            
            return {
                "period": f"Last {days} days",
                "summary": {
                    "total_calls": total_calls,
                    "successful_calls": successful_calls,
                    "failed_calls": failed_calls,
                    "success_rate": (successful_calls / total_calls * 100) if total_calls > 0 else 0,
                    "total_tokens": total_tokens,
                    "total_cost": total_cost,
                    "average_response_time_ms": avg_response_time
                },
                "by_provider": dict(provider_stats),
                "daily_breakdown": dict(daily_stats)
            }
            
        except Exception as e:
            logger.error(f"Error getting usage stats: {str(e)}")
            return {}
    
    async def get_current_quota_usage(self) -> Dict[str, Any]:
        """
        Get current quota usage for today
        """
        try:
            today = datetime.utcnow().strftime('%Y-%m-%d')
            start_of_day = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            
            # Get today's usage
            today_logs = self.db.query(APIUsageLog).filter(
                APIUsageLog.timestamp >= start_of_day
            ).all()
            
            gemini_calls = len([log for log in today_logs if log.api_provider == "gemini"])
            gemini_tokens = sum(log.tokens_used for log in today_logs if log.api_provider == "gemini")
            whatsapp_calls = len([log for log in today_logs if log.api_provider == "whatsapp"])
            
            return {
                "date": today,
                "gemini": {
                    "requests": gemini_calls,
                    "requests_limit": self.daily_limits["gemini_requests"],
                    "requests_percentage": (gemini_calls / self.daily_limits["gemini_requests"] * 100),
                    "tokens": gemini_tokens,
                    "tokens_limit": self.daily_limits["gemini_tokens"],
                    "tokens_percentage": (gemini_tokens / self.daily_limits["gemini_tokens"] * 100)
                },
                "whatsapp": {
                    "requests": whatsapp_calls,
                    "requests_limit": self.daily_limits["whatsapp_messages"],
                    "requests_percentage": (whatsapp_calls / self.daily_limits["whatsapp_messages"] * 100)
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting quota usage: {str(e)}")
            return {}
    
    async def _check_usage_alerts(self, api_provider: str):
        """
        Check if usage is approaching limits and log warnings
        """
        try:
            quota_usage = await self.get_current_quota_usage()
            
            if api_provider == "gemini":
                gemini_data = quota_usage.get("gemini", {})
                requests_pct = gemini_data.get("requests_percentage", 0)
                tokens_pct = gemini_data.get("tokens_percentage", 0)
                
                if requests_pct > 90:
                    logger.warning(f"Gemini API requests at {requests_pct:.1f}% of daily limit")
                elif requests_pct > 75:
                    logger.info(f"Gemini API requests at {requests_pct:.1f}% of daily limit")
                
                if tokens_pct > 90:
                    logger.warning(f"Gemini API tokens at {tokens_pct:.1f}% of daily limit")
                elif tokens_pct > 75:
                    logger.info(f"Gemini API tokens at {tokens_pct:.1f}% of daily limit")
            
        except Exception as e:
            logger.error(f"Error checking usage alerts: {str(e)}")
    
    async def get_error_analysis(self, days: int = 7) -> Dict[str, Any]:
        """
        Analyze API errors over the specified period
        """
        try:
            start_date = datetime.utcnow() - timedelta(days=days)
            
            error_logs = self.db.query(APIUsageLog).filter(
                APIUsageLog.timestamp >= start_date,
                APIUsageLog.success == False
            ).all()
            
            if not error_logs:
                return {"total_errors": 0, "error_types": {}, "recommendations": []}
            
            # Group errors by type
            error_types = defaultdict(int)
            rate_limit_errors = 0
            
            for log in error_logs:
                error_code = log.error_code or "unknown"
                error_types[error_code] += 1
                
                if "429" in str(log.error_code) or "rate limit" in str(log.error_message).lower():
                    rate_limit_errors += 1
            
            recommendations = []
            if rate_limit_errors > 0:
                recommendations.append("Consider implementing more aggressive rate limiting")
            
            if error_types.get("quota_exceeded", 0) > 0:
                recommendations.append("Monitor daily quota usage more closely")
            
            return {
                "total_errors": len(error_logs),
                "error_types": dict(error_types),
                "rate_limit_errors": rate_limit_errors,
                "recommendations": recommendations
            }
            
        except Exception as e:
            logger.error(f"Error analyzing errors: {str(e)}")
            return {}

# Global monitor instance
_global_monitor = None

def get_api_monitor(db: Session) -> APIMonitor:
    """Get or create global API monitor instance"""
    return APIMonitor(db)

# Decorator for automatic API monitoring
def monitor_api_call(
    api_provider: str,
    api_method: str,
    estimate_tokens: bool = True
):
    """
    Decorator to automatically monitor API calls
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            start_time = datetime.utcnow()
            success = True
            error_message = None
            error_code = None
            tokens_used = 0
            response_tokens = 0
            
            try:
                result = await func(*args, **kwargs)
                
                # Try to extract token usage from result
                if hasattr(result, 'usage'):
                    tokens_used = getattr(result.usage, 'prompt_tokens', 0)
                    response_tokens = getattr(result.usage, 'completion_tokens', 0)
                
                return result
                
            except Exception as e:
                success = False
                error_message = str(e)
                
                if "429" in error_message:
                    error_code = "429"
                elif "quota" in error_message.lower():
                    error_code = "quota_exceeded"
                else:
                    error_code = "api_error"
                
                raise e
                
            finally:
                # Log the API call
                response_time = (datetime.utcnow() - start_time).total_seconds() * 1000
                
                try:
                    # Extract database session from args (assuming it's available)
                    db = None
                    for arg in args:
                        if hasattr(arg, 'db') and hasattr(arg.db, 'add'):
                            db = arg.db
                            break
                    
                    if db:
                        monitor = get_api_monitor(db)
                        await monitor.log_api_call(
                            api_provider=api_provider,
                            api_method=api_method,
                            success=success,
                            tokens_used=tokens_used,
                            response_tokens=response_tokens,
                            response_time_ms=response_time,
                            error_message=error_message,
                            error_code=error_code
                        )
                except Exception as log_error:
                    logger.error(f"Failed to log API call: {log_error}")
        
        return wrapper
    return decorator