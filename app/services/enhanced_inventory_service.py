"""
Enhanced Inventory Service for Diverse African SMEs
Supports multi-UoM, AI integration, and business-specific operations
"""
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, desc, or_

from app.models import Product, Group, BusinessType
from app.models_inventory_enhanced import (
    UnitOfMeasure, BusinessTemplate, ProductUnitConversion, 
    InventoryLocation, ProductStock, SupplierInfo, PricingTier, AIInventoryInsight
)

logger = logging.getLogger(__name__)


class EnhancedInventoryService:
    """
    Advanced inventory management for diverse African SMEs
    """
    
    def __init__(self, db: Session):
        self.db = db
        
    # ==========================================
    # BUSINESS TEMPLATE MANAGEMENT
    # ==========================================
    
    def get_business_template(self, business_type: str) -> Optional[Dict[str, Any]]:
        """Get pre-configured template for business type"""
        try:
            template = self.db.query(BusinessTemplate).filter(
                BusinessTemplate.business_type == business_type,
                BusinessTemplate.is_active == True
            ).first()
            
            if template:
                return {
                    "business_type": template.business_type,
                    "name": template.name,
                    "default_units": template.default_units,
                    "typical_products": template.typical_products,
                    "pricing_structure": template.pricing_structure,
                    "inventory_settings": template.inventory_settings
                }
            return None
            
        except Exception as e:
            logger.error(f"Error getting business template: {str(e)}")
            return None
    
    def setup_business_from_template(self, group_id: int, business_type: str) -> bool:
        """Set up inventory system using business template"""
        try:
            template = self.get_business_template(business_type)
            if not template:
                return False
            
            # Create default inventory location
            default_location = InventoryLocation(
                group_id=group_id,
                name="Main Store/Warehouse",
                location_type="main",
                is_active=True
            )
            self.db.add(default_location)
            
            # If template has typical products, create them
            if template.get("typical_products"):
                self._create_template_products(group_id, template["typical_products"])
            
            self.db.commit()
            return True
            
        except Exception as e:
            logger.error(f"Error setting up business from template: {str(e)}")
            self.db.rollback()
            return False
    
    # ==========================================
    # MULTI-UOM MANAGEMENT
    # ==========================================
    
    def add_unit_conversion(self, product_id: int, base_unit: UnitOfMeasure, 
                          alt_unit: UnitOfMeasure, conversion_factor: float,
                          usage_context: str = "general") -> bool:
        """Add unit conversion for flexible inventory management"""
        try:
            conversion = ProductUnitConversion(
                product_id=product_id,
                base_unit=base_unit,
                base_quantity=1.0,
                alt_unit=alt_unit,
                alt_quantity=conversion_factor,
                conversion_factor=conversion_factor,
                usage_context=usage_context
            )
            
            self.db.add(conversion)
            self.db.commit()
            return True
            
        except Exception as e:
            logger.error(f"Error adding unit conversion: {str(e)}")
            self.db.rollback()
            return False
    
    def convert_quantity(self, product_id: int, quantity: float, 
                        from_unit: UnitOfMeasure, to_unit: UnitOfMeasure) -> Optional[float]:
        """Convert quantity between different units"""
        try:
            if from_unit == to_unit:
                return quantity
            
            # Find conversion
            conversion = self.db.query(ProductUnitConversion).filter(
                ProductUnitConversion.product_id == product_id,
                or_(
                    and_(ProductUnitConversion.base_unit == from_unit, 
                         ProductUnitConversion.alt_unit == to_unit),
                    and_(ProductUnitConversion.base_unit == to_unit, 
                         ProductUnitConversion.alt_unit == from_unit)
                )
            ).first()
            
            if not conversion:
                return None
            
            # Perform conversion
            if conversion.base_unit == from_unit:
                return quantity * conversion.conversion_factor
            else:
                return quantity / conversion.conversion_factor
                
        except Exception as e:
            logger.error(f"Error converting quantity: {str(e)}")
            return None
    
    # ==========================================
    # STOCK MANAGEMENT WITH MULTI-LOCATION
    # ==========================================
    
    def update_stock(self, product_id: int, location_id: int, quantity_change: float,
                    change_type: str, reason: str = None, variant_id: int = None) -> bool:
        """Update stock with multi-location support"""
        try:
            # Get or create stock record
            stock_record = self.db.query(ProductStock).filter(
                ProductStock.product_id == product_id,
                ProductStock.location_id == location_id,
                ProductStock.variant_id == variant_id
            ).first()
            
            if not stock_record:
                stock_record = ProductStock(
                    product_id=product_id,
                    location_id=location_id,
                    variant_id=variant_id,
                    current_stock=0.0
                )
                self.db.add(stock_record)
            
            # Update stock
            old_stock = stock_record.current_stock
            stock_record.current_stock = max(0, stock_record.current_stock + quantity_change)
            stock_record.update_available_stock()
            
            # Log the change
            self._log_inventory_change(
                product_id, location_id, variant_id, change_type,
                old_stock, quantity_change, stock_record.current_stock, reason
            )
            
            self.db.commit()
            
            # Check for low stock alerts
            if stock_record.is_low_stock():
                self._trigger_reorder_alert(stock_record)
            
            return True
            
        except Exception as e:
            logger.error(f"Error updating stock: {str(e)}")
            self.db.rollback()
            return False
    
    def get_total_stock(self, product_id: int, variant_id: int = None) -> float:
        """Get total stock across all locations"""
        try:
            query = self.db.query(func.sum(ProductStock.available_stock)).filter(
                ProductStock.product_id == product_id
            )
            
            if variant_id:
                query = query.filter(ProductStock.variant_id == variant_id)
            
            result = query.scalar()
            return result if result else 0.0
            
        except Exception as e:
            logger.error(f"Error getting total stock: {str(e)}")
            return 0.0
    
    def get_stock_at_location(self, product_id: int, location_id: int, variant_id: int = None) -> float:
        """Get stock for a specific product at a specific location"""
        try:
            query = self.db.query(ProductStock.available_stock).filter(
                ProductStock.product_id == product_id,
                ProductStock.location_id == location_id
            )
            
            if variant_id:
                query = query.filter(ProductStock.variant_id == variant_id)
            
            stock_record = query.first()
            return stock_record.available_stock if stock_record else 0.0
            
        except Exception as e:
            logger.error(f"Error getting stock at location: {str(e)}")
            return 0.0
    
    # ==========================================
    # AI-ACCESSIBLE INVENTORY METHODS
    # ==========================================
    
    def search_products_for_ai(self, group_id: int, search_query: str, 
                              limit: int = 10) -> List[Dict[str, Any]]:
        """AI-friendly product search with availability"""
        try:
            # Fuzzy search across name, description, tags
            from app.utils.sql_security import escape_sql_pattern
            safe_search = escape_sql_pattern(search_query)
            products = self.db.query(Product).filter(
                Product.group_id == group_id,
                Product.is_active == True,
                or_(
                    Product.name.ilike(f"%{safe_search}%", escape='\\'),
                    Product.description.ilike(f"%{safe_search}%", escape='\\'),
                    Product.search_keywords.ilike(f"%{safe_search}%", escape='\\')
                )
            ).limit(limit).all()
            
            results = []
            for product in products:
                total_stock = self.get_total_stock(product.id)
                
                results.append({
                    "id": product.id,
                    "name": product.name,
                    "description": product.description,
                    "price": product.get_current_price(),
                    "currency": product.currency,
                    "category": product.category.value if product.category else None,
                    "in_stock": total_stock > 0,
                    "stock_quantity": total_stock,
                    "is_low_stock": total_stock <= product.low_stock_threshold,
                    "variants": self._get_product_variants_for_ai(product.id)
                })
            
            return results
            
        except Exception as e:
            logger.error(f"Error in AI product search: {str(e)}")
            return []
    
    def get_all_available_products_for_ai(self, group_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """Get all available products for AI - used for general inventory requests"""
        try:
            # Get all active products with stock
            products = self.db.query(Product).filter(
                Product.group_id == group_id,
                Product.is_active == True
            ).limit(limit).all()
            
            results = []
            for product in products:
                total_stock = self.get_total_stock(product.id)
                
                # Only include products that are in stock
                if total_stock > 0:
                    results.append({
                        "id": product.id,
                        "name": product.name,
                        "description": product.description,
                        "price": product.get_current_price(),
                        "currency": product.currency,
                        "category": product.category.value if product.category else None,
                        "in_stock": True,
                        "stock_quantity": total_stock,
                        "is_low_stock": total_stock <= product.low_stock_threshold,
                        "variants": self._get_product_variants_for_ai(product.id)
                    })
            
            return results
        except Exception as e:
            logger.error(f"Error getting all available products for AI: {str(e)}")
            return []
    
    def get_product_availability_for_ai(self, product_id: int, 
                                      requested_quantity: float = 1.0) -> Dict[str, Any]:
        """Get detailed availability info for AI agent"""
        try:
            product = self.db.query(Product).filter(Product.id == product_id).first()
            if not product:
                return {"available": False, "reason": "Product not found"}
            
            total_stock = self.get_total_stock(product_id)
            
            # Get pricing tiers
            pricing_tiers = self.db.query(PricingTier).filter(
                PricingTier.product_id == product_id,
                PricingTier.is_active == True
            ).order_by(PricingTier.min_quantity).all()
            
            # Determine best pricing tier
            applicable_tier = None
            for tier in pricing_tiers:
                if tier.min_quantity <= requested_quantity:
                    applicable_tier = tier
            
            result = {
                "available": total_stock >= requested_quantity,
                "product_name": product.name,
                "total_stock": total_stock,
                "requested_quantity": requested_quantity,
                "base_price": product.get_current_price(),
                "currency": product.currency,
                "is_low_stock": total_stock <= product.low_stock_threshold,
                "pricing_tiers": []
            }
            
            # Add pricing information
            for tier in pricing_tiers:
                result["pricing_tiers"].append({
                    "tier_name": tier.tier_name,
                    "min_quantity": tier.min_quantity,
                    "unit_price": tier.unit_price,
                    "pricing_unit": tier.pricing_unit.value
                })
            
            if applicable_tier:
                result["recommended_price"] = applicable_tier.unit_price
                result["pricing_tier"] = applicable_tier.tier_name
            
            # Add alternatives if not available
            if not result["available"]:
                result["alternatives"] = self._get_alternative_products(product_id)
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting product availability for AI: {str(e)}")
            return {"available": False, "reason": "System error"}
    
    def get_business_inventory_summary_for_ai(self, group_id: int) -> Dict[str, Any]:
        """Get inventory summary for AI insights"""
        try:
            # Get total products
            total_products = self.db.query(Product).filter(
                Product.group_id == group_id,
                Product.is_active == True
            ).count()
            
            # Get low stock items
            low_stock_products = []
            out_of_stock_products = []
            
            products = self.db.query(Product).filter(
                Product.group_id == group_id,
                Product.is_active == True
            ).all()
            
            for product in products:
                total_stock = self.get_total_stock(product.id)
                if total_stock <= 0:
                    out_of_stock_products.append({
                        "id": product.id,
                        "name": product.name,
                        "category": product.category.value if product.category else None
                    })
                elif total_stock <= product.low_stock_threshold:
                    low_stock_products.append({
                        "id": product.id,
                        "name": product.name,
                        "stock": total_stock,
                        "threshold": product.low_stock_threshold
                    })
            
            return {
                "total_products": total_products,
                "low_stock_count": len(low_stock_products),
                "out_of_stock_count": len(out_of_stock_products),
                "low_stock_items": low_stock_products[:5],  # Top 5
                "out_of_stock_items": out_of_stock_products[:5],  # Top 5
                "inventory_health": self._calculate_inventory_health(group_id)
            }
            
        except Exception as e:
            logger.error(f"Error getting inventory summary for AI: {str(e)}")
            return {}
    
    # ==========================================
    # AFRICAN SME SPECIFIC FEATURES
    # ==========================================
    
    def add_supplier(self, group_id: int, supplier_data: Dict[str, Any]) -> bool:
        """Add local supplier to network"""
        try:
            supplier = SupplierInfo(
                group_id=group_id,
                name=supplier_data["name"],
                contact_person=supplier_data.get("contact_person"),
                phone=supplier_data.get("phone"),
                email=supplier_data.get("email"),
                address=supplier_data.get("address"),
                supplier_type=supplier_data.get("supplier_type"),
                products_category=supplier_data.get("products_category"),
                payment_terms=supplier_data.get("payment_terms"),
                location_region=supplier_data.get("location_region"),
                minimum_order=supplier_data.get("minimum_order", 1.0),
                minimum_order_unit=supplier_data.get("minimum_order_unit", UnitOfMeasure.PIECES),
                delivery_days=supplier_data.get("delivery_days", 7)
            )
            
            self.db.add(supplier)
            self.db.commit()
            return True
            
        except Exception as e:
            logger.error(f"Error adding supplier: {str(e)}")
            self.db.rollback()
            return False
    
    def get_reorder_suggestions(self, group_id: int) -> List[Dict[str, Any]]:
        """Generate reorder suggestions for African SMEs"""
        try:
            suggestions = []
            
            # Get all products needing reorder
            products = self.db.query(Product).filter(
                Product.group_id == group_id,
                Product.is_active == True,
                Product.track_inventory == True
            ).all()
            
            for product in products:
                total_stock = self.get_total_stock(product.id)
                
                if total_stock <= product.low_stock_threshold:
                    # Calculate suggested order quantity
                    suggested_qty = self._calculate_reorder_quantity(product.id)
                    
                    # Find best supplier
                    best_supplier = self._find_best_supplier(product.id)
                    
                    suggestions.append({
                        "product_id": product.id,
                        "product_name": product.name,
                        "current_stock": total_stock,
                        "suggested_order_qty": suggested_qty,
                        "priority": "high" if total_stock <= 0 else "medium",
                        "supplier": best_supplier,
                        "estimated_cost": suggested_qty * (product.cost_price or product.base_price)
                    })
            
            # Sort by priority
            suggestions.sort(key=lambda x: (x["priority"] == "high", -x["current_stock"]))
            return suggestions
            
        except Exception as e:
            logger.error(f"Error generating reorder suggestions: {str(e)}")
            return []
    
    # ==========================================
    # PRIVATE HELPER METHODS
    # ==========================================
    
    def _create_template_products(self, group_id: int, typical_products: List[Dict]):
        """Create products from business template"""
        from app.models import ProductCategory
        
        for product_data in typical_products:
            # Convert category string to enum
            category_str = product_data.get("category")
            category_enum = None
            if category_str:
                try:
                    category_enum = ProductCategory(category_str)
                except ValueError:
                    logger.warning(f"Invalid category '{category_str}' for product '{product_data['name']}', using None")
            
            product = Product(
                group_id=group_id,
                name=product_data["name"],
                description=product_data.get("description"),
                category=category_enum,
                base_price=product_data.get("price", 0.0),
                low_stock_threshold=product_data.get("threshold", 5)
            )
            self.db.add(product)
    
    def _get_product_variants_for_ai(self, product_id: int) -> List[Dict[str, Any]]:
        """Get product variants in AI-friendly format"""
        from app.models import ProductVariant
        
        variants = self.db.query(ProductVariant).filter(
            ProductVariant.product_id == product_id,
            ProductVariant.is_active == True
        ).all()
        
        return [
            {
                "id": variant.id,
                "name": variant.variant_name,
                "options": variant.variant_options,
                "stock": self.get_total_stock(product_id, variant.id),
                "price_adjustment": variant.price_adjustment
            }
            for variant in variants
        ]
    
    def _get_alternative_products(self, product_id: int) -> List[Dict[str, Any]]:
        """Find alternative products when requested item is unavailable"""
        product = self.db.query(Product).filter(Product.id == product_id).first()
        if not product:
            return []
        
        # Find products in same category with stock
        alternatives = self.db.query(Product).filter(
            Product.group_id == product.group_id,
            Product.category == product.category,
            Product.is_active == True,
            Product.id != product_id
        ).limit(3).all()
        
        result = []
        for alt in alternatives:
            stock = self.get_total_stock(alt.id)
            if stock > 0:
                result.append({
                    "id": alt.id,
                    "name": alt.name,
                    "price": alt.get_current_price(),
                    "stock": stock
                })
        
        return result
    
    def _calculate_inventory_health(self, group_id: int) -> str:
        """Calculate overall inventory health score"""
        products = self.db.query(Product).filter(
            Product.group_id == group_id,
            Product.is_active == True
        ).all()
        
        if not products:
            return "no_data"
        
        healthy_count = 0
        for product in products:
            stock = self.get_total_stock(product.id)
            if stock > product.low_stock_threshold:
                healthy_count += 1
        
        health_ratio = healthy_count / len(products)
        
        if health_ratio >= 0.8:
            return "excellent"
        elif health_ratio >= 0.6:
            return "good"
        elif health_ratio >= 0.4:
            return "fair"
        else:
            return "poor"
    
    def _calculate_reorder_quantity(self, product_id: int) -> float:
        """Calculate suggested reorder quantity based on historical data"""
        # Simple algorithm - can be enhanced with AI
        product = self.db.query(Product).filter(Product.id == product_id).first()
        if not product:
            return 0.0
        
        # Default to 2x threshold + safety stock
        return max(product.low_stock_threshold * 2, 10.0)
    
    def _find_best_supplier(self, product_id: int) -> Optional[Dict[str, Any]]:
        """Find best supplier for a product"""
        product = self.db.query(Product).filter(Product.id == product_id).first()
        if not product:
            return None
        
        # Find suppliers that might carry this product
        suppliers = self.db.query(SupplierInfo).filter(
            SupplierInfo.group_id == product.group_id,
            SupplierInfo.is_active == True
        ).order_by(desc(SupplierInfo.rating)).limit(1).all()
        
        if suppliers:
            supplier = suppliers[0]
            return {
                "id": supplier.id,
                "name": supplier.name,
                "phone": supplier.phone,
                "delivery_days": supplier.delivery_days,
                "minimum_order": supplier.minimum_order
            }
        
        return None
    
    def _log_inventory_change(self, product_id: int, location_id: int, variant_id: int,
                            change_type: str, old_qty: float, change: float, 
                            new_qty: float, reason: str):
        """Log inventory changes for audit trail"""
        from app.models import InventoryLog
        
        log_entry = InventoryLog(
            product_id=product_id,
            variant_id=variant_id,
            change_type=change_type,
            quantity_before=old_qty,
            quantity_change=change,
            quantity_after=new_qty,
            reason=reason
        )
        
        self.db.add(log_entry)
    
    def _trigger_reorder_alert(self, stock_record: ProductStock):
        """Trigger reorder alert for low stock"""
        logger.warning(f"Low stock alert: Product {stock_record.product_id} "
                      f"at location {stock_record.location_id}")
        # TODO: Integrate with notification system


def get_enhanced_inventory_service(db: Session) -> EnhancedInventoryService:
    """Get enhanced inventory service instance"""
    return EnhancedInventoryService(db)