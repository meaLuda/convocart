# app/main.py
import logging
from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pathlib import Path
import uvicorn
from app.database import SessionLocal, engine, Base, get_db
# from app.routers import users, webhook, data_import
from app.config import Settings, get_settings
from app import models
from app.config import get_settings
from contextlib import asynccontextmanager

from app.routers import users, webhook, data_import

settings = get_settings()
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

# Mount static files
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

# # Include routers
app.include_router(webhook.router, tags=["webhook"])
app.include_router(users.router, tags=["admin"])
app.include_router(data_import.router, tags=["data-import"])

# Initialize templates
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

def get_password_hash(password):
    """Hash a password for storing"""
    return pwd_context.hash(password)


    
    
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
