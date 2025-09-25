from sqlalchemy import event, text, create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.exc import SQLAlchemyError
import logging
from app.config import get_settings

settings = get_settings()

# Configure logging
logger = logging.getLogger(__name__)

# PostgreSQL database URL
SQLALCHEMY_DATABASE_URL = settings.database_url

# Create PostgreSQL engine with connection pooling
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    echo=False,  # Disable SQL query logging to reduce noise
    pool_pre_ping=True,  # Verify connections before using them
    pool_recycle=1800,   # Recycle connections every 30 minutes
    pool_size=5,         # Connection pool size
    max_overflow=10,     # Maximum overflow connections
    pool_timeout=30,     # Timeout for getting connection from pool
    connect_args={
        "connect_timeout": 10,  # Connection timeout
        "application_name": "OrderBot"
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
            if db:
                try:
                    db.close()
                except Exception as e:
                    logger.error(f"Error closing database connection: {e}")