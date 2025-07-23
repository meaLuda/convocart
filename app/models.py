# app/models.py
from datetime import datetime, timedelta
import enum
import json
from sqlalchemy.orm import Session
from sqlalchemy import JSON, Column, Integer, String, Text, DateTime, Float, Boolean, ForeignKey, Enum, Table, UniqueConstraint,func
from sqlalchemy.orm import relationship, validates
from sqlalchemy.ext.declarative import declared_attr
from app.database import Base
import re
import secrets
import string

# Base mixin for common fields
class TimestampMixin:
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

# User role enum
class UserRole(enum.Enum):
    CLIENT_ADMIN = "admin"
    SUPER_ADMIN = "super_admin"

# Order status enum
class OrderStatus(enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"

# Payment status enum
class PaymentStatus(enum.Enum):
    UNPAID = "unpaid"
    PAID = "paid"
    VERIFIED = "verified"
    FAILED = "failed"
    REFUNDED = "refunded"

# Payment method enum
class PaymentMethod(enum.Enum):
    MPESA = "mpesa"
    CASH_ON_DELIVERY = "cash_on_delivery"
    CARD = "card"

# Many-to-many relationship table for users and groups (for group memberships)
user_groups = Table(
    "user_groups",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("group_id", Integer, ForeignKey("groups.id"), primary_key=True)
)

class User(Base, TimestampMixin):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=True)
    phone_number = Column(String(20), unique=True, index=True, nullable=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(100), nullable=True)
    role = Column(Enum(UserRole), default=UserRole.CLIENT_ADMIN, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    last_login = Column(DateTime, nullable=True)
    account_verified = Column(Boolean, default=False, nullable=False)
    verification_token = Column(String(100), nullable=True)
    reset_token = Column(String(100), nullable=True)
    reset_token_expires_at = Column(DateTime, nullable=True)
    
    # Relationships
    groups = relationship("Group", secondary=user_groups, back_populates="users")
    
    @validates('email')
    def validate_email(self, key, email):
        if email is not None:
            # Basic email validation
            if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
                raise ValueError("Invalid email address")
        return email
    
    @validates('phone_number')
    def validate_phone(self, key, phone):
        if phone is not None:
            # Remove any non-digit characters
            clean_phone = re.sub(r'\D', '', phone)
            # Ensure it's a valid length (adjust as needed for your country)
            if len(clean_phone) < 9 or len(clean_phone) > 15:
                raise ValueError("Phone number must be between 9 and 15 digits")
            return clean_phone
        return phone
    
    def generate_verification_token(self):
        """Generate a random token for email verification"""
        alphabet = string.ascii_letters + string.digits
        token = ''.join(secrets.choice(alphabet) for _ in range(50))
        self.verification_token = token
        return token
    
    def generate_reset_token(self, expires_in_hours=24):
        """Generate a password reset token"""
        alphabet = string.ascii_letters + string.digits
        token = ''.join(secrets.choice(alphabet) for _ in range(50))
        self.reset_token = token
        self.reset_token_expires_at = datetime.utcnow() + datetime.timedelta(hours=expires_in_hours)
        return token

class Customer(Base, TimestampMixin):
    """Customer model for storing customer information. Each customer is tied to a group."""
    __tablename__ = "customers"
    
    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    phone_number = Column(String(20), nullable=False, index=True)
    
    # New field to track the current session group context
    active_group_id = Column(Integer, ForeignKey("groups.id"), nullable=True)
    
    # Relationships - specify foreign_keys explicitly to resolve ambiguity
    group = relationship("Group", back_populates="customers", foreign_keys=[group_id])
    active_group = relationship("Group", foreign_keys=[active_group_id])
    orders = relationship("Order", back_populates="customer")
    conversation_sessions = relationship("ConversationSession", back_populates="customer", order_by="desc(ConversationSession.last_interaction)")

    @validates('phone_number')
    def validate_phone(self, key, phone):
        if phone is not None:
            # Remove any non-digit characters
            clean_phone = re.sub(r'\D', '', phone)
            # Ensure it's a valid length
            if len(clean_phone) < 9 or len(clean_phone) > 15:
                raise ValueError("Phone number must be between 9 and 15 digits")
            return clean_phone
        return phone
    
    class Meta:
        # Define table constraints
        __table_args__ = (
            # Ensure phone_number is unique within a group
            UniqueConstraint('group_id', 'phone_number', name='uix_customer_group_phone'),
        )


class Group(Base, TimestampMixin):
    __tablename__ = "groups"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    identifier = Column(String(50), unique=True, index=True, nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(50), nullable=True)
    welcome_message = Column(Text, nullable=True)
    logo_url = Column(String(255), nullable=True)
    contact_email = Column(String(100), nullable=True)
    contact_phone = Column(String(20), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Relationships - specify foreign_keys in the Customer relationship
    users = relationship("User", secondary=user_groups, back_populates="groups")
    customers = relationship("Customer", back_populates="group", foreign_keys=[Customer.group_id])
    orders = relationship("Order", back_populates="group")
    
    @validates('identifier')
    def validate_identifier(self, key, identifier):
        # Ensure identifier is URL-friendly
        if not re.match(r'^[a-z0-9_-]+$', identifier):
            raise ValueError("Identifier can only contain lowercase letters, numbers, underscores, and dashes")
        return identifier

class Configuration(Base):
    """
    System configuration settings stored as key-value pairs
    """
    __tablename__ = "configurations"
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(255), unique=True, index=True, nullable=False)
    value = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    @staticmethod
    def get_value(db: Session, key: str, default_value: str = None) -> str:
        """
        Get a configuration value by key
        """
        config = db.query(Configuration).filter(Configuration.key == key).first()
        if config and config.value:
            return config.value
        return default_value
    
    @staticmethod
    def set_value(db: Session, key: str, value: str, description: str = None) -> 'Configuration':
        """
        Set a configuration value (create or update)
        """
        config = db.query(Configuration).filter(Configuration.key == key).first()
        if config:
            config.value = value
            if description:
                config.description = description
        else:
            config = Configuration(key=key, value=value, description=description)
            db.add(config)
        
        db.commit()
        return config


class Order(Base, TimestampMixin):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    order_number = Column(String(20), unique=True, index=True, nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    group_id = Column(Integer, ForeignKey("groups.id"), index=True, nullable=False)
    order_details = Column(Text, nullable=True)  # JSON data of order items
    status = Column(Enum(OrderStatus), default=OrderStatus.PENDING, nullable=False)
    total_amount = Column(Float, default=0.0, nullable=False)
    payment_method = Column(Enum(PaymentMethod), nullable=True)
    payment_ref = Column(String(50), nullable=True)     # Payment reference/transaction code i.e MPESA code
    payment_status = Column(Enum(PaymentStatus), default=PaymentStatus.UNPAID, nullable=False)
    
    # Relationships
    customer = relationship("Customer", back_populates="orders")
    group = relationship("Group", back_populates="orders")
    
    def __init__(self, **kwargs):
        super(Order, self).__init__(**kwargs)
        if not self.order_number:
            self.order_number = self.generate_order_number()
    
    def generate_order_number(self):
        """Generate a unique order number"""
        timestamp = datetime.utcnow().strftime('%Y%m%d')
        random_part = ''.join(secrets.choice(string.digits) for _ in range(4))
        return f"ORD-{timestamp}-{random_part}"


class ConversationState(str, Enum):
    """
    Enum for tracking conversation states
    """
    INITIAL = "initial"
    WELCOME = "welcome"
    AWAITING_ORDER_DETAILS = "awaiting_order_details"
    AWAITING_PAYMENT = "awaiting_payment"
    AWAITING_PAYMENT_CONFIRMATION = "awaiting_payment_confirmation"
    TRACKING_ORDER = "tracking_order"
    WAITING_FOR_SUPPORT = "waiting_for_support"
    IDLE = "idle"

class ConversationSession(Base):
    """
    Model for tracking customer conversation sessions
    """
    __tablename__ = "conversation_sessions"
    
    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    current_state = Column(String(50), default=ConversationState.INITIAL)
    context_data = Column(JSON, nullable=True)  # Stores JSON data related to current conversation
    last_interaction = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    customer = relationship("Customer", back_populates="conversation_sessions")
    
    def update_state(self, new_state, context=None):
        """
        Update the conversation state and context
        """
        self.current_state = new_state.value if isinstance(new_state, ConversationState) else new_state
        
        if context:
            # Update only the provided context fields, preserving existing ones
            current_context = self.get_context() or {}
            current_context.update(context)
            self.context_data = current_context
            
        self.last_interaction = datetime.utcnow()
        
    def get_context(self):
        """
        Get the current context data as a Python dict
        """
        if self.context_data:
            if isinstance(self.context_data, str):
                return json.loads(self.context_data)
            return self.context_data
        return {}
        
    def is_expired(self, expiry_minutes=30):
        """
        Check if the conversation has expired (inactive for too long)
        """
        if not self.is_active:
            return True
            
        expiry_time = datetime.utcnow() - timedelta(minutes=expiry_minutes)
        return self.last_interaction < expiry_time
    
    @classmethod
    def get_or_create_session(cls, db, customer_id):
        """
        Get the active session for a customer or create a new one
        """
        # Find active session
        session = db.query(cls).filter(
            cls.customer_id == customer_id,
            cls.is_active == True
        ).order_by(cls.last_interaction.desc()).first()
        
        # If no active session or session expired, create new one
        if not session or session.is_expired():
            if session:
                # Deactivate expired session
                session.is_active = False
                db.commit()
                
            # Create new session
            session = cls(
                customer_id=customer_id,
                current_state=ConversationState.INITIAL,
                is_active=True
            )
            db.add(session)
            db.commit()
            db.refresh(session)
            
        return session