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
    BANK_TRANSFER = "bank_transfer"
    MOBILE_MONEY = "mobile_money"
    CRYPTOCURRENCY = "crypto"


# Business type enum for multi-vertical support
class BusinessType(enum.Enum):
    RESTAURANT = "restaurant"
    RETAIL = "retail"
    GROCERY = "grocery"
    PHARMACY = "pharmacy"
    ELECTRONICS = "electronics"
    FASHION = "fashion"
    SERVICES = "services"
    AUTOMOTIVE = "automotive"
    BEAUTY = "beauty"
    FITNESS = "fitness"
    EDUCATION = "education"
    REAL_ESTATE = "real_estate"
    AGRICULTURE = "agriculture"
    GENERAL = "general"


# Product category for different business types
class ProductCategory(enum.Enum):
    # Restaurant
    FOOD = "food"
    BEVERAGES = "beverages"
    # Retail
    CLOTHING = "clothing"
    ACCESSORIES = "accessories"
    # Electronics
    SMARTPHONES = "smartphones"
    COMPUTERS = "computers"
    # Pharmacy
    MEDICINES = "medicines"
    HEALTH_PRODUCTS = "health_products"
    # Services
    CONSULTATION = "consultation"
    DELIVERY = "delivery"
    # General
    PHYSICAL_PRODUCT = "physical_product"
    DIGITAL_PRODUCT = "digital_product"
    SERVICE = "service"


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
    category = Column(String(50), nullable=True)  # Deprecated: use business_type
    business_type = Column(Enum(BusinessType), default=BusinessType.GENERAL, nullable=False)
    welcome_message = Column(Text, nullable=True)
    logo_url = Column(String(255), nullable=True)
    contact_email = Column(String(100), nullable=True)
    contact_phone = Column(String(20), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Business-specific settings
    business_settings = Column(JsonGettable, nullable=True)  # Store business-specific configurations
    operating_hours = Column(JsonGettable, nullable=True)  # Store operating hours
    delivery_areas = Column(JsonGettable, nullable=True)  # Store delivery areas/zones
    payment_methods = Column(JsonGettable, nullable=True)  # Store accepted payment methods
    
    # AI/ML settings
    ai_personality = Column(Text, nullable=True)  # AI personality for this business
    custom_prompts = Column(JsonGettable, nullable=True)  # Custom AI prompts for business
    
    # Analytics settings
    analytics_enabled = Column(Boolean, default=True, nullable=False)
    recommendation_engine = Column(Boolean, default=True, nullable=False)

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


class MessageDeliveryStatus(Base):
    """Track WhatsApp message delivery status"""
    __tablename__ = "message_delivery_status"
    
    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(String(255), unique=True, index=True, nullable=False)  # WhatsApp message ID
    recipient_phone = Column(String(20), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)
    
    # Message details
    message_type = Column(String(50), nullable=True)  # text, interactive, etc.
    message_content = Column(Text, nullable=True)
    
    # Status tracking
    sent_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    delivered_at = Column(DateTime, nullable=True)
    read_at = Column(DateTime, nullable=True)
    failed_at = Column(DateTime, nullable=True)
    
    # Current status
    current_status = Column(String(20), default="sent", nullable=False)  # sent, delivered, read, failed
    
    # Error details if failed
    error_code = Column(String(50), nullable=True)
    error_message = Column(Text, nullable=True)
    
    # Relationships
    customer = relationship("Customer", backref="message_statuses")
    order = relationship("Order", backref="message_statuses")

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
    order_items = relationship("OrderItem", back_populates="order")

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


class Product(Base, TimestampMixin):
    """
    Universal product model that adapts to any business type
    """
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False, index=True)
    
    # Basic product information
    name = Column(String(200), nullable=False, index=True)
    description = Column(Text, nullable=True)
    sku = Column(String(100), nullable=True, index=True)  # Stock Keeping Unit
    barcode = Column(String(100), nullable=True, index=True)
    
    # Categorization
    category = Column(Enum(ProductCategory), nullable=True)
    subcategory = Column(String(100), nullable=True)
    tags = Column(JsonGettable, nullable=True)  # Flexible tagging system
    
    # Pricing
    base_price = Column(Float, nullable=False, default=0.0)
    sale_price = Column(Float, nullable=True)  # Optional discounted price
    cost_price = Column(Float, nullable=True)  # For margin calculation
    currency = Column(String(3), default="KSH", nullable=False)
    
    # Inventory
    stock_quantity = Column(Integer, default=0, nullable=False)
    low_stock_threshold = Column(Integer, default=5, nullable=False)
    track_inventory = Column(Boolean, default=True, nullable=False)
    
    # Product variants (sizes, colors, etc.)
    has_variants = Column(Boolean, default=False, nullable=False)
    variant_options = Column(JsonGettable, nullable=True)  # e.g., {"sizes": ["S","M","L"], "colors": ["red","blue"]}
    
    # Media
    images = Column(JsonGettable, nullable=True)  # Array of image URLs
    video_url = Column(String(500), nullable=True)
    
    # Business-specific attributes
    attributes = Column(JsonGettable, nullable=True)  # Flexible attributes for different business types
    
    # Availability
    is_active = Column(Boolean, default=True, nullable=False)
    is_featured = Column(Boolean, default=False, nullable=False)
    availability_status = Column(String(50), default="available", nullable=False)  # available, out_of_stock, discontinued
    
    # SEO and searchability
    search_keywords = Column(Text, nullable=True)
    
    # Relationships
    group = relationship("Group", backref="products")
    inventory_logs = relationship("InventoryLog", back_populates="product")
    order_items = relationship("OrderItem", back_populates="product")
    reviews = relationship("ProductReview", back_populates="product")

    def get_current_price(self):
        """Get the current selling price (sale price if available, otherwise base price)"""
        return self.sale_price if self.sale_price and self.sale_price > 0 else self.base_price
    
    def is_in_stock(self):
        """Check if product is in stock"""
        if not self.track_inventory:
            return self.availability_status == "available"
        return self.stock_quantity > 0 and self.availability_status == "available"
    
    def is_low_stock(self):
        """Check if product is running low on stock"""
        if not self.track_inventory:
            return False
        return self.stock_quantity <= self.low_stock_threshold


class ProductVariant(Base, TimestampMixin):
    """
    Product variants for products with different options (size, color, etc.)
    """
    __tablename__ = "product_variants"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    
    # Variant identification
    sku = Column(String(100), nullable=True, index=True)
    variant_name = Column(String(200), nullable=False)  # e.g., "Large Red T-Shirt"
    variant_options = Column(JsonGettable, nullable=False)  # e.g., {"size": "L", "color": "red"}
    
    # Pricing (can override product base price)
    price_adjustment = Column(Float, default=0.0, nullable=False)  # +/- from base price
    
    # Inventory
    stock_quantity = Column(Integer, default=0, nullable=False)
    
    # Availability
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Relationships
    product = relationship("Product", backref="variants")


class InventoryLog(Base, TimestampMixin):
    """
    Track inventory changes for audit and analytics
    """
    __tablename__ = "inventory_logs"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    variant_id = Column(Integer, ForeignKey("product_variants.id"), nullable=True, index=True)
    
    # Change information
    change_type = Column(String(50), nullable=False)  # stock_in, stock_out, adjustment, sale, return
    quantity_before = Column(Integer, nullable=False)
    quantity_change = Column(Integer, nullable=False)  # Can be negative
    quantity_after = Column(Integer, nullable=False)
    
    # Context
    reason = Column(String(200), nullable=True)  # Reason for change
    reference_id = Column(String(100), nullable=True)  # Order ID, supplier invoice, etc.
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Cost tracking
    unit_cost = Column(Float, nullable=True)
    total_cost = Column(Float, nullable=True)
    
    # Relationships
    product = relationship("Product", back_populates="inventory_logs")
    variant = relationship("ProductVariant", backref="inventory_logs")
    user = relationship("User", backref="inventory_logs")


class OrderItem(Base, TimestampMixin):
    """
    Individual items within an order
    """
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True, index=True)  # Can be null for custom items
    variant_id = Column(Integer, ForeignKey("product_variants.id"), nullable=True, index=True)
    
    # Item details
    product_name = Column(String(200), nullable=False)  # Snapshot at time of order
    product_sku = Column(String(100), nullable=True)
    variant_details = Column(JsonGettable, nullable=True)  # Variant options at time of order
    
    # Quantity and pricing
    quantity = Column(Integer, nullable=False, default=1)
    unit_price = Column(Float, nullable=False)  # Price at time of order
    total_price = Column(Float, nullable=False)  # quantity * unit_price
    
    # Custom modifications
    special_instructions = Column(Text, nullable=True)
    customizations = Column(JsonGettable, nullable=True)  # Store any custom modifications
    
    # Relationships
    order = relationship("Order", back_populates="order_items")
    product = relationship("Product", back_populates="order_items")
    variant = relationship("ProductVariant", backref="order_items")


class ProductReview(Base, TimestampMixin):
    """
    Customer reviews and ratings for products
    """
    __tablename__ = "product_reviews"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True, index=True)  # Link to purchase
    
    # Review content
    rating = Column(Integer, nullable=False)  # 1-5 stars
    title = Column(String(200), nullable=True)
    comment = Column(Text, nullable=True)
    
    # Moderation
    is_verified_purchase = Column(Boolean, default=False, nullable=False)
    is_approved = Column(Boolean, default=True, nullable=False)
    
    # Helpful votes
    helpful_votes = Column(Integer, default=0, nullable=False)
    
    # Relationships
    product = relationship("Product", back_populates="reviews")
    customer = relationship("Customer", backref="reviews")
    order = relationship("Order", backref="reviews")


class CustomerAnalytics(Base, TimestampMixin):
    """
    Store customer behavior analytics for personalization
    """
    __tablename__ = "customer_analytics"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False, index=True)
    
    # Purchase behavior
    total_orders = Column(Integer, default=0, nullable=False)
    total_spent = Column(Float, default=0.0, nullable=False)
    average_order_value = Column(Float, default=0.0, nullable=False)
    last_order_date = Column(DateTime, nullable=True)
    
    # Preferences (ML-derived)
    preferred_categories = Column(JsonGettable, nullable=True)  # Top categories by purchase frequency
    preferred_price_range = Column(JsonGettable, nullable=True)  # {"min": X, "max": Y}
    purchase_frequency = Column(String(50), nullable=True)  # weekly, monthly, occasional
    
    # Interaction patterns
    peak_interaction_times = Column(JsonGettable, nullable=True)  # When customer usually chats
    preferred_communication_style = Column(String(50), nullable=True)  # formal, casual, etc.
    
    # AI-derived insights
    customer_segment = Column(String(50), nullable=True)  # VIP, regular, new, at_risk
    churn_risk_score = Column(Float, nullable=True)  # 0.0 to 1.0
    lifetime_value_prediction = Column(Float, nullable=True)
    
    # Recommendations
    next_purchase_prediction = Column(JsonGettable, nullable=True)
    personalized_offers = Column(JsonGettable, nullable=True)
    
    # Relationships
    customer = relationship("Customer", backref="analytics")
    group = relationship("Group", backref="customer_analytics")


