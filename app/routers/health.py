"""
Health Check Endpoints
Provides health and readiness checks for production monitoring
"""
import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db
from app.utils.config_validator import ConfigValidator
from app.utils.query_optimizer import DatabaseHealthChecker

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)

@router.get("/health")
async def health_check():
    """Basic health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "ConvoCart"
    }

@router.get("/health/detailed")
async def detailed_health_check(db: Session = Depends(get_db)):
    """Detailed health check with database and dependencies"""
    health_status = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "ConvoCart",
        "checks": {}
    }
    
    # Database check
    try:
        db.execute(text("SELECT 1")).fetchone()
        health_status["checks"]["database"] = {"status": "healthy"}
    except Exception as e:
        health_status["checks"]["database"] = {
            "status": "unhealthy",
            "error": str(e)
        }
        health_status["status"] = "unhealthy"
    
    # Cache check
    try:
        from app.services.cache_service import get_cache_service
        cache_service = await get_cache_service()
        await cache_service.set("health_check", "test", 10)
        cached_value = await cache_service.get("health_check")
        if cached_value == "test":
            health_status["checks"]["cache"] = {"status": "healthy"}
        else:
            health_status["checks"]["cache"] = {"status": "degraded", "message": "Cache not working properly"}
    except Exception as e:
        health_status["checks"]["cache"] = {
            "status": "unhealthy", 
            "error": str(e)
        }
    
    # Configuration check
    try:
        config_result = ConfigValidator.validate_production_config()
        if config_result["valid"]:
            health_status["checks"]["configuration"] = {"status": "healthy"}
        else:
            health_status["checks"]["configuration"] = {
                "status": "warning",
                "issues": config_result["critical_issues"],
                "warnings": config_result["warnings"]
            }
    except Exception as e:
        health_status["checks"]["configuration"] = {
            "status": "unhealthy",
            "error": str(e)
        }
    
    return health_status

@router.get("/readiness")
async def readiness_check(db: Session = Depends(get_db)):
    """Kubernetes readiness probe endpoint"""
    try:
        # Check database connectivity
        db.execute(text("SELECT 1")).fetchone()
        
        # Check if application can handle requests
        return {"status": "ready", "timestamp": datetime.utcnow().isoformat()}
    except Exception as e:
        logger.error(f"Readiness check failed: {str(e)}")
        raise HTTPException(status_code=503, detail="Service not ready")

@router.get("/liveness")
async def liveness_check():
    """Kubernetes liveness probe endpoint"""
    return {"status": "alive", "timestamp": datetime.utcnow().isoformat()}

@router.get("/metrics")
async def basic_metrics(db: Session = Depends(get_db)):
    """Basic application metrics"""
    try:
        # Database connection pool health
        db_health = DatabaseHealthChecker.check_connection_pool_status(db)
        
        # Cache statistics
        cache_stats = {}
        try:
            from app.services.cache_service import get_cache_service
            cache_service = await get_cache_service()
            cache_stats = await cache_service.get_stats()
        except Exception:
            cache_stats = {"status": "unavailable"}
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "database": db_health,
            "cache": cache_stats
        }
    except Exception as e:
        logger.error(f"Metrics collection failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Metrics collection failed")