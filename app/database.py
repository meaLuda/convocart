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
# SQLite/libsql doesn't support all PostgreSQL pooling options
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    echo=False,  # Disable SQL query logging to reduce noise
    pool_pre_ping=True,  # Verify connections before using them
    pool_recycle=1800,   # Recycle connections every 30 minutes
    connect_args={
        "auth_token": settings.turso_auth_token
    }
)

# Create synchronous session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Synchronous dependency with error handling and retry logic
def get_db():
    db = None
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            db = SessionLocal()
            # Test connection with a simple query to catch connection issues early
            db.execute(text("SELECT 1")).fetchone()
            yield db
            break  # Success, exit retry loop
        except SQLAlchemyError as e:
            logger.error(f"Database connection error (attempt {retry_count + 1}): {e}")
            if db:
                try:
                    db.rollback()
                    db.close()
                except:
                    pass
            retry_count += 1
            if retry_count >= max_retries:
                raise
        except Exception as e:
            logger.error(f"Unexpected database error: {e}")
            if db:
                try:
                    db.rollback()
                    db.close()
                except:
                    pass
            raise
        finally:
            if db and retry_count < max_retries:
                try:
                    db.close()
                except Exception as e:
                    logger.error(f"Error closing database connection: {e}")