from datetime import datetime, timedelta
import enum
import json
from sqlalchemy.orm import Session
from sqlalchemy import JSON, Column, Integer, String, Text, DateTime, Float, Boolean, ForeignKey, Enum, Table, TypeDecorator, UniqueConstraint,func
from sqlalchemy.orm import relationship, validates
from sqlalchemy.ext.declarative import declared_attr
import phonenumbers
from app.database import Base
import re
import secrets
import string


class JsonGettable(TypeDecorator):
    """
    Custom JSON type for SQLite compatibility.
    Strores data as a JSON string in a TEXT column.
    """
    impl = Text

    def process_bind_param(self, value, dialect):
        if value is not None:
            return json.dumps(value)

    def process_result_value(self, value, dialect):
        if value is not None:
            return json.loads(value)


# Base mixin for common fields
class TimestampMixin:
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


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
    Column("group_id", Integer, ForeignKey("groups.id"), primary_key=True),
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
            try:
                p = phonenumbers.parse(phone, None)
                if not phonenumbers.is_valid_number(p):
                    raise ValueError("Invalid phone number")
                return phonenumbers.format_number(
                    p, phonenumbers.PhoneNumberFormat.E164
                )
            except phonenumbers.phonenumberutil.NumberParseException as e:
                raise ValueError("Invalid phone number") from e
        return phone

    def generate_verification_token(self):
        """Generate a random token for email verification"""
        alphabet = string.ascii_letters + string.digits
        token = "".join(secrets.choice(alphabet) for _ in range(50))
        self.verification_token = token
        return token

    def generate_reset_token(self, expires_in_hours=24):
        """Generate a password reset token"""
        alphabet = string.ascii_letters + string.digits
        token = "".join(secrets.choice(alphabet) for _ in range(50))
        self.reset_token = token
        self.reset_token_expires_at = datetime.utcnow() + timedelta(
            hours=expires_in_hours
        )
        return token


class Customer(Base, TimestampMixin):
    """Customer model for storing customer information. Each customer is tied to a group."""

    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    phone_number = Column(String(20), nullable=False, index=True)

    # New field to track the current session group context
    active_group_id = Column(
        Integer, ForeignKey("groups.id"), nullable=True, index=True
    )

    # Relationships - specify foreign_keys explicitly to resolve ambiguity
    group = relationship("Group", back_populates="customers", foreign_keys=[group_id])
    active_group = relationship("Group", foreign_keys=[active_group_id])
    orders = relationship("Order", back_populates="customer")
    conversation_sessions = relationship(
        "ConversationSession",
        back_populates="customer",
        order_by="desc(ConversationSession.last_interaction)",
    )

    @validates('phone_number')
    def validate_phone(self, key, phone):
        if phone is not None:
            try:
                p = phonenumbers.parse(phone, None)
                if not phonenumbers.is_valid_number(p):
                    raise ValueError("Invalid phone number")
                return phonenumbers.format_number(
                    p, phonenumbers.PhoneNumberFormat.E164
                )
            except phonenumbers.phonenumberutil.NumberParseException as e:
                raise ValueError("Invalid phone number") from e
        return phone

    class Meta:
        # Define table constraints
        __table_args__ = (
            # Ensure phone_number is unique within a group
            UniqueConstraint(
                "group_id", "phone_number", name="uix_customer_group_phone"
            ),
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
    customers = relationship(
        "Customer", back_populates="group", foreign_keys=[Customer.group_id]
    )
    orders = relationship("Order", back_populates="group")

    @validates('identifier')
    def validate_identifier(self, key, identifier):
        # Ensure identifier is URL-friendly
        if not re.match(r"^[a-z0-9_-]+$", identifier):
            raise ValueError(
                "Identifier can only contain lowercase letters, numbers, underscores, and dashes"
            )
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
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

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
    def set_value(
        db: Session, key: str, value: str, description: str = None
    ) -> "Configuration":
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
    payment_ref = (
        Column(String(50), nullable=True)  # Payment reference/transaction code i.e MPESA code
    )
    payment_status = Column(
        Enum(PaymentStatus), default=PaymentStatus.UNPAID, nullable=False
    )
    last_notification_sent = Column(DateTime, nullable=True)
    notification_count = Column(Integer, default=0)

    # Relationships
    customer = relationship("Customer", back_populates="orders")
    group = relationship("Group", back_populates="orders")

    def __init__(self, **kwargs):
        super(Order, self).__init__(**kwargs)
        if not self.order_number:
            self.order_number = self.generate_order_number()

    def generate_order_number(self):
        """Generate a unique order number"""
        timestamp = datetime.utcnow().strftime("%Y%m%d")
        random_part = "".join(secrets.choice(string.digits) for _ in range(4))
        return f"ORD-{timestamp}-{random_part}"

    def can_send_notification(self, interval_minutes=5):
        """Check if a notification can be sent to avoid spamming."""
        if not self.last_notification_sent:
            return True

        time_since_last_sent = datetime.utcnow() - self.last_notification_sent
        if time_since_last_sent > timedelta(minutes=interval_minutes):
            return True

        return False

    def record_notification(self):
        """Record that a notification has been sent."""
        self.last_notification_sent = datetime.utcnow()
        self.notification_count = (self.notification_count or 0) + 1


class ConversationState(str, enum.Enum):
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
    current_state = Column(Enum(ConversationState), default=ConversationState.INITIAL)
    context_data = Column(
        JsonGettable, nullable=True
    )  # Stores JSON data related to current conversation
    last_interaction = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    customer = relationship("Customer", back_populates="conversation_sessions")

    def update_state(self, new_state, context=None):
        """
        Update the conversation state and context
        """
        self.current_state = (
            new_state.value if isinstance(new_state, ConversationState) else new_state
        )

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
        session = (
            db.query(cls)
            .filter(cls.customer_id == customer_id, cls.is_active == True)
            .order_by(cls.last_interaction.desc())
            .first()
        )

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
                is_active=True,
            )
            db.add(session)
            db.commit()
            db.refresh(session)

        return session


# Flow system enums
class StateType(str, enum.Enum):
    SEND_MESSAGE = "send_message"
    AWAIT_RESPONSE = "await_response"
    END_SESSION = "end_session"


class TriggerType(str, enum.Enum):
    KEYWORD = "keyword"
    BUTTON_ID = "button_id"
    ANY_TEXT = "any_text"
    SYSTEM = "system"  # For automatic transitions


class ActionName(str, enum.Enum):
    # Order management actions
    CREATE_ORDER = "create_order"
    TRACK_ORDER = "track_order"
    CANCEL_ORDER = "cancel_order"

    # Payment actions
    HANDLE_MPESA_PAYMENT = "handle_mpesa_payment"
    HANDLE_CASH_PAYMENT = "handle_cash_payment"
    HANDLE_PAYMENT_CONFIRMATION = "handle_payment_confirmation"

    # Communication actions
    SEND_WELCOME_MESSAGE = "send_welcome_message"
    SEND_HELP_MESSAGE = "send_help_message"
    SEND_PAYMENT_OPTIONS = "send_payment_options"
    CONTACT_SUPPORT = "contact_support"

    # System actions
    NO_ACTION = "no_action"
    RESET_SESSION = "reset_session"


class Flow(Base, TimestampMixin):
    """

    Represents a complete conversational bot flow for a client group
    """

    __tablename__ = "flows"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=False, nullable=False, index=True)
    start_state_id = Column(
        Integer, ForeignKey("flow_states.id"), nullable=True
    )  # Will be set after states are created

    # Relationships - specify foreign keys to resolve ambiguity
    group = relationship("Group", back_populates="flows")
    states = relationship(
        "FlowState",
        back_populates="flow",
        foreign_keys="FlowState.flow_id",
        cascade="all, delete-orphan",
    )
    start_state = relationship("FlowState", foreign_keys=[start_state_id], post_update=True)

    # Ensure only one active flow per group
    __table_args__ = (
        UniqueConstraint(
            "group_id", "is_active", name="uix_group_active_flow", sqlite_on_conflict="REPLACE"
        ),
    )


class FlowState(Base, TimestampMixin):
    """
    Represents a single step or state in a conversation flow
    """

    __tablename__ = "flow_states"

    id = Column(Integer, primary_key=True, index=True)
    flow_id = Column(Integer, ForeignKey("flows.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    message_body = Column(
        Text, nullable=True
    )  # Message to send when entering this state
    state_type = Column(Enum(StateType), default=StateType.SEND_MESSAGE, nullable=False)
    is_start_state = Column(Boolean, default=False, nullable=False, index=True)

    # JSON field for storing additional state configuration (buttons, etc.)
    state_config = Column(JsonGettable, nullable=True)

    # Relationships
    flow = relationship("Flow", back_populates="states", foreign_keys=[flow_id])
    outgoing_transitions = relationship(
        "FlowTransition",
        foreign_keys="FlowTransition.source_state_id",
        back_populates="source_state",
        cascade="all, delete-orphan",
    )
    incoming_transitions = relationship(
        "FlowTransition",
        foreign_keys="FlowTransition.target_state_id",
        back_populates="target_state",
    )


class FlowAction(Base, TimestampMixin):
    """
    Predefined actions that can be performed during flow transitions
    """

    __tablename__ = "flow_actions"

    id = Column(Integer, primary_key=True, index=True)
    action_name = Column(Enum(ActionName), unique=True, nullable=False)
    display_name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    # Relationships
    transitions = relationship("FlowTransition", back_populates="action")


class FlowTransition(Base, TimestampMixin):
    """
    Defines transitions between flow states with trigger conditions and actions
    """

    __tablename__ = "flow_transitions"

    id = Column(Integer, primary_key=True, index=True)
    source_state_id = Column(Integer, ForeignKey("flow_states.id"), nullable=False)
    target_state_id = Column(Integer, ForeignKey("flow_states.id"), nullable=False)
    trigger_type = Column(Enum(TriggerType), nullable=False)
    trigger_value = Column(
        String(255), nullable=True
    )  # The specific value to match (keyword, button_id, etc.)
    action_id = Column(Integer, ForeignKey("flow_actions.id"), nullable=True)
    priority = Column(Integer, default=0, nullable=False, index=True)

    # Relationships
    source_state = relationship(
        "FlowState",
        foreign_keys=[source_state_id],
        back_populates="outgoing_transitions",
    )
    target_state = relationship(
        "FlowState",
        foreign_keys=[target_state_id],
        back_populates="incoming_transitions",
    )
    action = relationship("FlowAction", back_populates="transitions")


# Add flows relationship to Group model
Group.flows = relationship("Flow", back_populates="group", cascade="all, delete-orphan")

# Add a relationship from Group to the active Flow
Group.active_flow = relationship(
    "Flow",
    primaryjoin="and_(Group.id == Flow.group_id, Flow.is_active == True)",
    uselist=False,
    viewonly=True,
)
