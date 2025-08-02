from sqlalchemy import event, text, create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.declarative import declarative_base
import sqlalchemy_libsql.libsql  # noqa: F401
from sqlalchemy.exc import SQLAlchemyError
import logging
from app.config import get_settings

settings = get_settings()

# Configure logging
logger = logging.getLogger(__name__)

# Construct the URL without auth parameters
SQLALCHEMY_DATABASE_URL = f"sqlite+libsql://{settings.turso_database_url}?secure=true"

# Create synchronous engine with auth token in connect_args
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    echo=True,
    connect_args={
        "auth_token": settings.turso_auth_token
    }
)

# Create synchronous session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Synchronous dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()