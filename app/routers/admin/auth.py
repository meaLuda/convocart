"""
Authentication module for admin interface
Handles login, logout, and authentication utilities
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from fastapi_csrf_protect.flexible import CsrfProtect

from app.database import get_db
from app import models
from app.config import get_settings
from app.templates_config import templates

settings = get_settings()
router = APIRouter()
logger = logging.getLogger(__name__)

# OAuth2 password bearer
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="admin/login")

# JWT settings
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# Password context for hashing and verification
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password, hashed_password):
    """Verify a password against a hash"""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    """Hash a password for storing"""
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=ALGORITHM)
    return encoded_jwt

class NotAuthenticatedException(Exception):
    """Custom exception for authentication failures"""
    pass

async def get_current_admin(request: Request, db: Session = Depends(get_db)):
    """Get current authenticated admin user"""
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

@router.get("/admin/login", response_class=HTMLResponse)
async def login_page(request: Request, csrf_protect: CsrfProtect = Depends(), error: Optional[str] = None):
    """Render the login page"""
    csrf_token, signed_token = csrf_protect.generate_csrf_tokens()
    context = {"request": request, "csrf_token": csrf_token}
    if error:
        context["error_message"] = error
    response = templates.TemplateResponse("login.html", context)
    csrf_protect.set_csrf_cookie(signed_token, response)
    return response

@router.post("/admin/login")
async def login(
    request: Request,
    csrf_protect: CsrfProtect = Depends(),
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    """Process login form"""
    try:
        await csrf_protect.validate_csrf(request)
    except Exception as e:
        logger.warning(f"CSRF validation failed: {str(e)}")
        return RedirectResponse(
            url="/admin/login?error=Invalid request. Please try again.",
            status_code=303
        )

    # Check credentials
    user = db.query(models.User).filter(models.User.username == username).first()
    
    if not user or not verify_password(password, user.password_hash):
        logger.warning(f"Failed login attempt for username: {username}")
        return RedirectResponse(
            url="/admin/login?error=Invalid username or password",
            status_code=303
        )
    
    if not user.is_active:
        logger.warning(f"Login attempt for inactive user: {username}")
        return RedirectResponse(
            url="/admin/login?error=Account is disabled. Contact administrator.",
            status_code=303
        )
    
    if user.role not in [models.UserRole.CLIENT_ADMIN, models.UserRole.SUPER_ADMIN]:
        logger.warning(f"Login attempt for user without admin privileges: {username}")
        return RedirectResponse(
            url="/admin/login?error=Insufficient privileges",
            status_code=303
        )

    # Create access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username, "role": user.role.value},
        expires_delta=access_token_expires
    )

    # Update last login time
    user.last_login = datetime.utcnow()
    db.commit()

    # Set cookie and redirect
    response = RedirectResponse(url="/admin/dashboard", status_code=303)
    response.set_cookie(
        key="access_token",
        value=f"Bearer {access_token}",
        httponly=True,
        secure=not settings.debug,  # Only send over HTTPS in production
        samesite="lax",
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )
    
    logger.info(f"Successful login for user: {username}")
    return response

@router.get("/admin/logout")
async def logout():
    """Logout and clear session"""
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie(key="access_token")
    return response