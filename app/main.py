# app/main.py
import logging
from datetime import datetime
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi_csrf_protect import CsrfProtect
from fastapi_csrf_protect.exceptions import CsrfProtectError
from sqlalchemy.orm import Session
from pathlib import Path
import uvicorn
import uuid
from app.database import SessionLocal, engine, Base, get_db
# from app.routers import users, webhook, data_import
from app.config import Settings, get_settings
from app import models
from app.config import get_settings
from contextlib import asynccontextmanager

from app.routers import users, webhook, data_import

settings = get_settings()

def validate_required_settings():
    """Validate that all required settings are present"""
    required_fields = ['twilio_account_sid', 'twilio_auth_token', 'twilio_whatsapp_number']
    missing_fields = []
    
    for field in required_fields:
        if not getattr(settings, field, None):
            missing_fields.append(field.upper())
    
    if missing_fields:
        logger.error(f"Missing required environment variables: {', '.join(missing_fields)}")
        logger.error("Please set these variables in your .env file or environment")
        return False
    
    logger.info("✅ All required Twilio configuration validated")
    return True

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

# Configure password hashing - import here to make configuration cleaner
from passlib.context import CryptContext
# Suppress the noisy bcrypt version warning
logging.getLogger("passlib.handlers.bcrypt").setLevel(logging.ERROR)


# Add this before creating the FastAPI app
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    Base.metadata.create_all(bind=engine)
    logger.info(f"Debug: {settings.debug}")

    # Create default admin user if not exists
    db = SessionLocal()
    try:
        admin = db.query(models.User).filter(
            models.User.username == settings.admin_username
        ).first()

        if not admin:
            try:
                # Create default super admin user with properly hashed password
                admin = models.User(
                    username=settings.admin_username,
                    password_hash=get_password_hash(settings.admin_password),
                    role=models.UserRole.SUPER_ADMIN,
                    is_active=True,
                    full_name="System Administrator"
                )
                db.add(admin)
                db.commit()
                logger.info("Created default super admin user")
            except Exception as e:
                logger.error(f"Error creating default admin user: {str(e)}")
                db.rollback()
        else:
            # Check if the existing user is a super admin
            if admin.role != models.UserRole.SUPER_ADMIN:
                # Update to super admin role if not already
                admin.role = models.UserRole.SUPER_ADMIN
                db.commit()
                logger.info("Updated default user to super admin role")
    finally:
        db.close()
    
    yield
    # Shutdown (if needed)
    
    
# Create password context with bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

app = FastAPI(
    title="ConvoCart",
    description="A simple ordering bot for WhatsApp Business API",
    version="1.0.0",
    lifespan=lifespan
)

origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CSRF Protection Configuration
@CsrfProtect.load_config
def get_csrf_config():
    return [
        ('secret_key', settings.secret_key),
        ('cookie_secure', not settings.debug),
        ('cookie_samesite', 'lax')
    ]

csrf = CsrfProtect()

# CSRF Error Handler
@app.exception_handler(CsrfProtectError)
def csrf_protect_exception_handler(request: Request, exc: CsrfProtectError):
    return {"detail": "CSRF token verification failed"}

# Mount static files
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

# # Include routers
app.include_router(webhook.router, tags=["webhook"])
app.include_router(users.router, tags=["admin"])
app.include_router(data_import.router, tags=["data-import"])

# Import shared templates configuration
from app.templates_config import templates

def get_password_hash(password):
    """Hash a password for storing"""
    return pwd_context.hash(password)

# Error handlers
@app.exception_handler(404)
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Handle HTTP exceptions with custom error pages"""
    error_id = str(uuid.uuid4())[:8]
    error_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    logger.error(f"HTTP Exception {exc.status_code}: {exc.detail} | Error ID: {error_id} | URL: {request.url}")
    
    # Determine appropriate template and context
    if exc.status_code == 404:
        template = "error/404.html"
        context = {
            "request": request,
            "error_code": 404,
            "error_id": error_id,
            "error_time": error_time
        }
    elif exc.status_code == 403:
        template = "error/403.html"
        context = {
            "request": request,
            "error_code": 403,
            "error_id": error_id,
            "error_time": error_time
        }
    elif exc.status_code == 500:
        template = "error/500.html"
        context = {
            "request": request,
            "error_code": 500,
            "error_details": str(exc.detail) if exc.detail else None,
            "error_id": error_id,
            "error_time": error_time
        }
    else:
        # Generic error template
        template = "error/generic.html"
        context = {
            "request": request,
            "error_code": exc.status_code,
            "error_title": "Error",
            "error_message": str(exc.detail) if exc.detail else "An unexpected error occurred",
            "error_icon": "fa-exclamation-circle",
            "error_id": error_id,
            "error_time": error_time,
            "show_retry": True
        }
    
    return templates.TemplateResponse(template, context, status_code=exc.status_code)

@app.exception_handler(500)
async def internal_server_error_handler(request: Request, exc: Exception):
    """Handle internal server errors"""
    error_id = str(uuid.uuid4())[:8]
    error_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    logger.error(f"Internal Server Error: {str(exc)} | Error ID: {error_id} | URL: {request.url}", exc_info=True)
    
    context = {
        "request": request,
        "error_code": 500,
        "error_details": str(exc) if settings.debug else "Internal server error occurred",
        "error_id": error_id,
        "error_time": error_time
    }
    
    return templates.TemplateResponse("error/500.html", context, status_code=500)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle request validation errors"""
    error_id = str(uuid.uuid4())[:8]
    error_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    logger.warning(f"Validation Error: {exc.errors()} | Error ID: {error_id} | URL: {request.url}")
    
    # For API requests, return JSON
    if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
        return {
            "detail": "Validation error",
            "errors": exc.errors(),
            "error_id": error_id
        }
    
    # For web requests, return HTML error page
    context = {
        "request": request,
        "error_code": 422,
        "error_title": "Validation Error",
        "error_message": "The submitted data contains errors. Please check your input and try again.",
        "error_details": "; ".join([f"{error['loc'][-1]}: {error['msg']}" for error in exc.errors()]),
        "error_icon": "fa-exclamation-triangle",
        "error_id": error_id,
        "error_time": error_time,
        "show_retry": True
    }
    
    return templates.TemplateResponse("error/generic.html", context, status_code=422)


    
    
@app.get("/")
async def root(request: Request):
    return templates.TemplateResponse(
        "intro.html",
        {
            "request": request,
            "title": "ConvoCart ConvoCart",
            "message": "Welcome to the ConvoCart"
        }
    )

@app.get("/admin/data-import-htmx")
async def data_import_htmx_page(request: Request):
    """
    HTMX-enhanced data import page for testing
    """
    return templates.TemplateResponse(
        "data_import_htmx.html",
        {"request": request}
    )

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.debug)
