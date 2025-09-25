"""
High-performance caching service using DiskCache for OrderBot
Provides multi-layered caching for analytics, AI responses, and database queries
"""
import os
import json
import logging
from functools import wraps
from typing import Dict, Any, Optional, List, Union
from datetime import datetime, timedelta

import diskcache as dc
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

class CacheService:
    """
    Enterprise-grade caching service with multiple cache strategies
    """
    
    def __init__(self, cache_dir: str = "./cache", max_size: int = 1e9):
        """
        Initialize cache service with disk-based storage
        
        Args:
            cache_dir: Directory for cache storage
            max_size: Maximum cache size in bytes (default 1GB)
        """
        self.cache_dir = cache_dir
        
        # Ensure cache directory exists
        os.makedirs(cache_dir, exist_ok=True)
        
        # Initialize different cache stores for different data types
        self.main_cache = dc.Cache(
            os.path.join(cache_dir, "main"),
            size_limit=max_size * 0.6,  # 60% for main cache
            eviction_policy='least-recently-used'
        )
        
        self.analytics_cache = dc.Cache(
            os.path.join(cache_dir, "analytics"),
            size_limit=max_size * 0.2,  # 20% for analytics
            eviction_policy='least-recently-used'
        )
        
        self.ai_cache = dc.Cache(
            os.path.join(cache_dir, "ai_responses"),
            size_limit=max_size * 0.15,  # 15% for AI responses
            eviction_policy='least-recently-used'
        )
        
        self.session_cache = dc.Cache(
            os.path.join(cache_dir, "sessions"),
            size_limit=max_size * 0.05,  # 5% for session data
            eviction_policy='least-recently-used'
        )
        
        logger.info(f"CacheService initialized with {max_size/1e6:.0f}MB capacity")
    
    def cached(self, expire_seconds: int = 3600, cache_type: str = "main"):
        """
        Decorator for caching function results
        
        Args:
            expire_seconds: Cache expiration time in seconds
            cache_type: Type of cache to use (main, analytics, ai, session)
        """
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                # Select appropriate cache
                cache_store = getattr(self, f"{cache_type}_cache", self.main_cache)
                
                # Generate cache key from function name and arguments
                cache_key = self._generate_cache_key(func.__name__, args, kwargs)
                
                # Try to get from cache
                cached_result = cache_store.get(cache_key)
                if cached_result is not None:
                    logger.debug(f"Cache HIT for {func.__name__}: {cache_key}")
                    return cached_result
                
                # Execute function and cache result
                result = func(*args, **kwargs)
                cache_store.set(cache_key, result, expire=expire_seconds)
                logger.debug(f"Cache MISS for {func.__name__}: {cache_key} (cached for {expire_seconds}s)")
                
                return result
            return wrapper
        return decorator
    
    def _generate_cache_key(self, func_name: str, args: tuple, kwargs: dict) -> str:
        """Generate a unique cache key from function name and arguments"""
        # Convert args and kwargs to a hashable string
        key_parts = [func_name]
        
        # Add positional arguments
        for arg in args:
            if hasattr(arg, 'id'):  # Database objects
                key_parts.append(f"{type(arg).__name__}_{arg.id}")
            elif isinstance(arg, (str, int, float, bool)):
                key_parts.append(str(arg))
            else:
                key_parts.append(str(hash(str(arg))))
        
        # Add keyword arguments
        for key, value in sorted(kwargs.items()):
            if hasattr(value, 'id'):
                key_parts.append(f"{key}_{type(value).__name__}_{value.id}")
            elif isinstance(value, (str, int, float, bool)):
                key_parts.append(f"{key}_{value}")
            else:
                key_parts.append(f"{key}_{hash(str(value))}")
        
        return "_".join(key_parts)
    
    # Customer Analytics Caching
    def get_customer_analytics(self, customer_id: int) -> Optional[Dict[str, Any]]:
        """Get cached customer analytics"""
        return self.analytics_cache.get(f"customer_analytics_{customer_id}")
    
    def set_customer_analytics(self, customer_id: int, analytics_data: Dict[str, Any], expire_hours: int = 6):
        """Cache customer analytics data"""
        self.analytics_cache.set(
            f"customer_analytics_{customer_id}", 
            analytics_data, 
            expire=expire_hours * 3600
        )
    
    # Product Recommendation Caching
    def get_product_recommendations(self, customer_id: int, limit: int = 5) -> Optional[List[Dict[str, Any]]]:
        """Get cached product recommendations"""
        return self.analytics_cache.get(f"recommendations_{customer_id}_{limit}")
    
    def set_product_recommendations(self, customer_id: int, recommendations: List[Dict[str, Any]], limit: int = 5):
        """Cache product recommendations"""
        self.analytics_cache.set(
            f"recommendations_{customer_id}_{limit}",
            recommendations,
            expire=1800  # 30 minutes
        )
    
    # AI Response Caching
    def get_ai_response(self, prompt_hash: str) -> Optional[str]:
        """Get cached AI response for similar prompts"""
        return self.ai_cache.get(f"ai_response_{prompt_hash}")
    
    def set_ai_response(self, prompt_hash: str, response: str):
        """Cache AI response to avoid repeated API calls"""
        self.ai_cache.set(
            f"ai_response_{prompt_hash}",
            response,
            expire=3600  # 1 hour
        )
    
    # Conversation Context Caching
    def get_conversation_context(self, customer_id: int) -> Optional[Dict[str, Any]]:
        """Get cached conversation context"""
        return self.session_cache.get(f"conversation_{customer_id}")
    
    def set_conversation_context(self, customer_id: int, context: Dict[str, Any]):
        """Cache conversation context for quick access"""
        self.session_cache.set(
            f"conversation_{customer_id}",
            context,
            expire=1800  # 30 minutes
        )
    
    # Inventory Caching
    def get_product_availability(self, product_id: int, variant_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Get cached product availability"""
        cache_key = f"availability_{product_id}"
        if variant_id:
            cache_key += f"_variant_{variant_id}"
        return self.main_cache.get(cache_key)
    
    def set_product_availability(self, product_id: int, availability_data: Dict[str, Any], variant_id: Optional[int] = None):
        """Cache product availability data"""
        cache_key = f"availability_{product_id}"
        if variant_id:
            cache_key += f"_variant_{variant_id}"
        self.main_cache.set(cache_key, availability_data, expire=300)  # 5 minutes
    
    # Business Configuration Caching
    def get_business_config(self, group_id: int) -> Optional[Dict[str, Any]]:
        """Get cached business configuration"""
        return self.main_cache.get(f"business_config_{group_id}")
    
    def set_business_config(self, group_id: int, config_data: Dict[str, Any]):
        """Cache business configuration"""
        self.main_cache.set(
            f"business_config_{group_id}",
            config_data,
            expire=7200  # 2 hours
        )
    
    # Menu/Product Catalog Caching
    def get_menu_items(self, group_id: int, category: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
        """Get cached menu items"""
        cache_key = f"menu_{group_id}"
        if category:
            cache_key += f"_category_{category}"
        return self.main_cache.get(cache_key)
    
    def set_menu_items(self, group_id: int, menu_items: List[Dict[str, Any]], category: Optional[str] = None):
        """Cache menu items"""
        cache_key = f"menu_{group_id}"
        if category:
            cache_key += f"_category_{category}"
        self.main_cache.set(cache_key, menu_items, expire=3600)  # 1 hour
    
    # Order Statistics Caching
    def get_order_stats(self, group_id: int, date_range: str = "today") -> Optional[Dict[str, Any]]:
        """Get cached order statistics"""
        return self.analytics_cache.get(f"order_stats_{group_id}_{date_range}")
    
    def set_order_stats(self, group_id: int, stats_data: Dict[str, Any], date_range: str = "today"):
        """Cache order statistics"""
        # Shorter cache for real-time stats
        expire_time = 300 if date_range == "today" else 1800  # 5min for today, 30min for others
        self.analytics_cache.set(
            f"order_stats_{group_id}_{date_range}",
            stats_data,
            expire=expire_time
        )
    
    # Cache Management
    def clear_cache(self, cache_type: Optional[str] = None):
        """Clear specific cache type or all caches"""
        if cache_type:
            cache_store = getattr(self, f"{cache_type}_cache", None)
            if cache_store:
                cache_store.clear()
                logger.info(f"Cleared {cache_type} cache")
        else:
            # Clear all caches
            for cache_name in ["main_cache", "analytics_cache", "ai_cache", "session_cache"]:
                cache_store = getattr(self, cache_name)
                cache_store.clear()
            logger.info("Cleared all caches")
    
    def get_cache_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get statistics for all cache stores"""
        stats = {}
        
        for cache_name in ["main", "analytics", "ai", "session"]:
            cache_store = getattr(self, f"{cache_name}_cache")
            stats[cache_name] = {
                "size": len(cache_store),
                "volume": cache_store.volume(),
                "hits": getattr(cache_store, 'hits', 0),
                "misses": getattr(cache_store, 'misses', 0)
            }
        
        return stats
    
    def invalidate_customer_cache(self, customer_id: int):
        """Invalidate all cache entries for a specific customer"""
        patterns = [
            f"customer_analytics_{customer_id}",
            f"recommendations_{customer_id}_*",
            f"conversation_{customer_id}"
        ]
        
        for pattern in patterns:
            if "*" in pattern:
                # For patterns with wildcards, we need to iterate
                base_pattern = pattern.replace("_*", "")
                for cache_name in ["main_cache", "analytics_cache", "session_cache"]:
                    cache_store = getattr(self, cache_name)
                    keys_to_delete = [key for key in cache_store if key.startswith(base_pattern)]
                    for key in keys_to_delete:
                        cache_store.delete(key)
            else:
                # Direct key deletion
                for cache_name in ["main_cache", "analytics_cache", "session_cache"]:
                    cache_store = getattr(self, cache_name)
                    cache_store.delete(pattern)
        
        logger.info(f"Invalidated cache for customer {customer_id}")

# Global cache service instance
_cache_service = None

def get_cache_service() -> CacheService:
    """Get the global cache service instance"""
    global _cache_service
    if _cache_service is None:
        _cache_service = CacheService()
    return _cache_service

# Convenience decorators for common caching patterns
def cache_analytics(expire_hours: int = 6):
    """Decorator for caching analytics functions"""
    return get_cache_service().cached(expire_seconds=expire_hours * 3600, cache_type="analytics")

def cache_ai_response(expire_minutes: int = 60):
    """Decorator for caching AI responses"""
    return get_cache_service().cached(expire_seconds=expire_minutes * 60, cache_type="ai")

def cache_database_query(expire_minutes: int = 30):
    """Decorator for caching database queries"""
    return get_cache_service().cached(expire_seconds=expire_minutes * 60, cache_type="main")