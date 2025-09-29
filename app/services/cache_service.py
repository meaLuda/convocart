"""
Redis Caching Service for FastAPI
Provides high-performance caching with decorators and cache invalidation
"""
import json
import logging
import hashlib
import pickle
import asyncio
from functools import wraps
from typing import Any, Optional, Union, Dict, List, Callable
from datetime import datetime, timedelta
import redis.asyncio as redis
from redis.asyncio import Redis
from app.config import get_settings

logger = logging.getLogger(__name__)

class CacheService:
    """
    Advanced Redis caching service with async support
    """
    
    def __init__(self, settings):
        self.settings = settings
        self.redis: Optional[Redis] = None
        self.default_ttl = settings.cache_ttl
        self.key_prefix = "convocart"
        
        # In-memory fallback cache for when Redis is unavailable
        self._memory_cache: Dict[str, Dict[str, Any]] = {}
        self._memory_cache_max_size = 1000
        
        logger.info(f"Cache service initialized with TTL={self.default_ttl}s")
    
    async def connect(self):
        """Connect to Redis server"""
        try:
            if self.settings.redis_password:
                self.redis = redis.from_url(
                    self.settings.redis_url,
                    password=self.settings.redis_password,
                    db=self.settings.redis_db,
                    max_connections=self.settings.redis_max_connections,
                    decode_responses=True
                )
            else:
                self.redis = redis.from_url(
                    self.settings.redis_url,
                    db=self.settings.redis_db,
                    max_connections=self.settings.redis_max_connections,
                    decode_responses=True
                )
            
            # Test connection
            await self.redis.ping()
            logger.info("✅ Connected to Redis successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to connect to Redis: {str(e)}")
            logger.warning("Will use in-memory cache as fallback")
            self.redis = None
            return False
    
    async def disconnect(self):
        """Disconnect from Redis"""
        if self.redis:
            await self.redis.close()
            logger.info("Disconnected from Redis")
    
    def _generate_cache_key(self, key: str, namespace: str = "default") -> str:
        """Generate prefixed cache key"""
        return f"{self.key_prefix}:{namespace}:{key}"
    
    def _hash_key(self, data: Any) -> str:
        """Generate hash for complex keys"""
        if isinstance(data, (str, int, float)):
            return str(data)
        
        # For complex objects, create a hash
        serialized = json.dumps(data, sort_keys=True, default=str)
        return hashlib.md5(serialized.encode()).hexdigest()
    
    async def get(self, key: str, namespace: str = "default") -> Optional[Any]:
        """Get value from cache"""
        cache_key = self._generate_cache_key(key, namespace)
        
        try:
            if self.redis:
                # Try Redis first
                value = await self.redis.get(cache_key)
                if value is not None:
                    return self._deserialize(value)
            
            # Fallback to memory cache
            if cache_key in self._memory_cache:
                cache_entry = self._memory_cache[cache_key]
                if cache_entry['expires_at'] > datetime.utcnow():
                    return cache_entry['value']
                else:
                    # Expired entry
                    del self._memory_cache[cache_key]
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting cache key {cache_key}: {str(e)}")
            return None
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None, namespace: str = "default") -> bool:
        """Set value in cache"""
        cache_key = self._generate_cache_key(key, namespace)
        ttl = ttl or self.default_ttl
        
        try:
            serialized_value = self._serialize(value)
            
            if self.redis:
                # Set in Redis
                await self.redis.setex(cache_key, ttl, serialized_value)
            
            # Also set in memory cache as backup
            self._set_memory_cache(cache_key, value, ttl)
            
            return True
            
        except Exception as e:
            logger.error(f"Error setting cache key {cache_key}: {str(e)}")
            return False
    
    async def delete(self, key: str, namespace: str = "default") -> bool:
        """Delete value from cache"""
        cache_key = self._generate_cache_key(key, namespace)
        
        try:
            if self.redis:
                await self.redis.delete(cache_key)
            
            # Also delete from memory cache
            if cache_key in self._memory_cache:
                del self._memory_cache[cache_key]
            
            return True
            
        except Exception as e:
            logger.error(f"Error deleting cache key {cache_key}: {str(e)}")
            return False
    
    async def exists(self, key: str, namespace: str = "default") -> bool:
        """Check if key exists in cache"""
        cache_key = self._generate_cache_key(key, namespace)
        
        try:
            if self.redis:
                return bool(await self.redis.exists(cache_key))
            
            # Check memory cache
            if cache_key in self._memory_cache:
                cache_entry = self._memory_cache[cache_key]
                if cache_entry['expires_at'] > datetime.utcnow():
                    return True
                else:
                    del self._memory_cache[cache_key]
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking cache key {cache_key}: {str(e)}")
            return False
    
    async def invalidate_pattern(self, pattern: str, namespace: str = "default") -> int:
        """Invalidate all keys matching pattern"""
        full_pattern = self._generate_cache_key(pattern, namespace)
        
        try:
            if self.redis:
                keys = await self.redis.keys(full_pattern)
                if keys:
                    return await self.redis.delete(*keys)
            
            # Invalidate from memory cache
            keys_to_delete = [k for k in self._memory_cache.keys() if pattern in k]
            for key in keys_to_delete:
                del self._memory_cache[key]
            
            return len(keys_to_delete)
            
        except Exception as e:
            logger.error(f"Error invalidating pattern {pattern}: {str(e)}")
            return 0
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        stats = {
            'memory_cache_size': len(self._memory_cache),
            'redis_connected': self.redis is not None
        }
        
        try:
            if self.redis:
                info = await self.redis.info()
                stats.update({
                    'redis_used_memory': info.get('used_memory_human', 'N/A'),
                    'redis_connected_clients': info.get('connected_clients', 0),
                    'redis_keyspace_hits': info.get('keyspace_hits', 0),
                    'redis_keyspace_misses': info.get('keyspace_misses', 0),
                })
                
                # Calculate hit rate
                hits = info.get('keyspace_hits', 0)
                misses = info.get('keyspace_misses', 0)
                total = hits + misses
                if total > 0:
                    stats['redis_hit_rate'] = round((hits / total) * 100, 2)
        except Exception as e:
            logger.error(f"Error getting Redis stats: {str(e)}")
        
        return stats
    
    def _serialize(self, value: Any) -> str:
        """Serialize value for storage"""
        try:
            if isinstance(value, (str, int, float, bool)):
                return json.dumps(value)
            else:
                # Use pickle for complex objects, then base64 encode
                import base64
                pickled = pickle.dumps(value)
                return base64.b64encode(pickled).decode('utf-8')
        except Exception:
            # Fallback to JSON
            return json.dumps(value, default=str)
    
    def _deserialize(self, value: str) -> Any:
        """Deserialize value from storage"""
        try:
            # Try JSON first
            return json.loads(value)
        except json.JSONDecodeError:
            try:
                # Try pickle
                import base64
                pickled = base64.b64decode(value.encode('utf-8'))
                return pickle.loads(pickled)
            except Exception:
                # Return as string if all else fails
                return value
    
    def _set_memory_cache(self, key: str, value: Any, ttl: int):
        """Set value in memory cache with size limit"""
        # Clean up expired entries
        self._cleanup_memory_cache()
        
        # If cache is full, remove oldest entries
        if len(self._memory_cache) >= self._memory_cache_max_size:
            # Remove 10% of oldest entries
            sorted_keys = sorted(
                self._memory_cache.keys(),
                key=lambda k: self._memory_cache[k]['created_at']
            )
            keys_to_remove = sorted_keys[:int(self._memory_cache_max_size * 0.1)]
            for k in keys_to_remove:
                del self._memory_cache[k]
        
        expires_at = datetime.utcnow() + timedelta(seconds=ttl)
        self._memory_cache[key] = {
            'value': value,
            'expires_at': expires_at,
            'created_at': datetime.utcnow()
        }
    
    def _cleanup_memory_cache(self):
        """Clean up expired entries from memory cache"""
        current_time = datetime.utcnow()
        expired_keys = [
            k for k, v in self._memory_cache.items()
            if v['expires_at'] <= current_time
        ]
        for key in expired_keys:
            del self._memory_cache[key]
    
    # Application-specific caching methods
    async def get_customer_analytics(self, customer_id: int) -> Optional[Dict[str, Any]]:
        """Get cached customer analytics"""
        return await self.get(f"customer_analytics_{customer_id}", "analytics")
    
    async def set_customer_analytics(self, customer_id: int, analytics_data: Dict[str, Any], expire_hours: int = 6):
        """Cache customer analytics data"""
        return await self.set(f"customer_analytics_{customer_id}", analytics_data, expire_hours * 3600, "analytics")
    
    async def get_product_recommendations(self, customer_id: int, limit: int = 5) -> Optional[List[Dict[str, Any]]]:
        """Get cached product recommendations"""
        return await self.get(f"recommendations_{customer_id}_{limit}", "analytics")
    
    async def set_product_recommendations(self, customer_id: int, recommendations: List[Dict[str, Any]], limit: int = 5):
        """Cache product recommendations"""
        return await self.set(f"recommendations_{customer_id}_{limit}", recommendations, 1800, "analytics")  # 30 minutes
    
    async def get_ai_response(self, prompt_hash: str) -> Optional[str]:
        """Get cached AI response for similar prompts"""
        return await self.get(f"ai_response_{prompt_hash}", "ai")
    
    async def set_ai_response(self, prompt_hash: str, response: str):
        """Cache AI response to avoid repeated API calls"""
        return await self.set(f"ai_response_{prompt_hash}", response, 3600, "ai")  # 1 hour
    
    async def get_conversation_context(self, customer_id: int) -> Optional[Dict[str, Any]]:
        """Get cached conversation context"""
        return await self.get(f"conversation_{customer_id}", "sessions")
    
    async def set_conversation_context(self, customer_id: int, context: Dict[str, Any]):
        """Cache conversation context for quick access"""
        return await self.set(f"conversation_{customer_id}", context, 1800, "sessions")  # 30 minutes
# Global cache service instance
_cache_service: Optional[CacheService] = None

async def get_cache_service() -> CacheService:
    """Get or create cache service instance"""
    global _cache_service
    
    if _cache_service is None:
        settings = get_settings()
        _cache_service = CacheService(settings)
        await _cache_service.connect()
    
    return _cache_service

# Cache decorators for easy use

def cache_result(
    ttl: Optional[int] = None,
    namespace: str = "functions",
    key_builder: Optional[Callable] = None
):
    """
    Decorator to cache function results
    
    Args:
        ttl: Time to live in seconds
        namespace: Cache namespace
        key_builder: Custom function to build cache key
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            cache_service = await get_cache_service()
            
            # Build cache key
            if key_builder:
                cache_key = key_builder(*args, **kwargs)
            else:
                cache_key = f"{func.__name__}:{cache_service._hash_key((args, kwargs))}"
            
            # Try to get from cache
            cached_result = await cache_service.get(cache_key, namespace)
            if cached_result is not None:
                logger.debug(f"Cache hit for {func.__name__}")
                return cached_result
            
            # Execute function
            result = await func(*args, **kwargs)
            
            # Cache result
            await cache_service.set(cache_key, result, ttl, namespace)
            logger.debug(f"Cached result for {func.__name__}")
            
            return result
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            # For sync functions, we need to handle the async cache operations
            async def _async_sync_wrapper():
                cache_service = await get_cache_service()
                
                # Build cache key
                if key_builder:
                    cache_key = key_builder(*args, **kwargs)
                else:
                    cache_key = f"{func.__name__}:{cache_service._hash_key((args, kwargs))}"
                
                # Try to get from cache
                cached_result = await cache_service.get(cache_key, namespace)
                if cached_result is not None:
                    logger.debug(f"Cache hit for {func.__name__}")
                    return cached_result
                
                # Execute function
                result = func(*args, **kwargs)
                
                # Cache result
                await cache_service.set(cache_key, result, ttl, namespace)
                logger.debug(f"Cached result for {func.__name__}")
                
                return result
            
            # Run the async wrapper in the current event loop or create one
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # We're already in an event loop, return cached result or execute synchronously
                    return _async_sync_wrapper()  # Remove asyncio.run call
                else:
                    return loop.run_until_complete(_async_sync_wrapper())
            except RuntimeError:
                # No event loop, create one
                return asyncio.run(_async_sync_wrapper())
        
        # Return appropriate wrapper based on whether function is async
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator

def invalidate_cache(namespace: str = "functions", pattern: str = "*"):
    """
    Decorator to invalidate cache after function execution
    
    Args:
        namespace: Cache namespace to invalidate
        pattern: Pattern of keys to invalidate
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            result = await func(*args, **kwargs)
            
            # Invalidate cache
            cache_service = await get_cache_service()
            await cache_service.invalidate_pattern(pattern, namespace)
            logger.debug(f"Invalidated cache pattern {pattern} in namespace {namespace}")
            
            return result
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            
            # Invalidate cache
            async def _invalidate():
                cache_service = await get_cache_service()
                await cache_service.invalidate_pattern(pattern, namespace)
                logger.debug(f"Invalidated cache pattern {pattern} in namespace {namespace}")
            
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # We're already in an event loop, skip invalidation or do it synchronously
                    pass  # Skip for now to avoid event loop issues
                else:
                    loop.run_until_complete(_invalidate())
            except RuntimeError:
                asyncio.run(_invalidate())
            
            return result
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator

# Utility functions for manual cache management

async def cache_get(key: str, namespace: str = "manual") -> Optional[Any]:
    """Get value from cache manually"""
    cache_service = await get_cache_service()
    return await cache_service.get(key, namespace)

async def cache_set(key: str, value: Any, ttl: Optional[int] = None, namespace: str = "manual") -> bool:
    """Set value in cache manually"""
    cache_service = await get_cache_service()
    return await cache_service.set(key, value, ttl, namespace)

async def cache_delete(key: str, namespace: str = "manual") -> bool:
    """Delete value from cache manually"""
    cache_service = await get_cache_service()
    return await cache_service.delete(key, namespace)

async def cache_stats() -> Dict[str, Any]:
    """Get cache statistics"""
    cache_service = await get_cache_service()
    return await cache_service.get_stats()

# Analytics-specific cache decorators

def cache_analytics(expire_hours: int = 1):
    """
    Decorator to cache analytics results with specified expiration in hours
    
    Args:
        expire_hours: Hours to cache the analytics data
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            cache_service = await get_cache_service()
            
            # Build cache key specific to analytics
            cache_key = f"analytics:{func.__name__}:{cache_service._hash_key((args, kwargs))}"
            
            # Try to get from cache
            cached_result = await cache_service.get(cache_key, "analytics")
            if cached_result is not None:
                logger.debug(f"Analytics cache hit for {func.__name__}")
                return cached_result
            
            # Execute function
            result = await func(*args, **kwargs)
            
            # Cache result with specified TTL
            ttl = expire_hours * 3600  # Convert hours to seconds
            await cache_service.set(cache_key, result, ttl, "analytics")
            logger.debug(f"Cached analytics result for {func.__name__} (TTL: {expire_hours}h)")
            
            return result
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            async def _async_sync_wrapper():
                cache_service = await get_cache_service()
                
                # Build cache key specific to analytics
                cache_key = f"analytics:{func.__name__}:{cache_service._hash_key((args, kwargs))}"
                
                # Try to get from cache
                cached_result = await cache_service.get(cache_key, "analytics")
                if cached_result is not None:
                    logger.debug(f"Analytics cache hit for {func.__name__}")
                    return cached_result
                
                # Execute function
                result = func(*args, **kwargs)
                
                # Cache result with specified TTL
                ttl = expire_hours * 3600  # Convert hours to seconds
                await cache_service.set(cache_key, result, ttl, "analytics")
                logger.debug(f"Cached analytics result for {func.__name__} (TTL: {expire_hours}h)")
                
                return result
            
            # Run the async wrapper in the current event loop or create one
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # We're already in an event loop, return cached result or execute synchronously
                    return _async_sync_wrapper()  # Remove asyncio.run call
                else:
                    return loop.run_until_complete(_async_sync_wrapper())
            except RuntimeError:
                # No event loop, create one
                return asyncio.run(_async_sync_wrapper())
        
        # Return appropriate wrapper based on whether function is async
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator

def cache_database_query(ttl: Optional[int] = None):
    """
    Decorator to cache database query results
    
    Args:
        ttl: Time to live in seconds (defaults to cache service default)
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            cache_service = await get_cache_service()
            
            # Build cache key specific to database queries
            cache_key = f"db_query:{func.__name__}:{cache_service._hash_key((args, kwargs))}"
            
            # Try to get from cache
            cached_result = await cache_service.get(cache_key, "database")
            if cached_result is not None:
                logger.debug(f"Database query cache hit for {func.__name__}")
                return cached_result
            
            # Execute function
            result = await func(*args, **kwargs)
            
            # Cache result
            await cache_service.set(cache_key, result, ttl, "database")
            logger.debug(f"Cached database query result for {func.__name__}")
            
            return result
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            async def _async_sync_wrapper():
                cache_service = await get_cache_service()
                
                # Build cache key specific to database queries
                cache_key = f"db_query:{func.__name__}:{cache_service._hash_key((args, kwargs))}"
                
                # Try to get from cache
                cached_result = await cache_service.get(cache_key, "database")
                if cached_result is not None:
                    logger.debug(f"Database query cache hit for {func.__name__}")
                    return cached_result
                
                # Execute function
                result = func(*args, **kwargs)
                
                # Cache result
                await cache_service.set(cache_key, result, ttl, "database")
                logger.debug(f"Cached database query result for {func.__name__}")
                
                return result
            
            # Run the async wrapper in the current event loop or create one
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # We're already in an event loop, return cached result or execute synchronously
                    return _async_sync_wrapper()  # Remove asyncio.run call
                else:
                    return loop.run_until_complete(_async_sync_wrapper())
            except RuntimeError:
                # No event loop, create one
                return asyncio.run(_async_sync_wrapper())
        
        # Return appropriate wrapper based on whether function is async
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator