# app/routers/admin.py
import json
import logging
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.templating import Jinja2Templates
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from app.database import get_db
from app.config import SECRET_KEY, WHATSAPP_PHONE_ID
from app import models
from pathlib import Path
from urllib.parse import quote


router = APIRouter()
logger = logging.getLogger(__name__)

# Setup templates
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")

# OAuth2 password bearer
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="admin/login")

# JWT settings
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """
    Create a JWT access token
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_admin(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    """
    Get the current admin user from the JWT token
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    admin = db.query(models.Admin).filter(models.Admin.username == username).first()
    if admin is None:
        raise credentials_exception
    
    return admin

@router.get("/admin/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """
    Render the login page
    """
    return templates.TemplateResponse("login.html", {"request": request})

@router.post("/admin/login")
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(), 
    db: Session = Depends(get_db)
):
    """
    Login endpoint for admin users
    """
    admin = db.query(models.Admin).filter(models.Admin.username == form_data.username).first()
    
    if not admin or admin.password != form_data.password:  # In production, use proper password hashing
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Create access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": admin.username}, expires_delta=access_token_expires
    )
    
    # Return token as cookie and redirect to dashboard
    response = RedirectResponse(url="/admin/dashboard", status_code=303)
    response.set_cookie(
        key="access_token", 
        value=f"Bearer {access_token}", 
        httponly=True,
        max_age=3600,  # 1 hour expiry
        samesite="lax"  # This helps with security but allows redirects
    )
    return response


async def get_current_admin(request: Request, db: Session = Depends(get_db)):
    """
    Get the current admin user from the JWT token in cookies
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    # Get token from cookie
    cookie_authorization: str = request.cookies.get("access_token")
    if not cookie_authorization:
        raise credentials_exception
        
    # Remove 'Bearer ' prefix if present
    if cookie_authorization.startswith("Bearer "):
        token = cookie_authorization.replace("Bearer ", "")
    else:
        token = cookie_authorization
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    admin = db.query(models.Admin).filter(models.Admin.username == username).first()
    if admin is None:
        raise credentials_exception
    
    return admin


@router.get("/admin/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, current_admin: models.Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    """
    Admin dashboard page
    """
    # Get recent orders
    orders = db.query(models.Order).order_by(models.Order.created_at.desc()).limit(10).all()
    
    # Get order statistics
    total_orders = db.query(models.Order).count()
    pending_orders = db.query(models.Order).filter(models.Order.status == "pending").count()
    completed_orders = db.query(models.Order).filter(models.Order.status == "completed").count()
    
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "admin": current_admin,
            "orders": orders,
            "total_orders": total_orders,
            "pending_orders": pending_orders,
            "completed_orders": completed_orders
        }
    )

@router.get("/admin/orders", response_class=HTMLResponse)
async def view_orders(
    request: Request,
    status: Optional[str] = None,
    page: int = 1,
    current_admin: models.Admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    View and manage orders
    """
    # Number of orders per page
    page_size = 20
    
    # Filter orders by status if provided
    query = db.query(models.Order)
    if status:
        query = query.filter(models.Order.status == status)
    
    # Get total count for pagination
    total_orders = query.count()
    
    # Get paginated orders
    orders = query.order_by(models.Order.created_at.desc()) \
        .offset((page - 1) * page_size) \
        .limit(page_size) \
        .all()
    
    # Get customer information for each order
    customer_info = {}
    for order in orders:
        customer = db.query(models.Customer).filter(models.Customer.id == order.customer_id).first()
        if customer:
            customer_info[order.id] = customer
    
    # Calculate pagination info
    total_pages = (total_orders + page_size - 1) // page_size
    
    return templates.TemplateResponse(
        "orders.html",
        {
            "request": request,
            "admin": current_admin,
            "orders": orders,
            "customer_info": customer_info,
            "current_page": page,
            "total_pages": total_pages,
            "total_orders": total_orders,
            "status_filter": status
        }
    )

@router.post("/admin/orders/{order_id}/status")
async def update_order_status(
    order_id: int,
    status: str = Form(...),
    notify_customer: bool = Form(False),
    current_admin: models.Admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Update the status of an order and optionally notify the customer
    """
    from app.services.whatsapp import WhatsAppService
    
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Get previous status for change detection
    previous_status = order.status
    
    # Update the order status
    order.status = status
    db.commit()
    
    # Notify customer if requested
    if notify_customer:
        # Get customer information
        customer = db.query(models.Customer).filter(models.Customer.id == order.customer_id).first()
        if customer:
            # Initialize WhatsApp service
            whatsapp_service = WhatsAppService()
            
            # Create status update message
            status_messages = {
                "pending": "🕒 Your order #{} is pending processing. We'll update you soon!",
                "processing": "⚙️ Your order #{} is now being processed. We're working on it!",
                "completed": "✅ Good news! Your order #{} has been completed. Thank you for your business!",
                "cancelled": "❌ Your order #{} has been cancelled. Please contact us if you have any questions."
            }
            
            message = status_messages.get(status, "Your order #{} status has been updated to: {}").format(
                order_id, status
            )
            
            # Send the message
            whatsapp_service.send_text_message(customer.phone_number, message)
            
            # If order is completed, perhaps ask for feedback
            if status == "completed" and previous_status != "completed":
                buttons = [
                    {"id": "feedback_good", "title": "👍 Great!"},
                    {"id": "feedback_ok", "title": "👌 It was OK"},
                    {"id": "feedback_bad", "title": "👎 Had issues"}
                ]
                whatsapp_service.send_quick_reply_buttons(
                    customer.phone_number, 
                    "How was your experience with this order? We'd love your feedback!",
                    buttons
                )
    
    # Redirect back to the orders page
    return RedirectResponse(url="/admin/orders", status_code=303)



@router.get("/admin/groups", response_class=HTMLResponse)
async def list_groups(
    request: Request,
    category: Optional[str] = None,
    page: int = 1,
    current_admin: models.Admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    List and manage groups
    """
    # Number of groups per page
    page_size = 20
    
    # Get all categories for filter dropdown
    categories = db.query(models.Group.category).distinct().all()
    categories = [cat[0] for cat in categories if cat[0]]
    
    # Filter groups by category if provided
    query = db.query(models.Group)
    if category:
        query = query.filter(models.Group.category == category)
    
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
    whatsapp_phone = WHATSAPP_PHONE_ID
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
            "whatsapp_phone": whatsapp_phone
        }
    )

@router.get("/admin/groups/new", response_class=HTMLResponse)
async def new_group_form(
    request: Request,
    current_admin: models.Admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Form to create a new group
    """
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
    name: str = Form(...),
    identifier: str = Form(...),
    description: str = Form(""),
    category: str = Form(""),
    welcome_message: str = Form(""),
    products: str = Form("[]"),  # JSON string of products
    is_active: bool = Form(True),
    current_admin: models.Admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Create a new group
    """
    # Check if identifier already exists
    existing = db.query(models.Group).filter(models.Group.identifier == identifier).first()
    if existing:
        raise HTTPException(status_code=400, detail="Group identifier already exists")
    
    # Validate products JSON
    try:
        products_json = json.loads(products)
        if not isinstance(products_json, list):
            raise HTTPException(status_code=400, detail="Products must be a valid JSON array")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Products must be a valid JSON array")
    
    # Create new group
    group = models.Group(
        name=name,
        identifier=identifier,
        description=description,
        category=category,
        welcome_message=welcome_message,
        products=products,
        is_active=is_active
    )
    
    db.add(group)
    db.commit()
    
    return RedirectResponse(url="/admin/groups", status_code=303)

@router.get("/admin/groups/{group_id}/edit", response_class=HTMLResponse)
async def edit_group_form(
    group_id: int,
    request: Request,
    current_admin: models.Admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Form to edit an existing group
    """
    # Get the group
    group = db.query(models.Group).filter(models.Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    
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
    group_id: int,
    name: str = Form(...),
    identifier: str = Form(...),
    description: str = Form(""),
    category: str = Form(""),
    welcome_message: str = Form(""),
    products: str = Form("[]"),  # JSON string of products
    is_active: bool = Form(True),
    current_admin: models.Admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Update an existing group
    """
    # Get the group
    group = db.query(models.Group).filter(models.Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    
    # Check if identifier already exists (for another group)
    existing = db.query(models.Group).filter(
        models.Group.identifier == identifier,
        models.Group.id != group_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Group identifier already exists")
    
    # Validate products JSON
    try:
        products_json = json.loads(products)
        if not isinstance(products_json, list):
            raise HTTPException(status_code=400, detail="Products must be a valid JSON array")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Products must be a valid JSON array")
    
    # Update group
    group.name = name
    group.identifier = identifier
    group.description = description
    group.category = category
    group.welcome_message = welcome_message
    group.products = products
    group.is_active = is_active
    group.updated_at = datetime.utcnow()
    
    db.commit()
    
    return RedirectResponse(url="/admin/groups", status_code=303)

@router.post("/admin/groups/{group_id}/delete")
async def delete_group(
    group_id: int,
    current_admin: models.Admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Delete a group
    """
    # Get the group
    group = db.query(models.Group).filter(models.Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    
    # Delete the group
    db.delete(group)
    db.commit()
    
    return RedirectResponse(url="/admin/groups", status_code=303)



@router.get("/admin/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    current_admin: models.Admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    System-wide settings page
    """
    # Get all configurations
    configs = db.query(models.Configuration).all()
    
    # Organize by keys
    config_map = {}
    for config in configs:
        config_map[config.key] = config
    
    # Get the WhatsApp phone number from config or environment
    whatsapp_phone = config_map.get('whatsapp_phone_number', None)
    if not whatsapp_phone:
        # Use environment WHATSAPP_PHONE_ID if available, strip any '+' prefix
        default_phone = WHATSAPP_PHONE_ID.replace('+', '') if WHATSAPP_PHONE_ID else ''
        whatsapp_phone = models.Configuration(
            key='whatsapp_phone_number',
            value=default_phone,
            description='WhatsApp Business Phone Number (without + prefix)'
        )
        db.add(whatsapp_phone)
        db.commit()
    
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "admin": current_admin,
            "configs": configs,
            "whatsapp_phone": whatsapp_phone
        }
    )

@router.post("/admin/settings/update")
async def update_settings(
    request: Request,
    current_admin: models.Admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Update system settings
    """
    form_data = await request.form()
    
    # Get all form fields with 'config_' prefix
    for key, value in form_data.items():
        if key.startswith('config_'):
            config_key = key.replace('config_', '')
            models.Configuration.set_value(db, config_key, value)
    
    return RedirectResponse(url="/admin/settings", status_code=303)

@router.get("/admin/groups/link-generator", response_class=HTMLResponse)
async def link_generator(
    request: Request,
    group_id: Optional[int] = None,
    current_admin: models.Admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    WhatsApp link generator tool with optional pre-selected group
    """
    try:
        # Get all active groups
        groups = db.query(models.Group).filter(models.Group.is_active == True).order_by(models.Group.name).all()
        
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
        if not whatsapp_phone and WHATSAPP_PHONE_ID:
            whatsapp_phone = WHATSAPP_PHONE_ID
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