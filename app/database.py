# app/database.py
from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import OperationalError, SQLAlchemyError
import logging
import time
from app.config import DATABASE_URI_POSTGRES

# Configure logging
logger = logging.getLogger(__name__)

# Maximum number of retries for database connection
MAX_RETRIES = 5
RETRY_DELAY = 2  # seconds between retries

# Create SQLAlchemy engine with retry mechanism
def create_db_engine_with_retry():
    retry_count = 0
    last_exception = None
    
    while retry_count < MAX_RETRIES:
        try:
            logger.info("Attempting to connect to PostgreSQL database")
            engine = create_engine(
                DATABASE_URI_POSTGRES,
                pool_pre_ping=True,
                pool_recycle=3600,
                connect_args={"connect_timeout": 10}
            )
            
            # Test the connection
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                conn.close()
            
            logger.info("Successfully connected to PostgreSQL database")
            return engine
            
        except (OperationalError, SQLAlchemyError) as e:
            last_exception = e
            retry_count += 1
            wait_time = RETRY_DELAY * (2 ** (retry_count - 1))  # Exponential backoff
            logger.warning(f"Database connection attempt {retry_count} failed: {str(e)}. Retrying in {wait_time} seconds...")
            time.sleep(wait_time)
    
    # If we get here, all retries failed
    logger.error(f"All database connection attempts failed after {MAX_RETRIES} retries")
    raise last_exception

# Initialize engine
engine = None
if DATABASE_URI_POSTGRES:
    try:
        engine = create_db_engine_with_retry()
    except Exception as e:
        logger.error(f"Failed to initialize database engine: {str(e)}")
        raise

if engine:
    # Add event listeners for connection pooling
    @event.listens_for(engine, "connect")
    def connect(dbapi_connection, connection_record):
        logger.debug("Database connection established")

    @event.listens_for(engine, "checkout")
    def checkout(dbapi_connection, connection_record, connection_proxy):
        logger.debug("Database connection checked out from pool")

    @event.listens_for(engine, "checkin")
    def checkin(dbapi_connection, connection_record):
        logger.debug("Database connection returned to pool")

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create base class for models
Base = declarative_base()

# Dependency to get database session with error handling
def get_db():
    db = SessionLocal()
    try:
        # Test the connection before yielding
        db.execute(text("SELECT 1"))
        yield db
    except SQLAlchemyError as e:
        logger.error(f"Database error during session: {str(e)}")
        # If we get a database error here, we might need to reinitialize engine
        global engine
        engine = create_db_engine_with_retry()
        SessionLocal.configure(bind=engine)
        db = SessionLocal()
        yield db
    finally:
        db.close()