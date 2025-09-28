"""
Groups module for admin interface
Handles group management, payment methods, and WhatsApp link generation
"""
import json
import logging
import re
from datetime import datetime
from typing import Optional
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi_csrf_protect.flexible import CsrfProtect
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.config import get_settings
from app.templates_config import templates
from app.routers.users import get_current_admin

settings = get_settings()
router = APIRouter()
logger = logging.getLogger(__name__)

# Helper functions for handling JSON with SQLite
def parse_json_from_db(json_str):
    """Parse a JSON string from the database into a Python object.
    Returns an empty dict/list if the input is None or invalid.
    """
    if not json_str:
        return {}
    
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        # Return empty dict/list for invalid JSON
        return {}

def validate_json_input(json_str, expected_type=list):
    """Validate that a JSON string is valid and of the expected type.
    Raises HTTPException if validation fails.
    """
    try:
        parsed = json.loads(json_str)
        if not isinstance(parsed, expected_type):
            raise HTTPException(
                status_code=400, 
                detail=f"JSON data must be a {expected_type.__name__}"
            )
        return True
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON format")

@router.get("/admin/groups", response_class=HTMLResponse)
async def list_groups(
    request: Request,
    category: Optional[str] = None,
    page: int = 1,
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """List and manage groups"""
    # Get the current admin user from the cookie
    current_admin = await get_current_admin(request, db)
    
    # Number of groups per page
    page_size = 20
    
    # Base query for groups
    query = db.query(models.Group)
    
    # Filter groups by user's associations if not super admin
    if current_admin.role != models.UserRole.SUPER_ADMIN:
        query = query.join(models.Group.users).filter(models.User.id == current_admin.id)
    
    # Get all categories for filter dropdown
    categories = db.query(models.Group.category).distinct().all()
    categories = [cat[0] for cat in categories if cat[0]]
    
    # Filter groups by category if provided
    if category:
        query = query.filter(models.Group.category == category)

    # Filter by search query
    if search:
        query = query.filter(
            models.Group.name.ilike(f"%{search}%") |
            models.Group.identifier.ilike(f"%{search}%")
        )
    
    # Get total count for pagination
    total_groups = query.count()
    
    # Get paginated groups
    groups = query.order_by(models.Group.name) \
        .offset((page - 1) * page_size) \
        .limit(page_size) \
        .all()
    
    # Calculate pagination info
    total_pages = (total_groups + page_size - 1) // page_size
    
    # Get the WhatsApp phone number without the "+" for the link
    whatsapp_phone = settings.whatsapp_phone_number
    if whatsapp_phone and whatsapp_phone.startswith("+"):
        whatsapp_phone = whatsapp_phone[1:]
    
    return templates.TemplateResponse(
        "groups.html",
        {
            "request": request,
            "admin": current_admin,
            "groups": groups,
            "categories": categories,
            "current_page": page,
            "total_pages": total_pages,
            "total_groups": total_groups,
            "category_filter": category,
            "whatsapp_phone": whatsapp_phone,
            "search_query": search
        }
    )

@router.get("/admin/groups/new", response_class=HTMLResponse)
async def new_group_form(
    request: Request,
    current_admin: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Form to create a new group"""
    # Get all categories for dropdown
    categories = db.query(models.Group.category).distinct().all()
    categories = [cat[0] for cat in categories if cat[0]]
    
    return templates.TemplateResponse(
        "group_form.html",
        {
            "request": request,
            "admin": current_admin,
            "categories": categories,
            "group": None,  # No existing group for a new form
        }
    )

@router.post("/admin/groups/new")
async def create_group(
    request: Request,
    name: str = Form(...),
    identifier: str = Form(...),
    description: str = Form(""),
    category: str = Form(""),
    welcome_message: str = Form(""),
    is_active: bool = Form(True),
    # Payment method fields
    mpesa_till_enabled: bool = Form(False),
    mpesa_till_number: str = Form(""),
    mpesa_till_business_name: str = Form(""),
    mpesa_till_instructions: str = Form(""),
    mpesa_paybill_enabled: bool = Form(False),
    mpesa_paybill_number: str = Form(""),
    mpesa_paybill_account_format: str = Form(""),
    airtel_money_enabled: bool = Form(False),
    airtel_money_number: str = Form(""),
    bank_transfer_enabled: bool = Form(False),
    bank_name: str = Form(""),
    bank_account_number: str = Form(""),
    bank_account_name: str = Form(""),
    cash_on_delivery_enabled: bool = Form(True),
    csrf_protect: CsrfProtect = Depends(),
    db: Session = Depends(get_db)
):
    """Create a new group"""
    # Validate CSRF token
    await csrf_protect.validate_csrf(request)
    
    # Get the current admin user
    current_admin = await get_current_admin(request, db)
    
    # Sanitize the identifier
    sanitized_identifier = identifier.lower().replace(" ", "-")
    sanitized_identifier = re.sub(r'[^a-z0-9_-]', '', sanitized_identifier)
    
    # Check if identifier already exists
    existing = db.query(models.Group).filter(models.Group.identifier == sanitized_identifier).first()
    if existing:
        raise HTTPException(status_code=400, detail="Group identifier already exists")
    
    # Build payment methods configuration
    payment_methods = {}
    
    if mpesa_till_enabled and mpesa_till_number:
        payment_methods['mpesa_till'] = {
            'enabled': True,
            'till_number': mpesa_till_number.strip(),
            'business_name': mpesa_till_business_name.strip() or name,
            'instructions': mpesa_till_instructions.strip() or f"Pay via M-Pesa:\n1. Go to M-Pesa menu\n2. Select Lipa na M-Pesa\n3. Select Buy Goods and Services\n4. Enter Till Number: {mpesa_till_number}\n5. Enter amount: {{amount}}\n6. Complete transaction\n7. Send M-Pesa confirmation message here"
        }
    
    if mpesa_paybill_enabled and mpesa_paybill_number:
        payment_methods['mpesa_paybill'] = {
            'enabled': True,
            'paybill_number': mpesa_paybill_number.strip(),
            'account_number_format': mpesa_paybill_account_format.strip() or 'ORDER-{order_number}',
            'business_name': mpesa_till_business_name.strip() or name
        }
    
    if airtel_money_enabled and airtel_money_number:
        payment_methods['airtel_money'] = {
            'enabled': True,
            'number': airtel_money_number.strip(),
            'instructions': f"Pay via Airtel Money to: {airtel_money_number}\nThen send confirmation message here"
        }
    
    if bank_transfer_enabled and bank_name and bank_account_number:
        payment_methods['bank_transfer'] = {
            'enabled': True,
            'bank_name': bank_name.strip(),
            'account_number': bank_account_number.strip(),
            'account_name': bank_account_name.strip() or name,
            'instructions': f"Bank Transfer Details:\nBank: {bank_name}\nAccount: {bank_account_number}\nName: {bank_account_name or name}\nSend confirmation after transfer"
        }
    
    payment_methods['cash_on_delivery'] = {
        'enabled': cash_on_delivery_enabled
    }
    
    group = models.Group(
        name=name,
        identifier=sanitized_identifier,
        description=description,
        category=category,
        welcome_message=welcome_message,
        is_active=is_active,
        payment_methods=payment_methods
    )
    
    db.add(group)
    db.commit()
    db.refresh(group)  # Refresh to get the new ID
    
    # Add the current admin to this group if they're not a super admin
    if current_admin.role != models.UserRole.SUPER_ADMIN:
        current_admin.groups.append(group)
        db.commit()
    
    return RedirectResponse(url="/admin/groups", status_code=303)

@router.get("/admin/groups/{group_id}/edit", response_class=HTMLResponse)
async def edit_group_form(
    group_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Form to edit an existing group"""
    # Get the current admin user
    current_admin = await get_current_admin(request, db)
    
    # Get the group
    group = db.query(models.Group).filter(models.Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    
    # Check permissions - only allow super admins or admins assigned to this group
    if current_admin.role != models.UserRole.SUPER_ADMIN:
        if group not in current_admin.groups:
            raise HTTPException(status_code=403, detail="You don't have permission to edit this group")
    
    # Get all categories for dropdown
    categories = db.query(models.Group.category).distinct().all()
    categories = [cat[0] for cat in categories if cat[0]]
    if group.category and group.category not in categories:
        categories.append(group.category)
    
    return templates.TemplateResponse(
        "group_form.html",
        {
            "request": request,
            "admin": current_admin,
            "group": group,
            "categories": categories,
        }
    )

@router.post("/admin/groups/{group_id}/edit")
async def update_group(
    request: Request,
    group_id: int,
    name: str = Form(...),
    identifier: str = Form(...),
    description: str = Form(""),
    category: str = Form(""),
    welcome_message: str = Form(""),
    is_active: bool = Form(True),
    # Payment method fields
    mpesa_till_enabled: bool = Form(False),
    mpesa_till_number: str = Form(""),
    mpesa_till_business_name: str = Form(""),
    mpesa_till_instructions: str = Form(""),
    mpesa_paybill_enabled: bool = Form(False),
    mpesa_paybill_number: str = Form(""),
    mpesa_paybill_account_format: str = Form(""),
    airtel_money_enabled: bool = Form(False),
    airtel_money_number: str = Form(""),
    bank_transfer_enabled: bool = Form(False),
    bank_name: str = Form(""),
    bank_account_number: str = Form(""),
    bank_account_name: str = Form(""),
    cash_on_delivery_enabled: bool = Form(True),
    csrf_protect: CsrfProtect = Depends(),
    db: Session = Depends(get_db)
):
    """Update an existing group"""
    # Validate CSRF token
    await csrf_protect.validate_csrf(request)
    
    # Get the current admin user
    current_admin = await get_current_admin(request, db)
    
    # Get the group
    group = db.query(models.Group).filter(models.Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    
    # Sanitize the identifier
    sanitized_identifier = identifier.lower().replace(" ", "-")
    sanitized_identifier = re.sub(r'[^a-z0-9_-]', '', sanitized_identifier)
    
    # Check if identifier already exists (for another group)
    existing = db.query(models.Group).filter(
        models.Group.identifier == sanitized_identifier,
        models.Group.id != group_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Group identifier already exists")
    
    # Build payment methods configuration
    payment_methods = {}
    
    if mpesa_till_enabled and mpesa_till_number:
        payment_methods['mpesa_till'] = {
            'enabled': True,
            'till_number': mpesa_till_number.strip(),
            'business_name': mpesa_till_business_name.strip() or name,
            'instructions': mpesa_till_instructions.strip() or f"Pay via M-Pesa:\n1. Go to M-Pesa menu\n2. Select Lipa na M-Pesa\n3. Select Buy Goods and Services\n4. Enter Till Number: {mpesa_till_number}\n5. Enter amount: {{amount}}\n6. Complete transaction\n7. Send M-Pesa confirmation message here"
        }
    
    if mpesa_paybill_enabled and mpesa_paybill_number:
        payment_methods['mpesa_paybill'] = {
            'enabled': True,
            'paybill_number': mpesa_paybill_number.strip(),
            'account_number_format': mpesa_paybill_account_format.strip() or 'ORDER-{order_number}',
            'business_name': mpesa_till_business_name.strip() or name
        }
    
    if airtel_money_enabled and airtel_money_number:
        payment_methods['airtel_money'] = {
            'enabled': True,
            'number': airtel_money_number.strip(),
            'instructions': f"Pay via Airtel Money to: {airtel_money_number}\nThen send confirmation message here"
        }
    
    if bank_transfer_enabled and bank_name and bank_account_number:
        payment_methods['bank_transfer'] = {
            'enabled': True,
            'bank_name': bank_name.strip(),
            'account_number': bank_account_number.strip(),
            'account_name': bank_account_name.strip() or name,
            'instructions': f"Bank Transfer Details:\nBank: {bank_name}\nAccount: {bank_account_number}\nName: {bank_account_name or name}\nSend confirmation after transfer"
        }
    
    payment_methods['cash_on_delivery'] = {
        'enabled': cash_on_delivery_enabled
    }
    
    # Update group - store JSON as string for SQLite compatibility
    group.name = name
    group.identifier = sanitized_identifier
    group.description = description
    group.category = category
    group.welcome_message = welcome_message
    group.is_active = is_active
    group.payment_methods = payment_methods
    group.updated_at = datetime.utcnow()
    
    db.commit()
    
    return RedirectResponse(url="/admin/groups", status_code=303)

@router.post("/admin/groups/{group_id}/delete")
async def delete_group(
    request: Request,
    group_id: int,
    csrf_protect: CsrfProtect = Depends(),
    db: Session = Depends(get_db)
):
    """Delete a group if it has no associated orders.
    If it has orders, it will be marked as inactive.
    """
    # Validate CSRF token
    await csrf_protect.validate_csrf(request)
    
    # Get the current admin user
    current_admin = await get_current_admin(request, db)

    # Get the group
    group = db.query(models.Group).filter(models.Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    # Check permissions - only allow super admins or admins assigned to this group
    if current_admin.role != models.UserRole.SUPER_ADMIN:
        if group not in current_admin.groups:
            raise HTTPException(status_code=403, detail="You don't have permission to modify this group")

    # Check for associated orders
    order_count = db.query(models.Order).filter(models.Order.group_id == group_id).count()

    if order_count > 0:
        # If there are orders, soft delete by making it inactive
        group.is_active = False
        group.name = f"{group.name} (Archived)"
        # Remove user associations to hide it from client admins
        group.users = []
        db.commit()
        logger.info(f"Group '{group.identifier}' archived due to existing orders.")
    else:
        # If no orders, proceed with deletion
        # First, delete related customers to avoid foreign key violations
        db.query(models.Customer).filter(models.Customer.group_id == group_id).delete(synchronize_session=False)
        db.delete(group)
        db.commit()
        logger.info(f"Group '{group.identifier}' and its customers deleted.")

    return RedirectResponse(url="/admin/groups", status_code=303)

@router.get("/admin/groups/link-generator", response_class=HTMLResponse)
async def link_generator(
    request: Request,
    group_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """WhatsApp link generator tool with optional pre-selected group"""
    try:
        # Get the current admin user
        current_admin = await get_current_admin(request, db)
        
        # Filter groups based on admin role
        if current_admin.role != models.UserRole.SUPER_ADMIN:
            groups = db.query(models.Group).filter(
                models.Group.is_active == True,
                models.Group.users.any(models.User.id == current_admin.id)
            ).order_by(models.Group.name).all()
        else:
            groups = db.query(models.Group).filter(
                models.Group.is_active == True
            ).order_by(models.Group.name).all()
        
        if not groups:
            # Handle case where no groups exist yet
            return templates.TemplateResponse(
                "link_generator.html",
                {
                    "request": request,
                    "admin": current_admin,
                    "groups": [],
                    "whatsapp_phone": "",
                    "error_message": "No active groups found. Please create a group first."
                }
            )
        
        # Get the WhatsApp phone number from database settings
        whatsapp_phone = models.Configuration.get_value(db, 'whatsapp_phone_number', '')
        
        # If no phone number in database, try to get from environment
        if not whatsapp_phone and settings.whatsapp_phone_number:
            whatsapp_phone = settings.whatsapp_phone_number
            if whatsapp_phone.startswith("+"):
                whatsapp_phone = whatsapp_phone[1:]
            
            # Save this to the database for future use
            models.Configuration.set_value(
                db, 
                'whatsapp_phone_number', 
                whatsapp_phone, 
                'WhatsApp Business Phone Number (without + prefix)'
            )
            logger.info("WhatsApp phone number saved to database from environment variable")
        
        # Get pre-selected group if group_id is provided
        selected_group = None
        if group_id:
            selected_group = db.query(models.Group).filter(
                models.Group.id == group_id, 
                models.Group.is_active == True
            ).first()
        
        # Handle pre-generating link if group is selected
        generated_link = None
        generated_message = None
        if selected_group:
            phone = whatsapp_phone
            message_text = f"order from group:{selected_group.identifier}"
            encoded_message = quote(message_text)
            generated_link = f"https://wa.me/{phone}?text={encoded_message}"
            generated_message = message_text
        
        return templates.TemplateResponse(
            "link_generator.html",
            {
                "request": request,
                "admin": current_admin,
                "groups": groups,
                "whatsapp_phone": whatsapp_phone,
                "selected_group": selected_group,
                "generated_link": generated_link,
                "generated_message": generated_message
            }
        )
    except Exception as e:
        logger.error(f"Error in link generator: {str(e)}")
        return templates.TemplateResponse(
            "link_generator.html",
            {
                "request": request,
                "admin": current_admin,
                "groups": [],
                "whatsapp_phone": "",
                "error_message": f"An error occurred: {str(e)}"
            }
        )