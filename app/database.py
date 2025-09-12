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

# Create synchronous engine with auth token in connect_args and connection resilience
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    echo=False,  # Disable SQL query logging to reduce noise
    pool_pre_ping=True,  # Verify connections before using them
    pool_recycle=3600,   # Recycle connections every hour
    connect_args={
        "auth_token": settings.turso_auth_token
    }
)

# Create synchronous session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Synchronous dependency with error handling
def get_db():
    db = SessionLocal()
    try:
        # Test connection with a simple query to catch connection issues early
        db.execute(text("SELECT 1")).fetchone()
        yield db
    except SQLAlchemyError as e:
        logger.error(f"Database connection error: {e}")
        db.rollback()
        raise
    except Exception as e:
        logger.error(f"Unexpected database error: {e}")
        db.rollback()
        raise
    finally:
        try:
            db.close()
        except Exception as e:
            logger.error(f"Error closing database connection: {e}")