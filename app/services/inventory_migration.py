"""
Migration and Setup Script for Enhanced Inventory System
Helps integrate the new inventory features with existing data
"""
import logging
from typing import Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.models import Group, Product, BusinessType
from app.models_inventory_enhanced import (
    BusinessTemplate, InventoryLocation, ProductStock, 
    UnitOfMeasure, ProductUnitConversion
)
from app.services.business_templates import create_business_templates, AFRICAN_SME_TEMPLATES

logger = logging.getLogger(__name__)


class InventoryMigrationService:
    """
    Service to migrate existing inventory to enhanced system
    """
    
    def __init__(self, db: Session):
        self.db = db
    
    def run_full_migration(self) -> Dict[str, Any]:
        """
        Complete migration from basic to enhanced inventory system
        """
        try:
            results = {
                "business_templates_created": 0,
                "locations_created": 0,
                "stock_records_migrated": 0,
                "unit_conversions_added": 0,
                "groups_migrated": 0,
                "errors": []
            }
            
            # Step 1: Create business templates
            logger.info("Creating business templates...")
            templates_created = self._create_business_templates()
            results["business_templates_created"] = templates_created
            
            # Step 2: Migrate existing groups
            logger.info("Migrating existing groups...")
            groups_migrated = self._migrate_existing_groups()
            results["groups_migrated"] = groups_migrated
            
            # Step 3: Create default locations for all groups
            logger.info("Creating default inventory locations...")
            locations_created = self._create_default_locations()
            results["locations_created"] = locations_created
            
            # Step 4: Migrate existing product stock data
            logger.info("Migrating product stock data...")
            stock_migrated = self._migrate_product_stock()
            results["stock_records_migrated"] = stock_migrated
            
            # Step 5: Add default unit conversions
            logger.info("Adding default unit conversions...")
            conversions_added = self._add_default_unit_conversions()
            results["unit_conversions_added"] = conversions_added
            
            self.db.commit()
            
            logger.info(f"Migration completed successfully: {results}")
            return results
            
        except Exception as e:
            logger.error(f"Migration failed: {str(e)}")
            self.db.rollback()
            results["errors"].append(str(e))
            return results
    
    def _create_business_templates(self) -> int:
        """Create all business templates"""
        try:
            create_business_templates(self.db)
            return len(AFRICAN_SME_TEMPLATES)
        except Exception as e:
            logger.error(f"Error creating business templates: {str(e)}")
            return 0
    
    def _migrate_existing_groups(self) -> int:
        """Set up existing groups with enhanced inventory features"""
        try:
            groups = self.db.query(Group).all()
            migrated_count = 0
            
            for group in groups:
                try:
                    # Ensure group has a business type
                    if not hasattr(group, 'business_type') or not group.business_type:
                        group.business_type = BusinessType.GENERAL
                    
                    migrated_count += 1
                    
                except Exception as e:
                    logger.error(f"Error migrating group {group.id}: {str(e)}")
            
            return migrated_count
            
        except Exception as e:
            logger.error(f"Error migrating groups: {str(e)}")
            return 0
    
    def _create_default_locations(self) -> int:
        """Create default inventory locations for all groups"""
        try:
            groups = self.db.query(Group).all()
            locations_created = 0
            
            for group in groups:
                # Check if group already has locations
                existing_location = self.db.query(InventoryLocation).filter(
                    InventoryLocation.group_id == group.id
                ).first()
                
                if not existing_location:
                    default_location = InventoryLocation(
                        group_id=group.id,
                        name="Main Store",
                        location_type="main",
                        address=f"{group.name} Main Location",
                        is_active=True
                    )
                    
                    self.db.add(default_location)
                    locations_created += 1
            
            return locations_created
            
        except Exception as e:
            logger.error(f"Error creating default locations: {str(e)}")
            return 0
    
    def _migrate_product_stock(self) -> int:
        """Migrate existing product stock to new ProductStock model"""
        try:
            products = self.db.query(Product).all()
            stock_records_created = 0
            
            for product in products:
                # Get the default location for this product's group
                default_location = self.db.query(InventoryLocation).filter(
                    InventoryLocation.group_id == product.group_id,
                    InventoryLocation.location_type == "main"
                ).first()
                
                if not default_location:
                    continue
                
                # Check if stock record already exists
                existing_stock = self.db.query(ProductStock).filter(
                    ProductStock.product_id == product.id,
                    ProductStock.location_id == default_location.id
                ).first()
                
                if not existing_stock:
                    # Create new stock record from existing product data
                    stock_record = ProductStock(
                        product_id=product.id,
                        location_id=default_location.id,
                        current_stock=float(product.stock_quantity) if product.stock_quantity else 0.0,
                        reserved_stock=0.0,
                        available_stock=float(product.stock_quantity) if product.stock_quantity else 0.0,
                        reorder_point=float(product.low_stock_threshold) if product.low_stock_threshold else 5.0,
                        average_cost=product.cost_price if product.cost_price else product.base_price
                    )
                    
                    self.db.add(stock_record)
                    stock_records_created += 1
            
            return stock_records_created
            
        except Exception as e:
            logger.error(f"Error migrating product stock: {str(e)}")
            return 0
    
    def _add_default_unit_conversions(self) -> int:
        """Add default unit conversions for products based on business type"""
        try:
            conversions_added = 0
            
            # Get all groups with their business types
            groups = self.db.query(Group).all()
            
            for group in groups:
                business_type = group.business_type if hasattr(group, 'business_type') else BusinessType.GENERAL
                
                # Get products for this group
                products = self.db.query(Product).filter(Product.group_id == group.id).all()
                
                for product in products:
                    # Add appropriate conversions based on business type
                    self._add_business_specific_conversions(product, business_type)
                    conversions_added += 1
            
            return conversions_added
            
        except Exception as e:
            logger.error(f"Error adding unit conversions: {str(e)}")
            return 0
    
    def _add_business_specific_conversions(self, product: Product, business_type: BusinessType):
        """Add business-specific unit conversions for a product"""
        try:
            # Common conversions based on business type
            conversions_map = {
                BusinessType.GROCERY: [
                    (UnitOfMeasure.KILOGRAMS, UnitOfMeasure.GRAMS, 1000),
                    (UnitOfMeasure.LITERS, UnitOfMeasure.MILLILITERS, 1000),
                    (UnitOfMeasure.PIECES, UnitOfMeasure.BOXES, 0.1)  # 10 pieces per box
                ],
                BusinessType.RESTAURANT: [
                    (UnitOfMeasure.KILOGRAMS, UnitOfMeasure.GRAMS, 1000),
                    (UnitOfMeasure.LITERS, UnitOfMeasure.MILLILITERS, 1000),
                    (UnitOfMeasure.CRATES, UnitOfMeasure.BOTTLES, 24)  # 24 bottles per crate
                ],
                BusinessType.AGRICULTURE: [
                    (UnitOfMeasure.TONNES, UnitOfMeasure.KILOGRAMS, 1000),
                    (UnitOfMeasure.SACKS, UnitOfMeasure.KILOGRAMS, 50),  # 50kg per sack
                    (UnitOfMeasure.BAGS, UnitOfMeasure.KILOGRAMS, 25)   # 25kg per bag
                ],
                BusinessType.PHARMACY: [
                    (UnitOfMeasure.LITERS, UnitOfMeasure.MILLILITERS, 1000),
                    (UnitOfMeasure.BOXES, UnitOfMeasure.PIECES, 10)  # 10 pieces per box
                ]
            }
            
            # Get conversions for this business type
            conversions = conversions_map.get(business_type, [
                (UnitOfMeasure.PIECES, UnitOfMeasure.BOXES, 0.1)  # Default conversion
            ])
            
            # Add conversions for this product
            for base_unit, alt_unit, factor in conversions:
                existing_conversion = self.db.query(ProductUnitConversion).filter(
                    ProductUnitConversion.product_id == product.id,
                    ProductUnitConversion.base_unit == base_unit,
                    ProductUnitConversion.alt_unit == alt_unit
                ).first()
                
                if not existing_conversion:
                    conversion = ProductUnitConversion(
                        product_id=product.id,
                        base_unit=base_unit,
                        base_quantity=1.0,
                        alt_unit=alt_unit,
                        alt_quantity=factor,
                        conversion_factor=factor,
                        usage_context="general"
                    )
                    
                    self.db.add(conversion)
        
        except Exception as e:
            logger.error(f"Error adding conversions for product {product.id}: {str(e)}")
    
    def setup_new_business(self, group_id: int, business_type: str) -> bool:
        """Set up inventory system for a new business"""
        try:
            from app.services.enhanced_inventory_service import get_enhanced_inventory_service
            
            inventory_service = get_enhanced_inventory_service(self.db)
            
            # Setup from template
            success = inventory_service.setup_business_from_template(group_id, business_type)
            
            if success:
                # Add sample products if template has them
                self._add_sample_products_for_business(group_id, business_type)
            
            return success
            
        except Exception as e:
            logger.error(f"Error setting up new business: {str(e)}")
            return False
    
    def _add_sample_products_for_business(self, group_id: int, business_type: str):
        """Add sample products for demonstration"""
        try:
            template_data = AFRICAN_SME_TEMPLATES.get(business_type)
            if not template_data or not template_data.get("typical_products"):
                return
            
            # Get default location
            location = self.db.query(InventoryLocation).filter(
                InventoryLocation.group_id == group_id,
                InventoryLocation.location_type == "main"
            ).first()
            
            if not location:
                return
            
            # Create sample products
            for product_data in template_data["typical_products"][:3]:  # First 3 only
                product = Product(
                    group_id=group_id,
                    name=f"Sample {product_data['name']}",
                    description=f"Sample product for {business_type} business",
                    base_price=product_data.get("price", 100.0),
                    low_stock_threshold=product_data.get("threshold", 5),
                    is_active=True
                )
                
                self.db.add(product)
                self.db.flush()  # Get product ID
                
                # Create stock record
                stock_record = ProductStock(
                    product_id=product.id,
                    location_id=location.id,
                    current_stock=20.0,  # Sample stock
                    available_stock=20.0,
                    reorder_point=product_data.get("threshold", 5)
                )
                
                self.db.add(stock_record)
        
        except Exception as e:
            logger.error(f"Error adding sample products: {str(e)}")


def run_inventory_migration(db: Session) -> Dict[str, Any]:
    """Main migration function"""
    migration_service = InventoryMigrationService(db)
    return migration_service.run_full_migration()


def setup_business_inventory(db: Session, group_id: int, business_type: str) -> bool:
    """Set up inventory for a new business"""
    migration_service = InventoryMigrationService(db)
    return migration_service.setup_new_business(group_id, business_type)