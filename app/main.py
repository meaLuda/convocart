# app/main.py
import logging
from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pathlib import Path
import uvicorn
from app.database import engine, Base, get_db
from app.routers import webhook, admin
from app.config import HOST, PORT, DEBUG, ADMIN_USERNAME, ADMIN_PASSWORD
from app import models

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

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

# Include routers
app.include_router(webhook.router, tags=["webhook"])
app.include_router(admin.router, tags=["admin"])

# Initialize templates
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

@app.on_event("startup")
async def startup_event():
    # Create database tables
    Base.metadata.create_all(bind=engine)
    
    # Create default admin user if not exists
    db = next(get_db())
    admin = db.query(models.Admin).filter(models.Admin.username == ADMIN_USERNAME).first()
    if not admin:
        admin = models.Admin(
            username=ADMIN_USERNAME,
            password=ADMIN_PASSWORD  # In production, use proper password hashing
        )
        db.add(admin)
        db.commit()
        logger.info("Created default admin user")

@app.get("/")
async def root(request: Request):
    return templates.TemplateResponse(
        "base.html",
        {
            "request": request,
            "title": "WhatsApp Order Bot",
            "message": "Welcome to the WhatsApp Order Bot"
        }
    )

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=DEBUG)