"""
Database Query Optimization Utilities
Provides performance optimizations for common query patterns
"""
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy import func, text
from app.services.cache_service import cache_database_query
from app import models

logger = logging.getLogger(__name__)

class QueryOptimizer:
    """Database query optimization utilities"""
    
    @staticmethod
    @cache_database_query(ttl=300)  # Cache for 5 minutes
    def get_orders_with_relationships(
        db: Session, 
        group_ids: Optional[List[int]] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[models.Order]:
        """
        Optimized order query with eager loading
        Reduces N+1 queries by preloading relationships
        """
        query = db.query(models.Order).options(
            joinedload(models.Order.customer),
            joinedload(models.Order.group),
            selectinload(models.Order.customer).selectinload(models.Customer.groups)
        )
        
        if group_ids:
            query = query.filter(models.Order.group_id.in_(group_ids))
        
        return query.order_by(models.Order.created_at.desc()).offset(offset).limit(limit).all()
    
    @staticmethod
    @cache_database_query(ttl=600)  # Cache for 10 minutes
    def get_group_statistics_bulk(db: Session, group_ids: List[int]) -> Dict[int, Dict[str, int]]:
        """
        Get statistics for multiple groups in a single optimized query
        """
        # Single query to get all stats
        results = db.query(
            models.Order.group_id,
            func.count(models.Order.id).label('order_count'),
            func.count(func.distinct(models.Customer.id)).label('customer_count'),
            func.sum(models.Order.total_amount).label('total_revenue')
        ).outerjoin(
            models.Customer, models.Customer.id == models.Order.customer_id
        ).filter(
            models.Order.group_id.in_(group_ids)
        ).group_by(models.Order.group_id).all()
        
        # Convert to dictionary for easy lookup
        stats_dict = {}
        for result in results:
            stats_dict[result.group_id] = {
                'order_count': result.order_count or 0,
                'customer_count': result.customer_count or 0,
                'total_revenue': float(result.total_revenue or 0)
            }
        
        # Fill in missing groups with zero stats
        for group_id in group_ids:
            if group_id not in stats_dict:
                stats_dict[group_id] = {
                    'order_count': 0,
                    'customer_count': 0,
                    'total_revenue': 0.0
                }
        
        return stats_dict
    
    @staticmethod
    @cache_database_query(ttl=300)
    def get_recent_orders_for_customer(
        db: Session, 
        customer_id: int, 
        limit: int = 5
    ) -> List[models.Order]:
        """
        Get recent orders for a customer with minimal queries
        """
        return db.query(models.Order).options(
            joinedload(models.Order.group)
        ).filter(
            models.Order.customer_id == customer_id
        ).order_by(
            models.Order.created_at.desc()
        ).limit(limit).all()
    
    @staticmethod
    def optimize_conversation_queries(db: Session):
        """
        Add database indexes for conversation-related queries
        """
        # These would typically be in migration files, but included here for reference
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_orders_customer_created ON orders(customer_id, created_at DESC);",
            "CREATE INDEX IF NOT EXISTS idx_orders_group_status ON orders(group_id, status);",
            "CREATE INDEX IF NOT EXISTS idx_orders_created_status ON orders(created_at DESC, status);",
            "CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone_number);",
            "CREATE INDEX IF NOT EXISTS idx_conversation_sessions_customer ON conversation_sessions(customer_id);",
            "CREATE INDEX IF NOT EXISTS idx_conversation_sessions_updated ON conversation_sessions(updated_at DESC);"
        ]
        
        try:
            for index_sql in indexes:
                db.execute(text(index_sql))
            db.commit()
            logger.info("Database indexes optimized")
        except Exception as e:
            logger.error(f"Error creating indexes: {str(e)}")
            db.rollback()
    
    @staticmethod
    @cache_database_query(ttl=1800)  # Cache for 30 minutes
    def get_configuration_cache(db: Session) -> Dict[str, str]:
        """
        Cache configuration values to avoid repeated database queries
        """
        configs = db.query(models.Configuration).all()
        return {config.key: config.value for config in configs}
    
    @staticmethod
    def get_customer_orders_paginated(
        db: Session,
        customer_id: int,
        page: int = 1,
        page_size: int = 10
    ) -> Dict[str, Any]:
        """
        Paginated customer orders with count optimization
        """
        offset = (page - 1) * page_size
        
        # Get total count efficiently
        total_count = db.query(func.count(models.Order.id)).filter(
            models.Order.customer_id == customer_id
        ).scalar()
        
        # Get paginated results with relationships
        orders = db.query(models.Order).options(
            joinedload(models.Order.group)
        ).filter(
            models.Order.customer_id == customer_id
        ).order_by(
            models.Order.created_at.desc()
        ).offset(offset).limit(page_size).all()
        
        total_pages = (total_count + page_size - 1) // page_size
        
        return {
            'orders': orders,
            'total_count': total_count,
            'total_pages': total_pages,
            'current_page': page,
            'has_next': page < total_pages,
            'has_prev': page > 1
        }

class DatabaseHealthChecker:
    """Monitor database performance and health"""
    
    @staticmethod
    def check_slow_queries(db: Session, threshold_ms: int = 1000) -> List[Dict[str, Any]]:
        """
        Check for slow queries (PostgreSQL specific)
        """
        try:
            # Enable query statistics if not already enabled
            db.execute(text("SELECT pg_stat_statements_reset();"))
            
            # Get slow queries
            slow_queries = db.execute(text(f"""
                SELECT 
                    query,
                    calls,
                    total_time,
                    mean_time,
                    rows
                FROM pg_stat_statements 
                WHERE mean_time > {threshold_ms}
                ORDER BY mean_time DESC 
                LIMIT 10;
            """)).fetchall()
            
            return [dict(row) for row in slow_queries]
        except Exception as e:
            logger.warning(f"Could not check slow queries: {str(e)}")
            return []
    
    @staticmethod
    def check_connection_pool_status(db: Session) -> Dict[str, Any]:
        """
        Check database connection pool health
        """
        try:
            # Basic connection test
            db.execute(text("SELECT 1")).fetchone()
            
            # Get connection stats (PostgreSQL specific)
            stats = db.execute(text("""
                SELECT 
                    count(*) as total_connections,
                    count(*) FILTER (WHERE state = 'active') as active_connections,
                    count(*) FILTER (WHERE state = 'idle') as idle_connections
                FROM pg_stat_activity 
                WHERE datname = current_database();
            """)).fetchone()
            
            return {
                'status': 'healthy',
                'total_connections': stats.total_connections,
                'active_connections': stats.active_connections, 
                'idle_connections': stats.idle_connections
            }
        except Exception as e:
            logger.error(f"Database health check failed: {str(e)}")
            return {
                'status': 'unhealthy',
                'error': str(e)
            }