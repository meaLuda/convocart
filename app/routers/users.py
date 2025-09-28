import logging
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from app.database import get_db
from app import models
from passlib.context import CryptContext
from app.config import get_settings

settings = get_settings()


router = APIRouter()
logger = logging.getLogger(__name__)

# Import shared templates configuration
from app.templates_config import templates
from fastapi_csrf_protect import CsrfProtect


# OAuth2 password bearer
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="admin/login")

# JWT settings
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

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
class NotAuthenticatedException(Exception):
    """Custom exception for authentication failures"""
    pass

async def get_current_admin(
    request: Request,
    db: Session = Depends(get_db)
):
    # Get token from cookie
    token = request.cookies.get("access_token")
    if not token:
        raise NotAuthenticatedException("No authentication token found")
    
    # Remove "Bearer " prefix if present
    if token.startswith("Bearer "):
        token = token[7:]
    
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        username: str = payload.get("sub")
        if username is None:
            raise NotAuthenticatedException("Invalid token: no username")
    except JWTError:
        raise NotAuthenticatedException("Invalid or expired token")
    
    user = db.query(models.User).filter(models.User.username == username).first()
    if user is None or user.role not in [models.UserRole.CLIENT_ADMIN, models.UserRole.SUPER_ADMIN]:
        raise NotAuthenticatedException("User not found or insufficient permissions")
    
    return user


def check_admin_has_access_to_group(admin, group_id, db):
    """Check if an admin has access to a specific group"""
    if admin.role == models.UserRole.SUPER_ADMIN:
        return True
    
    # Check if admin is a member of this group
    return any(group.id == group_id for group in admin.groups)





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