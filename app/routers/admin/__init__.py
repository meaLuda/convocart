"""
Admin routers package
Contains all admin interface modules
"""
from fastapi import APIRouter
from . import auth, dashboard, orders, groups, settings, inventory

# Create main admin router
admin_router = APIRouter()

# Include all admin sub-routers
admin_router.include_router(auth.router, tags=["admin-auth"])
admin_router.include_router(dashboard.router, tags=["admin-dashboard"])
admin_router.include_router(orders.router, tags=["admin-orders"])
admin_router.include_router(groups.router, tags=["admin-groups"])
admin_router.include_router(inventory.router, tags=["admin-inventory"])
admin_router.include_router(inventory.legacy_router, tags=["admin-legacy"])
admin_router.include_router(settings.router, tags=["admin-settings"])

__all__ = ["admin_router", "auth", "dashboard", "orders", "groups", "inventory", "settings"]