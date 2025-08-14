import json
import logging
from datetime import datetime, timedelta
import re
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.templating import Jinja2Templates
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from app.database import get_db
from app import models
from pathlib import Path
from urllib.parse import quote
from passlib.context import CryptContext  # Added for password hashing
from app.config import get_settings

settings = get_settings()


router = APIRouter()
logger = logging.getLogger(__name__)

# Setup templates
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")

# OAuth2 password bearer
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="admin/login")

# JWT settings
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
WHATSAPP_PHONE_NUMBER = settings.whatsapp_phone_number
WHATSAPP_API_URL = settings.whatsapp_api_url
WHATSAPP_PHONE_ID = settings.whatsapp_phone_id
WHATSAPP_API_TOKEN = settings.whatsapp_api_token
WHATSAPP_VERIFY_TOKEN = settings.webhook_verify_token
WEBHOOK_VERIFY_TOKEN = settings.webhook_verify_token

# Password context for hashing and verification
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password, hashed_password):
    """
    Verify a password against a hash
    """
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    """
    Hash a password for storing
    """
    return pwd_context.hash(password)


# Replace the old get_current_admin with this
async def get_current_admin(
    request: Request,
    db: Session = Depends(get_db)
):
    # Get token from cookie
    token = request.cookies.get("access_token")
    if not token:
        return RedirectResponse(url="/admin/login", status_code=303)
    
    # Remove "Bearer " prefix if present
    if token.startswith("Bearer "):
        token = token[7:]
    
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        username: str = payload.get("sub")
        if username is None:
            return RedirectResponse(url="/admin/login", status_code=303)
    except JWTError:
        return RedirectResponse(url="/admin/login", status_code=303)
    
    user = db.query(models.User).filter(models.User.username == username).first()
    if user is None or user.role not in [models.UserRole.CLIENT_ADMIN, models.UserRole.SUPER_ADMIN]:
        return RedirectResponse(url="/admin/login", status_code=303)
    
    return user


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
        encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=ALGORITHM)
        return encoded_jwt
    
    user = db.query(models.User).filter(models.User.username == form_data.username).first()
    
    # Check if user exists, has admin role, and password is correct
    if not user or user.role not in [models.UserRole.CLIENT_ADMIN, models.UserRole.SUPER_ADMIN] or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Update last login timestamp
    user.last_login = datetime.utcnow()
    db.commit()
    
    # Create access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
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

@router.get("/admin/logout")
async def logout():
    """
    Logout and clear the session cookie
    """
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie(key="access_token")
    return response


@router.get("/admin/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    """
    Admin dashboard page
    """
    # Get the current admin user from the cookie
    current_admin = await get_current_admin(request, db)
    if isinstance(current_admin, RedirectResponse):
        return current_admin
    
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
            "current_page": current_page
        }
    )

@router.get("/admin/orders", response_class=HTMLResponse)
async def view_orders(
    request: Request,
    status: Optional[str] = None,
    page: int = 1,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    View and manage orders
    """
    # Get the current admin user from the cookie
    current_admin = await get_current_admin(request, db)
    if isinstance(current_admin, RedirectResponse):
        return current_admin
    # Add debugging logs
    logger.info(f"Orders view: User {current_admin.username}, role: {current_admin.role}")
    group_ids = [group.id for group in current_admin.groups]
    logger.info(f"User groups: {group_ids}")
    
    # Base query for orders - initialize FIRST
    query = db.query(models.Order)
    
    # Filter orders by user's groups if not super admin
    if current_admin.role != models.UserRole.SUPER_ADMIN:
        if not current_admin.groups:
            logger.info(f"User {current_admin.username} has no groups, showing no orders")
            query = query.filter(False)
        else:
            group_ids = [group.id for group in current_admin.groups]
            logger.info(f"Filtering orders for groups: {group_ids}")
            # Apply the filter BEFORE any execution
            query = query.filter(models.Order.group_id.in_(group_ids))
            logger.info(f"SQL Query: {str(query.statement.compile(dialect=db.bind.dialect))}")
    
    # Apply additional filters (status filter)
    if status:
        try:
            order_status = models.OrderStatus(status)
            query = query.filter(models.Order.status == order_status)
        except ValueError:
            # Invalid status, ignore filter
            pass

    # Apply date range filter
    if start_date and end_date:
        try:
            start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
            end_date_obj = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(models.Order.created_at >= start_date_obj, models.Order.created_at < end_date_obj)
        except ValueError:
            # Invalid date format, ignore filter
            pass
    
    # Get total count for pagination
    total_orders = query.count()
    logger.info(f"Total filtered orders: {total_orders}")
    
    page_size = 20  # Number of orders per page
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
            "status_filter": status,
            "order_statuses": [status.value for status in models.OrderStatus]
        }
    )



def check_admin_has_access_to_group(admin, group_id, db):
    """Check if an admin has access to a specific group"""
    if admin.role == models.UserRole.SUPER_ADMIN:
        return True
    
    # Check if admin is a member of this group
    return any(group.id == group_id for group in admin.groups)


@router.post("/admin/orders/{order_id}/status")
async def update_order_status(
    order_id: int,
    status: str = Form(...),
    payment_status: Optional[str] = Form(None),
    payment_ref: Optional[str] = Form(None),
    total_amount: Optional[float] = Form(None),
    notify_customer: bool = Form(False),
    request: Request = None,
    db: Session = Depends(get_db)
):
    # Get the current admin user
    current_admin = await get_current_admin(request, db)
    if isinstance(current_admin, RedirectResponse):
        return current_admin
    
    # Get the order
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Check if admin has access to this order's group
    if not check_admin_has_access_to_group(current_admin, order.group_id, db):
        raise HTTPException(status_code=403, detail="You don't have permission to update this order")

    # Get previous status for change detection
    previous_status = order.status
    previous_payment_status = order.payment_status
    
    try:
        # Update the order status using enum
        order.status = models.OrderStatus(status)
        
        # Update payment status if provided
        if payment_status:
            order.payment_status = models.PaymentStatus(payment_status)
        
        # Update payment reference if provided
        if payment_ref:
            if len(payment_ref) > 50:
                raise HTTPException(status_code=400, detail="Payment reference too long (max 50 characters)")
            order.payment_ref = payment_ref
        
        # Update total amount if provided
        if total_amount is not None:
            try:
                order.total_amount = float(total_amount)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid amount value")
        
        # Add a timestamp for the update
        order.updated_at = datetime.utcnow()
        db.commit()
        
        logger.info(f"Order {order.order_number} updated by {current_admin.username}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid status value: {str(e)}")
    
    # Notify customer if requested
    if notify_customer:
        # Check if we can send a notification (prevent duplicates)
        if not hasattr(order, 'can_send_notification') or order.can_send_notification():
            try:
                # Get customer information
                customer = db.query(models.Customer).filter(models.Customer.id == order.customer_id).first()
                if customer:
                    # Import the WhatsApp service directly and initialize with DB session
                    from app.services.whatsapp import WhatsAppService
                    whatsapp_service = WhatsAppService(db)
                    
                    # Get group name for personalized messages
                    group_name = order.group.name if order.group else "Our store"
                    
                    # Determine if we should use order update or payment update notification
                    if previous_payment_status != order.payment_status and order.payment_method:
                        # Payment status has changed, so send a payment update notification
                        payment_data = {
                            "order_number": order.order_number,
                            "payment_status": order.payment_status.value,
                            "payment_method": order.payment_method.value.replace('_', ' ').title(),
                            "payment_ref": order.payment_ref or "",
                            "amount": order.total_amount
                        }
                        
                        # Send payment status update notification
                        whatsapp_service.send_payment_status_update(
                            customer.phone_number,
                            payment_data
                        )
                    else:
                        # Send a comprehensive order status update
                        order_data = {
                            "order_number": order.order_number,
                            "status": order.status.value,
                            "group_name": group_name,
                            "total_amount": order.total_amount,
                            "created_at": order.created_at.strftime('%Y-%m-%d %H:%M'),
                            "order_details": order.order_details
                        }
                        
                        # Add payment information if available
                        if order.payment_method:
                            order_data["payment_method"] = order.payment_method.value.replace('_', ' ').title()
                            
                            if order.payment_status:
                                order_data["payment_status"] = order.payment_status.value.title()
                            
                            if order.payment_ref:
                                order_data["payment_ref"] = order.payment_ref
            
                        # Send order status update notification
                        whatsapp_service.send_order_status_update(
                            customer.phone_number,
                            order_data
                        )
                    
                    # Record that we sent a notification
                    if hasattr(order, 'record_notification'):
                        order.record_notification()
                        db.commit()
                    else:
                        # Fallback for existing orders without the notification tracking fields
                        # Store the last notification time in session to prevent duplicates
                        session_key = f"last_notification_{order.id}"
                        request.session[session_key] = datetime.utcnow().isoformat()
                    
                    # If order is completed, ask for feedback
                    if order.status == models.OrderStatus.COMPLETED and previous_status != models.OrderStatus.COMPLETED:
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
            except Exception as e:
                logger.error(f"Error sending notification: {str(e)}")
                # Continue with redirect even if notification fails
        else:
            logger.info(f"Skipping duplicate notification for order {order.order_number}")
    
    # Redirect back to the orders page
    return RedirectResponse(url="/admin/orders", status_code=303)



@router.get("/admin/groups", response_class=HTMLResponse)
async def list_groups(
    request: Request,
    category: Optional[str] = None,
    page: int = 1,
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    List and manage groups
    """
    # Get the current admin user from the cookie
    current_admin = await get_current_admin(request, db)
    if isinstance(current_admin, RedirectResponse):
        return current_admin
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

@router.post("/admin/groups/new")
async def create_group(
    name: str = Form(...),
    identifier: str = Form(...),
    description: str = Form(""),
    category: str = Form(""),
    welcome_message: str = Form(""),
    is_active: bool = Form(True),
    request: Request = None,
    db: Session = Depends(get_db)
):
    """
    Create a new group
    """
    # Get the current admin user
    current_admin = await get_current_admin(request, db)
    if isinstance(current_admin, RedirectResponse):
        return current_admin
    
    # Sanitize the identifier
    sanitized_identifier = identifier.lower().replace(" ", "-")
    sanitized_identifier = re.sub(r'[^a-z0-9_-]', '', sanitized_identifier)
    
    # Check if identifier already exists
    existing = db.query(models.Group).filter(models.Group.identifier == sanitized_identifier).first()
    if existing:
        raise HTTPException(status_code=400, detail="Group identifier already exists")
    
    group = models.Group(
        name=name,
        identifier=sanitized_identifier,
        description=description,
        category=category,
        welcome_message=welcome_message,
        is_active=is_active
    )
    
    db.add(group)
    db.commit()
    db.refresh(group)  # Refresh to get the new ID
    
    # Add the current admin to this group if they're not a super admin
    if current_admin.role != models.UserRole.SUPER_ADMIN:
        current_admin.groups.append(group)
        db.commit()
    
    return RedirectResponse(url="/admin/groups", status_code=303)



@router.post("/admin/groups/{group_id}/edit")
async def update_group(
    group_id: int,
    name: str = Form(...),
    identifier: str = Form(...),
    description: str = Form(""),
    category: str = Form(""),
    welcome_message: str = Form(""),
    is_active: bool = Form(True),
    current_admin: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Update an existing group
    """
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
    
    
    # Update group - store JSON as string for SQLite compatibility
    group.name = name
    group.identifier = sanitized_identifier,
    group.description = description
    group.category = category
    group.welcome_message = welcome_message
    group.is_active = is_active
    group.updated_at = datetime.utcnow()
    
    db.commit()
    
    return RedirectResponse(url="/admin/groups", status_code=303)


# Template filter to properly parse JSON from db for display
@router.get("/admin/groups/{group_id}/edit", response_class=HTMLResponse)
async def edit_group_form(
    group_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Form to edit an existing group
    """
    # Get the current admin user
    current_admin = await get_current_admin(request, db)
    if isinstance(current_admin, RedirectResponse):
        return current_admin
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

@router.post("/admin/groups/{group_id}/delete")
async def delete_group(
    group_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Delete a group if it has no associated orders.
    If it has orders, it will be marked as inactive.
    """
    # Get the current admin user
    current_admin = await get_current_admin(request, db)
    if isinstance(current_admin, RedirectResponse):
        return current_admin

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

@router.get("/admin/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    current_admin: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    System-wide settings page
    """
    try:
        # Get all configurations
        configs = db.query(models.Configuration).all()
        
        # Check for success or error messages from the query parameters
        success_message = request.query_params.get('success')
        error_message = request.query_params.get('error')
        
        # WhatsApp config keys that should be in the database
        whatsapp_config_keys = [
            'whatsapp_phone_number',
            'whatsapp_api_url',
            'whatsapp_phone_id',
            'whatsapp_api_token',
            'webhook_verify_token'
        ]
        
        # General config keys
        general_config_keys = [
            'business_name',
            'default_welcome_message'
        ]
        
        # Ensure all expected config keys exist in the database
        for key in whatsapp_config_keys + general_config_keys:
            config = db.query(models.Configuration).filter(models.Configuration.key == key).first()
            if not config:
                # Get default value from environment variables for WhatsApp settings
                default_value = ""
                description = ""
                
                if key == 'whatsapp_phone_number':
                    default_value = WHATSAPP_PHONE_NUMBER.replace('+', '') if WHATSAPP_PHONE_NUMBER else ''
                    description = 'WhatsApp Business Phone Number (without + prefix)'
                elif key == 'whatsapp_api_url':
                    default_value = WHATSAPP_API_URL or ''
                    description = 'WhatsApp API URL'
                elif key == 'whatsapp_phone_id':
                    default_value = WHATSAPP_PHONE_ID or ''
                    description = 'WhatsApp Phone ID'
                elif key == 'whatsapp_api_token':
                    default_value = WHATSAPP_API_TOKEN or ''
                    description = 'WhatsApp API Token'
                elif key == 'webhook_verify_token':
                    default_value = WEBHOOK_VERIFY_TOKEN or ''
                    description = 'Webhook Verification Token'
                elif key == 'business_name':
                    description = 'Business Name'
                elif key == 'default_welcome_message':
                    description = 'Default welcome message for new customers'
                
                # Create the configuration entry
                new_config = models.Configuration(
                    key=key,
                    value=default_value,
                    description=description
                )
                db.add(new_config)
                db.commit()
                
                # Add to the configs list
                configs.append(new_config)
        
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
    except Exception as e:
        logger.error(f"Error loading settings page: {str(e)}")
        return templates.TemplateResponse(
            "settings.html",
            {
                "request": request,
                "admin": current_admin,
                "configs": [],
                "success_message": None,
                "error_message": f"Error loading settings: {str(e)}"
            }
        )

@router.post("/admin/settings/update")
async def update_settings(
    request: Request,
    current_admin: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Update system settings
    """
    try:
        form_data = await request.form()
        
        # Get all form fields with 'config_' prefix
        updated_count = 0
        for key, value in form_data.items():
            if key.startswith('config_'):
                config_key = key.replace('config_', '')
                if len(config_key) > 255:
                    raise HTTPException(status_code=400, detail=f"Configuration key '{config_key}' too long (max 255 characters)")
                if len(value) > 10000: # Assuming a reasonable max length for text config values
                    raise HTTPException(status_code=400, detail=f"Configuration value for '{config_key}' too long (max 10000 characters)")
                models.Configuration.set_value(db, config_key, value)
                updated_count += 1
        
        # Redirect with success message
        return RedirectResponse(
            url=f"/admin/settings?success=Successfully updated {updated_count} settings", 
            status_code=303
        )
    except Exception as e:
        logger.error(f"Error updating settings: {str(e)}")
        return RedirectResponse(
            url=f"/admin/settings?error={str(e)}", 
            status_code=303
        )

@router.post("/admin/reload-whatsapp-config")
async def reload_whatsapp_config(
    request: Request,
    current_admin: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Reload the WhatsApp service with the latest database configuration
    """
    # Only super admins can reload the configuration
    if current_admin.role != models.UserRole.SUPER_ADMIN:
        return JSONResponse(status_code=403, content={
            "success": False,
            "message": "Only super admins can reload WhatsApp configuration"
        })
    
    try:
        # Create a new WhatsApp service instance with the latest config
        from app.services.whatsapp import WhatsAppService
        
        # Update the webhook router's service instance
        import app.routers.webhook as webhook_router
        webhook_router.whatsapp_service = WhatsAppService(db)
        
        logger.info(f"WhatsApp configuration reloaded by admin: {current_admin.username}")
        
        return JSONResponse(content={
            "success": True,
            "message": "WhatsApp configuration reloaded successfully"
        })
    except Exception as e:
        logger.error(f"Error reloading WhatsApp configuration: {str(e)}")
        return JSONResponse(status_code=500, content={
            "success": False,
            "message": f"Error reloading configuration: {str(e)}"
        })


@router.post("/admin/test-whatsapp-connection")
async def test_whatsapp_connection(
    request: Request,
    current_admin: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Test WhatsApp connection by sending a test message
    """
    # Only super admins can test the connection
    if current_admin.role != models.UserRole.SUPER_ADMIN:
        return JSONResponse(status_code=403, content={
            "success": False,
            "message": "Only super admins can test WhatsApp connection"
        })
    
    try:
        # Get request data
        data = await request.json()
        phone_number = data.get("phone_number")
        
        if not phone_number:
            return JSONResponse(status_code=400, content={
                "success": False,
                "message": "Phone number is required"
            })
        
        # Create a WhatsApp service instance with database configuration
        from app.services.whatsapp import WhatsAppService
        whatsapp_service = WhatsAppService(db)
        
        # Send a test message
        test_message = "🧪 This is a test message from your WhatsApp Order Bot. If you received this, your API configuration is working correctly! Time: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        result = whatsapp_service.send_text_message(phone_number, test_message)
        
        # Check for errors in the result
        if "error" in result:
            return JSONResponse(status_code=400, content={
                "success": False,
                "message": f"Error sending test message: {result.get('error')}"
            })
        
        logger.info(f"Successfully sent test message to {phone_number}")
        
        return JSONResponse(content={
            "success": True,
            "message": "Test message sent successfully"
        })
    except Exception as e:
        logger.error(f"Error testing WhatsApp connection: {str(e)}")
        return JSONResponse(status_code=500, content={
            "success": False,
            "message": f"Error testing connection: {str(e)}"
        })
    

@router.get("/admin/groups/link-generator", response_class=HTMLResponse)
async def link_generator(
    request: Request,
    group_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """
    WhatsApp link generator tool with optional pre-selected group
    """
    try:
        # Get the current admin user
        current_admin = await get_current_admin(request, db)
        if isinstance(current_admin, RedirectResponse):
            return current_admin
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

# User Management Routes - SUPER_ADMIN only

def check_super_admin(user: models.User):
    """Check if user is a super admin"""
    if user.role != models.UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only super admins can manage users"
        )
    return True

@router.get("/admin/users", response_class=HTMLResponse)
async def list_users(
    request: Request,
    page: int = 1,
    current_admin: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    List all users - SUPER_ADMIN only
    """
    # Check if current user is a super admin
    check_super_admin(current_admin)
    
    # Number of users per page
    page_size = 20
    
    # Get total count for pagination
    total_users = db.query(models.User).count()
    
    # Get paginated users
    users = db.query(models.User) \
        .order_by(models.User.created_at.desc()) \
        .offset((page - 1) * page_size) \
        .limit(page_size) \
        .all()
    
    # Calculate pagination info
    total_pages = (total_users + page_size - 1) // page_size
    
    return templates.TemplateResponse(
        "users.html",
        {
            "request": request,
            "admin": current_admin,
            "users": users,
            "current_page": page,
            "total_pages": total_pages,
            "total_users": total_users,
            "roles": [role.value for role in models.UserRole]
        }
    )

@router.get("/admin/users/new", response_class=HTMLResponse)
async def new_user_form(
    request: Request,
    current_admin: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Form to create a new user - SUPER_ADMIN only
    """
    # Check if current user is a super admin
    check_super_admin(current_admin)
    
    # Get all available groups
    groups = db.query(models.Group).order_by(models.Group.name).all()
    
    return templates.TemplateResponse(
        "user_form.html",
        {
            "request": request,
            "admin": current_admin,
            "user": None,  # No existing user for a new form
            "groups": groups,
            "roles": [role.value for role in models.UserRole]
        }
    )

@router.post("/admin/users/new")
async def create_user(
    request: Request,
    current_admin: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Create a new user - SUPER_ADMIN only
    """
    # Check if current user is a super admin
    check_super_admin(current_admin)
    
    # Get form data
    form_data = await request.form()
    username = form_data.get("username")
    password = form_data.get("password")
    email = form_data.get("email", None)
    phone_number = form_data.get("phone_number", None)
    full_name = form_data.get("full_name", None)
    role = form_data.get("role")
    is_active = form_data.get("is_active", "False") == "True"
    
    # Get selected groups
    group_ids = form_data.getlist("groups")

    # Add validation for client_admin role
    if role == models.UserRole.CLIENT_ADMIN.value and not group_ids:
        raise HTTPException(
            status_code=400,
            detail="A Client Admin must be assigned to at least one group."
        )

    # Basic validation
    if not username or not password or not role:
        raise HTTPException(status_code=400, detail="Missing required fields")
    
    # Check if username already exists
    existing = db.query(models.User).filter(models.User.username == username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")
    
    # Check if email is provided and already exists
    if email:
        existing_email = db.query(models.User).filter(models.User.email == email).first()
        if existing_email:
            raise HTTPException(status_code=400, detail="Email already exists")
    
    # Check if phone is provided and already exists
    if phone_number:
        existing_phone = db.query(models.User).filter(models.User.phone_number == phone_number).first()
        if existing_phone:
            raise HTTPException(status_code=400, detail="Phone number already exists")
    
    try:
        # Create new user with hashed password
        user = models.User(
            username=username,
            password_hash=get_password_hash(password),
            email=email,
            phone_number=phone_number,
            full_name=full_name,
            role=models.UserRole(role),
            is_active=is_active
        )
        
        db.add(user)
        db.commit()
        
        # Add user to selected groups
        if group_ids:
            for group_id in group_ids:
                group = db.query(models.Group).filter(models.Group.id == int(group_id)).first()
                if group:
                    user.groups.append(group)
            db.commit()
        
        return RedirectResponse(url="/admin/users", status_code=303)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/admin/users/{user_id}/edit", response_class=HTMLResponse)
async def edit_user_form(
    user_id: int,
    request: Request,
    current_admin: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Form to edit an existing user - SUPER_ADMIN only
    """
    # Check if current user is a super admin
    check_super_admin(current_admin)
    
    # Get the user
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Get all available groups
    groups = db.query(models.Group).order_by(models.Group.name).all()
    
    # Get user's group IDs
    user_group_ids = [group.id for group in user.groups]
    
    return templates.TemplateResponse(
        "user_form.html",
        {
            "request": request,
            "admin": current_admin,
            "user": user,
            "groups": groups,
            "user_groups": user_group_ids,
            "roles": [role.value for role in models.UserRole]
        }
    )

@router.post("/admin/users/{user_id}/edit")
async def update_user(
    user_id: int,
    request: Request,
    current_admin: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Update an existing user - SUPER_ADMIN only
    """
    # Check if current user is a super admin
    check_super_admin(current_admin)
    
    # Get the user
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Get form data
    form_data = await request.form()
    username = form_data.get("username")
    password = form_data.get("password")  # Optional for edit
    email = form_data.get("email", None)
    phone_number = form_data.get("phone_number", None)
    full_name = form_data.get("full_name", None)
    role = form_data.get("role")
    is_active = form_data.get("is_active", "False") == "True"
    
    # Get selected groups
    group_ids = form_data.getlist("groups")

    # Add validation for client_admin role
    if role == models.UserRole.CLIENT_ADMIN.value and not group_ids:
        raise HTTPException(
            status_code=400,
            detail="A Client Admin must be assigned to at least one group."
        )

    # Basic validation
    if not username or not role:
        raise HTTPException(status_code=400, detail="Missing required fields")
    
    # Check if username already exists (for another user)
    existing = db.query(models.User).filter(
        models.User.username == username,
        models.User.id != user_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")
    
    # Check if email is provided and already exists
    if email:
        existing_email = db.query(models.User).filter(
            models.User.email == email,
            models.User.id != user_id
        ).first()
        if existing_email:
            raise HTTPException(status_code=400, detail="Email already exists")
    
    # Check if phone is provided and already exists
    if phone_number:
        existing_phone = db.query(models.User).filter(
            models.User.phone_number == phone_number,
            models.User.id != user_id
        ).first()
        if existing_phone:
            raise HTTPException(status_code=400, detail="Phone number already exists")
    
    try:
        # Update user fields
        user.username = username
        user.email = email
        user.phone_number = phone_number
        user.full_name = full_name
        user.role = models.UserRole(role)
        user.is_active = is_active
        
        # Update password if provided
        if password:
            user.password_hash = get_password_hash(password)
        
        # Clear existing groups and add selected ones
        user.groups = []
        if group_ids:
            for group_id in group_ids:
                group = db.query(models.Group).filter(models.Group.id == int(group_id)).first()
                if group:
                    user.groups.append(group)
        
        # Update timestamp
        user.updated_at = datetime.utcnow()
        
        db.commit()
        
        return RedirectResponse(url="/admin/users", status_code=303)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/admin/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: int,
    current_admin: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Generate a password reset token for a user - SUPER_ADMIN only
    """
    # Check if current user is a super admin
    check_super_admin(current_admin)
    
    # Get the user
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Generate a reset token
    token = user.generate_reset_token()
    db.commit()
    
    # Redirect back to edit page with the token
    return templates.TemplateResponse(
        "user_form.html",
        {
            "request": {"url": {"path": f"/admin/users/{user_id}/edit"}},
            "admin": current_admin,
            "user": user,
            "groups": db.query(models.Group).order_by(models.Group.name).all(),
            "user_groups": [group.id for group in user.groups],
            "roles": [role.value for role in models.UserRole],
            "reset_token": token
        }
    )

@router.post("/admin/users/{user_id}/toggle-active")
async def toggle_user_active(
    user_id: int,
    current_admin: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Toggle a user's active status - SUPER_ADMIN only
    """
    # Check if current user is a super admin
    check_super_admin(current_admin)
    
    # Get the user
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Prevent deactivating yourself
    if user.id == current_admin.id:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")
    
    # Toggle active status
    user.is_active = not user.is_active
    db.commit()
    
    return RedirectResponse(url="/admin/users", status_code=303)

@router.post("/admin/users/{user_id}/delete")
async def delete_user(
    user_id: int,
    current_admin: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Delete a user - SUPER_ADMIN only
    """
    # Check if current user is a super admin
    check_super_admin(current_admin)
    
    # Get the user
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Prevent deleting yourself
    if user.id == current_admin.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    
    # Delete the user
    db.delete(user)
    db.commit()

    return RedirectResponse(url="/admin/users", status_code=303)