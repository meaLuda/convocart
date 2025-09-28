"""
Dashboard module for admin interface
Handles main dashboard, stats, and API usage monitoring
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.templates_config import templates
from app.services.api_monitor import get_api_monitor
from app.routers.users import get_current_admin

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/admin/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    """Admin dashboard page"""
    # Get the current admin user from the cookie
    current_admin = await get_current_admin(request, db)
    
    # Add debugging logs
    logger.info(f"Dashboard: User {current_admin.username}, role: {current_admin.role}")
    group_ids = [group.id for group in current_admin.groups]
    logger.info(f"User groups: {group_ids}")
    
    # Get all orders if super admin, or filter by groups if client admin
    query = db.query(models.Order)

    if current_admin.role != models.UserRole.SUPER_ADMIN:
        if not current_admin.groups:
            logger.info(f"User {current_admin.username} has no groups, showing no orders")
            query = query.filter(False)  # Empty result set
        else:
            group_ids = [group.id for group in current_admin.groups]
            logger.info(f"Filtering dashboard orders for groups: {group_ids}")
            query = query.filter(models.Order.group_id.in_(group_ids))
            logger.info(f"SQL Query: {str(query.statement.compile(dialect=db.bind.dialect))}")
        
    # Execute the query to get recent orders
    orders = query.order_by(models.Order.created_at.desc()).limit(10).all()
    
    # Get order statistics - use THE SAME filtering logic as for orders
    base_query = db.query(models.Order)
    if current_admin.role != models.UserRole.SUPER_ADMIN:
        if not current_admin.groups:
            # If admin has no groups, show zero counts
            base_query = base_query.filter(False)  # Empty result set
        else:
            group_ids = [group.id for group in current_admin.groups]
            base_query = base_query.filter(models.Order.group_id.in_(group_ids))
    
    total_orders = base_query.count()
    pending_orders = base_query.filter(models.Order.status == models.OrderStatus.PENDING).count()
    completed_orders = base_query.filter(models.Order.status == models.OrderStatus.COMPLETED).count()
    
    # Add pagination variables
    page_size = 10
    total_pages = (total_orders + page_size - 1) // page_size if total_orders > 0 else 1
    current_page = 1
    
    # Get currency configuration
    currency_config = db.query(models.Configuration).filter(
        models.Configuration.key == "default_currency"
    ).first()
    currency = currency_config.value if currency_config else "KSh"
    
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "admin": current_admin,
            "orders": orders,
            "total_orders": total_orders,
            "pending_orders": pending_orders,
            "completed_orders": completed_orders,
            "total_pages": total_pages,
            "current_page": current_page,
            "currency": currency
        }
    )

@router.get("/htmx/dashboard-stats", response_class=HTMLResponse)
async def htmx_dashboard_stats(
    request: Request,
    current_admin: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """HTMX endpoint for real-time dashboard stats"""
    try:
        # Determine which groups to show based on user role
        if current_admin.role == models.UserRole.SUPER_ADMIN:
            # Super admin sees all groups
            order_query = db.query(models.Order)
        else:
            # Client admin sees only their groups
            order_query = db.query(models.Order).join(models.Group).filter(
                models.Group.client_admin_id == current_admin.id
            )
        
        # Calculate stats
        total_orders = order_query.count()
        pending_orders = order_query.filter(models.Order.status == models.OrderStatus.PENDING).count()
        completed_orders = order_query.filter(models.Order.status == models.OrderStatus.COMPLETED).count()
        
        stats = {
            "total_orders": total_orders,
            "pending_orders": pending_orders,
            "completed_orders": completed_orders
        }
        
        return templates.TemplateResponse(
            "partials/dashboard_stats.html",
            {"request": request, **stats}
        )
        
    except Exception as e:
        logger.error(f"Error loading dashboard stats: {str(e)}")
        return '<div class="text-red-500">Error loading dashboard stats</div>'

@router.get("/admin/api-usage", response_class=HTMLResponse)
async def api_usage_page(
    request: Request,
    current_admin: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """API Usage monitoring dashboard"""
    try:
        # Only super admins can view API usage
        if current_admin.role != models.UserRole.SUPER_ADMIN:
            raise HTTPException(status_code=403, detail="Access denied")
        
        api_monitor = get_api_monitor(db)
        
        # Get usage stats for different periods
        daily_stats = await api_monitor.get_usage_stats(days=1)
        weekly_stats = await api_monitor.get_usage_stats(days=7)
        monthly_stats = await api_monitor.get_usage_stats(days=30)
        
        # Get current quota usage
        quota_usage = await api_monitor.get_current_quota_usage()
        
        # Get error analysis
        error_analysis = await api_monitor.get_error_analysis(days=7)
        
        return templates.TemplateResponse(
            "api_usage.html",
            {
                "request": request,
                "admin": current_admin,
                "daily_stats": daily_stats,
                "weekly_stats": weekly_stats,
                "monthly_stats": monthly_stats,
                "quota_usage": quota_usage,
                "error_analysis": error_analysis
            }
        )
        
    except Exception as e:
        logger.error(f"Error loading API usage page: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/htmx/api-usage-stats", response_class=HTMLResponse)
async def htmx_api_usage_stats(
    request: Request,
    days: int = Query(1, description="Number of days"),
    current_admin: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """HTMX endpoint for real-time API usage stats"""
    try:
        if current_admin.role != models.UserRole.SUPER_ADMIN:
            return '<div class="text-red-500">Access denied</div>'
        
        api_monitor = get_api_monitor(db)
        stats = await api_monitor.get_usage_stats(days=days)
        
        return templates.TemplateResponse(
            "partials/api_usage_stats.html",
            {"request": request, "stats": stats, "days": days}
        )
        
    except Exception as e:
        logger.error(f"Error loading API usage stats: {str(e)}")
        return '<div class="text-red-500">Error loading API usage stats</div>'