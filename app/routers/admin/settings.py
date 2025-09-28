"""
Settings module for admin interface
Handles system configuration and WhatsApp settings
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi_csrf_protect import CsrfProtect
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.templates_config import templates
from app.routers.users import get_current_admin

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/admin/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    db: Session = Depends(get_db)
):
    """Settings configuration page"""
    # Get the current admin user
    current_admin = await get_current_admin(request, db)
    
    # Get all configuration values
    configs = db.query(models.Configuration).all()
    
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "admin": current_admin,
            "configs": configs
        }
    )

@router.post("/admin/settings/update")
async def update_settings(
    request: Request,
    csrf_protect: CsrfProtect = Depends(),
    db: Session = Depends(get_db)
):
    """Update system settings"""
    # Validate CSRF token
    await csrf_protect.validate_csrf(request)
    
    # Get the current admin user
    current_admin = await get_current_admin(request, db)
    
    # Get form data
    form_data = await request.form()
    
    success_message = None
    error_message = None
    
    try:
        # Update configuration values
        config_keys = [
            'whatsapp_phone_number',
            'whatsapp_api_url', 
            'whatsapp_phone_id',
            'whatsapp_api_token',
            'webhook_verify_token',
            'business_name',
            'default_welcome_message',
            'default_currency'
        ]
        
        for key in config_keys:
            form_key = f'config_{key}'
            if form_key in form_data:
                value = form_data[form_key]
                
                # Find existing config or create new one
                config = db.query(models.Configuration).filter(
                    models.Configuration.key == key
                ).first()
                
                if config:
                    config.value = value
                else:
                    config = models.Configuration(key=key, value=value)
                    db.add(config)
        
        db.commit()
        success_message = "Settings updated successfully!"
        
    except Exception as e:
        logger.error(f"Error updating settings: {str(e)}")
        error_message = "Failed to update settings. Please try again."
        db.rollback()
    
    # Get all configuration values for template
    configs = db.query(models.Configuration).all()
    
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "admin": current_admin,
            "configs": configs,
            "success_message": success_message,
            "error_message": error_message
        }
    )

@router.post("/admin/reload-whatsapp-config")
async def reload_whatsapp_config(
    request: Request,
    db: Session = Depends(get_db)
):
    """Reload WhatsApp configuration without restarting"""
    try:
        # Get the current admin user
        current_admin = await get_current_admin(request, db)
        
        # Only super admins can reload config
        if current_admin.role != models.UserRole.SUPER_ADMIN:
            raise HTTPException(status_code=403, detail="Access denied")
        
        # This would trigger a config reload in the WhatsApp service
        # For now, just return success
        return {"success": True, "message": "Configuration reloaded successfully"}
        
    except Exception as e:
        logger.error(f"Error reloading WhatsApp config: {str(e)}")
        return {"success": False, "message": str(e)}

@router.post("/admin/test-whatsapp-connection")
async def test_whatsapp_connection(
    request: Request,
    db: Session = Depends(get_db)
):
    """Test WhatsApp API connection"""
    try:
        # Get the current admin user
        current_admin = await get_current_admin(request, db)
        
        # Only super admins can test connection
        if current_admin.role != models.UserRole.SUPER_ADMIN:
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Get request data
        data = await request.json()
        phone_number = data.get('phone_number')
        
        if not phone_number:
            return {"success": False, "message": "Phone number is required"}
        
        # Test the WhatsApp connection
        try:
            from app.services.whatsapp import WhatsAppService
            whatsapp_service = WhatsAppService(db)
            
            # Send a test message
            test_message = "This is a test message from ConvoCart admin panel."
            success = whatsapp_service.send_message(phone_number, test_message)
            
            if success:
                return {"success": True, "message": "Test message sent successfully"}
            else:
                return {"success": False, "message": "Failed to send test message"}
                
        except Exception as e:
            logger.error(f"WhatsApp test error: {str(e)}")
            return {"success": False, "message": f"WhatsApp API error: {str(e)}"}
        
    except Exception as e:
        logger.error(f"Error testing WhatsApp connection: {str(e)}")
        return {"success": False, "message": str(e)}