"""
Cart Recovery Admin Routes
Provides admin interface for cart recovery analytics and management
"""
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.templates_config import templates
from app.services.cart_recovery_analytics import get_cart_recovery_analytics_service
from app.services.cart_abandonment_service import get_cart_abandonment_service
from app.models import User, UserRole, CartSession, CartStatus
from app.routers.users import get_current_admin
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/cart-recovery", tags=["cart-recovery"])


@router.get("/analytics", response_class=HTMLResponse)
async def cart_recovery_analytics(
    request: Request, 
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """Cart recovery analytics dashboard"""
    try:
        analytics_service = get_cart_recovery_analytics_service(db)
        
        # Get user's group ID (you may need to adjust this based on your auth system)
        # For now, assuming super admin can see all groups
        if admin.role == UserRole.SUPER_ADMIN:
            # Get first group for demo - you may want to add group selection
            from app.models import Group
            group = db.query(Group).first()
            group_id = group.id if group else 1
        else:
            # For client admin, get their associated group
            group_id = admin.groups[0].id if admin.groups else 1
        
        # Generate comprehensive report
        report = analytics_service.generate_abandonment_report(group_id, days=30)
        
        return templates.TemplateResponse("admin/cart_recovery_analytics.html", {
            "request": request,
            "admin": admin,
            "report": report,
            "group_id": group_id
        })
        
    except Exception as e:
        logger.error(f"Error loading cart recovery analytics: {e}")
        raise HTTPException(status_code=500, detail="Failed to load analytics")


@router.get("/abandoned-carts", response_class=HTMLResponse)
async def abandoned_carts_list(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """List of currently abandoned carts"""
    try:
        # Get abandoned carts
        abandoned_carts = db.query(CartSession).filter(
            CartSession.status == CartStatus.ABANDONED
        ).order_by(CartSession.abandoned_at.desc()).limit(50).all()
        
        return templates.TemplateResponse("admin/abandoned_carts.html", {
            "request": request,
            "admin": admin,
            "abandoned_carts": abandoned_carts
        })
        
    except Exception as e:
        logger.error(f"Error loading abandoned carts: {e}")
        raise HTTPException(status_code=500, detail="Failed to load abandoned carts")


@router.post("/trigger-recovery/{cart_session_id}")
async def trigger_manual_recovery(
    cart_session_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """Manually trigger recovery campaign for a specific cart"""
    try:
        abandonment_service = get_cart_abandonment_service(db)
        
        # Get cart session
        cart_session = db.query(CartSession).filter(
            CartSession.id == cart_session_id
        ).first()
        
        if not cart_session:
            raise HTTPException(status_code=404, detail="Cart session not found")
        
        if not cart_session.is_eligible_for_recovery():
            raise HTTPException(status_code=400, detail="Cart not eligible for recovery")
        
        # Create recovery campaign
        campaign = abandonment_service.create_recovery_campaign(cart_session)
        
        if campaign:
            # Send recovery message
            from app.services.whatsapp import WhatsAppService
            whatsapp_service = WhatsAppService()
            success = abandonment_service.send_recovery_message(campaign, whatsapp_service)
            
            if success:
                return {"success": True, "message": "Recovery campaign triggered successfully"}
            else:
                return {"success": False, "message": "Failed to send recovery message"}
        else:
            return {"success": False, "message": "Failed to create recovery campaign"}
            
    except Exception as e:
        logger.error(f"Error triggering manual recovery: {e}")
        raise HTTPException(status_code=500, detail="Failed to trigger recovery")


@router.get("/configuration", response_class=HTMLResponse)
async def cart_recovery_configuration(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """Cart recovery configuration settings"""
    try:
        from app.models import Configuration
        
        # Get current configuration values
        configs = {
            'cart_abandonment_threshold_minutes': Configuration.get_value(db, 'cart_abandonment_threshold_minutes', '15'),
            'cart_recovery_max_attempts': Configuration.get_value(db, 'cart_recovery_max_attempts', '3'),
            'cart_recovery_interval_hours': Configuration.get_value(db, 'cart_recovery_interval_hours', '2'),
            'recovery_discount_enabled': Configuration.get_value(db, 'recovery_discount_enabled', 'true'),
        }
        
        return templates.TemplateResponse("admin/cart_recovery_config.html", {
            "request": request,
            "admin": admin,
            "configs": configs
        })
        
    except Exception as e:
        logger.error(f"Error loading cart recovery configuration: {e}")
        raise HTTPException(status_code=500, detail="Failed to load configuration")


@router.post("/configuration")
async def update_cart_recovery_configuration(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """Update cart recovery configuration settings"""
    try:
        if admin.role != UserRole.SUPER_ADMIN:
            raise HTTPException(status_code=403, detail="Only super admins can update configuration")
        
        form_data = await request.form()
        from app.models import Configuration
        
        # Update configuration values
        config_updates = {
            'cart_abandonment_threshold_minutes': form_data.get('abandonment_threshold', '15'),
            'cart_recovery_max_attempts': form_data.get('max_attempts', '3'),
            'cart_recovery_interval_hours': form_data.get('recovery_interval', '2'),
            'recovery_discount_enabled': 'true' if form_data.get('discount_enabled') else 'false',
        }
        
        for key, value in config_updates.items():
            Configuration.set_value(db, key, value)
        
        db.commit()
        
        # Return just the success message HTML
        success_html = '''
        <div class="bg-green-100 border border-green-400 text-green-700 px-4 py-3 rounded mb-6 animate-fade-in">
            <div class="flex items-center">
                <i class="fas fa-check-circle mr-2"></i>
                <span>Configuration updated successfully!</span>
            </div>
        </div>
        <script>
            // Auto-hide message after 5 seconds
            setTimeout(() => {
                const msg = document.querySelector('#success-message-area .bg-green-100');
                if (msg) {
                    msg.style.opacity = '0';
                    setTimeout(() => msg.remove(), 300);
                }
            }, 5000);
        </script>
        '''
        
        from fastapi.responses import HTMLResponse
        return HTMLResponse(content=success_html)
        
    except Exception as e:
        logger.error(f"Error updating cart recovery configuration: {e}")
        raise HTTPException(status_code=500, detail="Failed to update configuration")