"""
Enhanced Inventory Models for Diverse African SMEs
Supports multi-UoM, business templates, and AI integration
"""
from datetime import datetime
import enum
from sqlalchemy import Column, Integer, String, Text, DateTime, Float, Boolean, ForeignKey, Enum, JSON
from sqlalchemy.orm import relationship
from app.database import Base
from app.models import TimestampMixin, JsonGettable


class UnitOfMeasure(enum.Enum):
    """Units of measurement for diverse African SME needs"""
    # Count-based
    PIECES = "pcs"
    ITEMS = "items"
    UNITS = "units"
    BOXES = "boxes"
    PACKETS = "packets"
    BOTTLES = "bottles"
    BAGS = "bags"
    SACKS = "sacks"
    
    # Weight-based
    GRAMS = "g"
    KILOGRAMS = "kg"
    TONNES = "tonnes"
    POUNDS = "lbs"
    
    # Volume-based
    MILLILITERS = "ml"
    LITERS = "l"
    GALLONS = "gal"
    
    # Length-based
    MILLIMETERS = "mm"
    CENTIMETERS = "cm"
    METERS = "m"
    KILOMETERS = "km"
    INCHES = "in"
    FEET = "ft"
    YARDS = "yd"
    
    # Area-based
    SQUARE_METERS = "m2"
    SQUARE_FEET = "ft2"
    ACRES = "acres"
    HECTARES = "ha"
    
    # African-specific
    BUNDLES = "bundles"    # For crops like maize
    CRATES = "crates"      # For beverages
    JERRYCANS = "jerrycans" # For liquids
    CARTONS = "cartons"    # For packaged goods


class BusinessTemplate(Base, TimestampMixin):
    """Pre-configured templates for different African SME types"""
    __tablename__ = "business_templates"
    
    id = Column(Integer, primary_key=True)
    business_type = Column(String(50), nullable=False, unique=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    
    # Default configuration
    default_units = Column(JsonGettable)  # Common UoM for this business type
    typical_products = Column(JsonGettable)  # Common product categories
    pricing_structure = Column(JsonGettable)  # Retail, wholesale, bulk pricing
    inventory_settings = Column(JsonGettable)  # Default thresholds, etc.
    
    # African context
    common_suppliers = Column(JsonGettable)  # Local supplier types
    seasonal_factors = Column(JsonGettable)  # Agricultural seasons, etc.
    regulatory_requirements = Column(JsonGettable)  # Health permits, licenses
    
    is_active = Column(Boolean, default=True)


class ProductUnitConversion(Base, TimestampMixin):
    """Multi-UoM support for flexible inventory management"""
    __tablename__ = "product_unit_conversions"
    
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    
    # Base unit (how inventory is stored)
    base_unit = Column(Enum(UnitOfMeasure), nullable=False)
    base_quantity = Column(Float, nullable=False, default=1.0)
    
    # Alternative unit
    alt_unit = Column(Enum(UnitOfMeasure), nullable=False)
    alt_quantity = Column(Float, nullable=False)
    
    # Conversion factor: base_quantity * conversion_factor = alt_quantity
    conversion_factor = Column(Float, nullable=False)
    
    # Context
    usage_context = Column(String(50))  # purchase, sale, production, storage
    is_default = Column(Boolean, default=False)
    
    # Relationships
    product = relationship("Product", backref="unit_conversions")
    
    def convert_to_base(self, quantity: float) -> float:
        """Convert from alternative unit to base unit"""
        return quantity / self.conversion_factor
    
    def convert_from_base(self, base_qty: float) -> float:
        """Convert from base unit to alternative unit"""
        return base_qty * self.conversion_factor


class InventoryLocation(Base, TimestampMixin):
    """Multiple storage locations for larger SMEs"""
    __tablename__ = "inventory_locations"
    
    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False)
    
    name = Column(String(100), nullable=False)
    location_type = Column(String(50))  # warehouse, shop, storage, farm
    address = Column(Text)
    
    # Capacity and characteristics
    max_capacity = Column(Float)
    capacity_unit = Column(Enum(UnitOfMeasure))
    storage_conditions = Column(JsonGettable)  # temperature, humidity, etc.
    
    # Contact and management
    manager_name = Column(String(100))
    manager_phone = Column(String(20))
    
    is_active = Column(Boolean, default=True)
    
    # Relationships
    group = relationship("Group", backref="inventory_locations")


class ProductStock(Base, TimestampMixin):
    """Enhanced stock tracking with multi-location and multi-UoM support"""
    __tablename__ = "product_stocks"
    
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    location_id = Column(Integer, ForeignKey("inventory_locations.id"), nullable=False)
    variant_id = Column(Integer, ForeignKey("product_variants.id"), nullable=True)
    
    # Stock levels in base unit
    current_stock = Column(Float, nullable=False, default=0.0)
    reserved_stock = Column(Float, nullable=False, default=0.0)  # For pending orders
    available_stock = Column(Float, nullable=False, default=0.0)  # current - reserved
    
    # Thresholds
    min_stock_level = Column(Float, nullable=False, default=0.0)
    max_stock_level = Column(Float, nullable=True)
    reorder_point = Column(Float, nullable=False, default=5.0)
    
    # Cost tracking
    average_cost = Column(Float, nullable=True)  # Weighted average cost
    last_purchase_cost = Column(Float, nullable=True)
    
    # Expiry tracking (for pharmaceuticals, food, etc.)
    expiry_date = Column(DateTime, nullable=True)
    batch_number = Column(String(50), nullable=True)
    
    # Relationships
    product = relationship("Product", backref="stock_records")
    location = relationship("InventoryLocation", backref="stock_records")
    variant = relationship("ProductVariant", backref="stock_records")
    
    def update_available_stock(self):
        """Update available stock calculation"""
        self.available_stock = max(0, self.current_stock - self.reserved_stock)
    
    def is_low_stock(self) -> bool:
        """Check if stock is below reorder point"""
        return self.available_stock <= self.reorder_point
    
    def is_out_of_stock(self) -> bool:
        """Check if completely out of stock"""
        return self.available_stock <= 0


class SupplierInfo(Base, TimestampMixin):
    """Local supplier network for African SMEs"""
    __tablename__ = "suppliers"
    
    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False)
    
    # Basic info
    name = Column(String(200), nullable=False)
    contact_person = Column(String(100))
    phone = Column(String(20))
    email = Column(String(100))
    address = Column(Text)
    
    # Business details
    supplier_type = Column(String(100))  # manufacturer, distributor, farmer, etc.
    products_category = Column(JsonGettable)  # What they supply
    payment_terms = Column(String(200))  # 30 days credit, cash on delivery, etc.
    
    # African context
    location_region = Column(String(100))  # For logistics planning
    minimum_order = Column(Float)
    minimum_order_unit = Column(Enum(UnitOfMeasure))
    delivery_days = Column(Integer, default=7)
    
    # Quality and reliability
    rating = Column(Float, default=0.0)  # 0-5 rating
    notes = Column(Text)
    
    is_active = Column(Boolean, default=True)
    
    # Relationships
    group = relationship("Group", backref="suppliers")


class PricingTier(Base, TimestampMixin):
    """Flexible pricing for African trade relationships"""
    __tablename__ = "pricing_tiers"
    
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    
    # Tier definition
    tier_name = Column(String(50), nullable=False)  # retail, wholesale, bulk
    min_quantity = Column(Float, nullable=False, default=1.0)
    max_quantity = Column(Float, nullable=True)
    
    # Pricing
    unit_price = Column(Float, nullable=False)
    pricing_unit = Column(Enum(UnitOfMeasure), nullable=False)
    
    # Discounts
    discount_percentage = Column(Float, default=0.0)
    
    is_active = Column(Boolean, default=True)
    
    # Relationships
    product = relationship("Product", backref="pricing_tiers")


class AIInventoryInsight(Base, TimestampMixin):
    """Store AI-generated insights for inventory optimization"""
    __tablename__ = "ai_inventory_insights"
    
    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    
    # Insight details
    insight_type = Column(String(50))  # reorder_suggestion, price_optimization, etc.
    insight_data = Column(JsonGettable)  # AI analysis results
    confidence_score = Column(Float)  # 0-1 confidence in the insight
    
    # Status
    status = Column(String(20), default="pending")  # pending, applied, rejected
    applied_at = Column(DateTime, nullable=True)
    applied_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Relationships
    group = relationship("Group", backref="ai_insights")
    product = relationship("Product", backref="ai_insights")