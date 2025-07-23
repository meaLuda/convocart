# app/main.py
import logging
from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pathlib import Path
import uvicorn
# from app.database import engine, Base, get_db
# from app.routers import users, webhook
from app.config import HOST, PORT, DEBUG, SUPER_ADMIN_USERNAME, SUPER_ADMIN_PASSWORD
from app import models

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

# Create password context with bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Create the FastAPI app
app = FastAPI(
    title="WhatsApp Order Bot",
    description="A simple ordering bot for WhatsApp Business API",
    version="1.0.0",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

# # Include routers
# app.include_router(webhook.router, tags=["webhook"])
# app.include_router(users.router, tags=["admin"])

# Initialize templates
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

def get_password_hash(password):
    """Hash a password for storing"""
    return pwd_context.hash(password)

@app.on_event("startup")
async def startup_event():
    # Create database tables
    # Base.metadata.create_all(bind=engine)
    logger.info(f"Debug: {DEBUG}")

    # # Create default admin user if not exists
    # db = next(get_db())
    # admin = db.query(models.User).filter(models.User.username == SUPER_ADMIN_USERNAME).first()

    # if not admin:
    #     try:
    #         # Create default super admin user with properly hashed password
    #         admin = models.User(
    #             username=SUPER_ADMIN_USERNAME,
    #             password_hash=get_password_hash(SUPER_ADMIN_PASSWORD),
    #             role=models.UserRole.SUPER_ADMIN,
    #             is_active=True,
    #             full_name="System Administrator"
    #         )
    #         db.add(admin)
    #         db.commit()
    #         logger.info("Created default super admin user")
    #     except Exception as e:
    #         logger.error(f"Error creating default admin user: {str(e)}")
    #         db.rollback()
    # else:
    #     # Check if the existing user is a super admin
    #     if admin.role != models.UserRole.SUPER_ADMIN:
    #         # Update to super admin role if not already
    #         admin.role = models.UserRole.SUPER_ADMIN
    #         db.commit()
    #         logger.info("Updated default user to super admin role")

@app.get("/")
async def root(request: Request):
    return templates.TemplateResponse(
        "intro.html",
        {
            "request": request,
            "title": "WhatsApp Order Bot ConvoCart",
            "message": "Welcome to the WhatsApp Order Bot"
        }
    )

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=DEBUG)
