"""
Smart Inventory Management Service
Handles inventory tracking, low stock alerts, and predictive restocking for any business type
"""
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, desc

from app.models import (
    Product, ProductVariant, InventoryLog, Order, OrderItem, 
    CustomerAnalytics, Group, BusinessType
)

logger = logging.getLogger(__name__)

class InventoryService:
    """
    Smart inventory management that adapts to different business types
    """
    
    def __init__(self, db: Session):
        self.db = db
    
    # ==========================================
    # STOCK MANAGEMENT
    # ==========================================
    
    def update_stock(self, product_id: int, quantity_change: int, 
                    change_type: str, reason: str = None, 
                    reference_id: str = None, user_id: int = None,
                    variant_id: int = None) -> bool:
        """
        Update product stock and log the change
        """
        try:
            if variant_id:
                # Update variant stock
                variant = self.db.query(ProductVariant).filter(
                    ProductVariant.id == variant_id
                ).first()
                if not variant:
                    return False
                    
                quantity_before = variant.stock_quantity
                variant.stock_quantity = max(0, variant.stock_quantity + quantity_change)
                quantity_after = variant.stock_quantity
                
                # Log the change
                log_entry = InventoryLog(
                    product_id=product_id,
                    variant_id=variant_id,
                    change_type=change_type,
                    quantity_before=quantity_before,
                    quantity_change=quantity_change,
                    quantity_after=quantity_after,
                    reason=reason,
                    reference_id=reference_id,
                    user_id=user_id
                )
                
            else:
                # Update main product stock
                product = self.db.query(Product).filter(
                    Product.id == product_id
                ).first()
                if not product:
                    return False
                    
                quantity_before = product.stock_quantity
                product.stock_quantity = max(0, product.stock_quantity + quantity_change)
                quantity_after = product.stock_quantity
                
                # Update availability status
                if product.stock_quantity == 0:
                    product.availability_status = "out_of_stock"
                elif product.stock_quantity > 0 and product.availability_status == "out_of_stock":
                    product.availability_status = "available"
                
                # Log the change
                log_entry = InventoryLog(
                    product_id=product_id,
                    change_type=change_type,
                    quantity_before=quantity_before,
                    quantity_change=quantity_change,
                    quantity_after=quantity_after,
                    reason=reason,
                    reference_id=reference_id,
                    user_id=user_id
                )
            
            self.db.add(log_entry)
            self.db.commit()
            
            # Check for low stock alerts
            self._check_low_stock_alert(product_id, variant_id)
            
            return True
            
        except Exception as e:
            logger.error(f"Error updating stock for product {product_id}: {str(e)}")
            self.db.rollback()
            return False
    
    def process_order_stock_reduction(self, order_id: int) -> bool:
        """
        Reduce stock quantities based on order items
        """
        try:
            order_items = self.db.query(OrderItem).filter(
                OrderItem.order_id == order_id
            ).all()
            
            for item in order_items:
                if item.product_id:  # Only process if linked to actual product
                    self.update_stock(
                        product_id=item.product_id,
                        quantity_change=-item.quantity,
                        change_type="sale",
                        reason="Order fulfillment",
                        reference_id=str(order_id),
                        variant_id=item.variant_id
                    )
            
            return True
            
        except Exception as e:
            logger.error(f"Error processing stock reduction for order {order_id}: {str(e)}")
            return False
    
    def restock_product(self, product_id: int, quantity: int, 
                       unit_cost: float = None, supplier_info: str = None,
                       user_id: int = None, variant_id: int = None) -> bool:
        """
        Add stock for restocking
        """
        return self.update_stock(
            product_id=product_id,
            quantity_change=quantity,
            change_type="stock_in",
            reason=f"Restocking - {supplier_info}" if supplier_info else "Restocking",
            user_id=user_id,
            variant_id=variant_id
        )
    
    # ==========================================
    # INVENTORY ANALYTICS
    # ==========================================
    
    def get_low_stock_products(self, group_id: int) -> List[Dict[str, Any]]:
        """
        Get products that are running low on stock
        """
        try:
            # Main products with low stock
            low_stock_products = self.db.query(Product).filter(
                and_(
                    Product.group_id == group_id,
                    Product.track_inventory == True,
                    Product.stock_quantity <= Product.low_stock_threshold,
                    Product.is_active == True
                )
            ).all()
            
            result = []
            for product in low_stock_products:
                result.append({
                    "product_id": product.id,
                    "name": product.name,
                    "sku": product.sku,
                    "current_stock": product.stock_quantity,
                    "threshold": product.low_stock_threshold,
                    "status": "low_stock" if product.stock_quantity > 0 else "out_of_stock",
                    "variants": []
                })
                
                # Check variants
                if product.has_variants:
                    low_stock_variants = self.db.query(ProductVariant).filter(
                        and_(
                            ProductVariant.product_id == product.id,
                            ProductVariant.stock_quantity <= product.low_stock_threshold,
                            ProductVariant.is_active == True
                        )
                    ).all()
                    
                    for variant in low_stock_variants:
                        result[-1]["variants"].append({
                            "variant_id": variant.id,
                            "name": variant.variant_name,
                            "sku": variant.sku,
                            "current_stock": variant.stock_quantity,
                            "options": variant.variant_options
                        })
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting low stock products for group {group_id}: {str(e)}")
            return []
    
    def get_inventory_turnover_analysis(self, group_id: int, days: int = 30) -> Dict[str, Any]:
        """
        Analyze inventory turnover for the specified period
        """
        try:
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=days)
            
            # Get sales data
            sales_data = self.db.query(
                Product.id,
                Product.name,
                Product.sku,
                func.sum(OrderItem.quantity).label('total_sold'),
                func.avg(Product.stock_quantity).label('avg_stock'),
                func.count(OrderItem.id).label('order_frequency')
            ).join(
                OrderItem, Product.id == OrderItem.product_id
            ).join(
                Order, OrderItem.order_id == Order.id
            ).filter(
                and_(
                    Product.group_id == group_id,
                    Order.created_at >= start_date,
                    Order.created_at <= end_date
                )
            ).group_by(Product.id).all()
            
            result = {
                "period_days": days,
                "analysis_date": end_date.isoformat(),
                "products": []
            }
            
            for item in sales_data:
                if item.avg_stock and item.avg_stock > 0:
                    turnover_rate = item.total_sold / item.avg_stock
                else:
                    turnover_rate = 0
                
                result["products"].append({
                    "product_id": item.id,
                    "name": item.name,
                    "sku": item.sku,
                    "total_sold": item.total_sold,
                    "avg_stock": float(item.avg_stock) if item.avg_stock else 0,
                    "turnover_rate": turnover_rate,
                    "order_frequency": item.order_frequency,
                    "performance": self._categorize_performance(turnover_rate)
                })
            
            return result
            
        except Exception as e:
            logger.error(f"Error analyzing inventory turnover: {str(e)}")
            return {"products": [], "error": str(e)}
    
    def predict_restock_needs(self, group_id: int, forecast_days: int = 14) -> List[Dict[str, Any]]:
        """
        Predict which products will need restocking based on sales velocity
        """
        try:
            # Get sales velocity for the last 30 days
            velocity_period = 30
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=velocity_period)
            
            sales_velocity = self.db.query(
                Product.id,
                Product.name,
                Product.sku,
                Product.stock_quantity,
                Product.low_stock_threshold,
                func.sum(OrderItem.quantity).label('total_sold')
            ).join(
                OrderItem, Product.id == OrderItem.product_id
            ).join(
                Order, OrderItem.order_id == Order.id
            ).filter(
                and_(
                    Product.group_id == group_id,
                    Product.track_inventory == True,
                    Product.is_active == True,
                    Order.created_at >= start_date,
                    Order.created_at <= end_date
                )
            ).group_by(Product.id).all()
            
            predictions = []
            
            for product in sales_velocity:
                if product.total_sold and product.total_sold > 0:
                    # Calculate daily sales velocity
                    daily_velocity = product.total_sold / velocity_period
                    
                    # Predict when stock will hit threshold
                    if daily_velocity > 0:
                        days_until_restock = (product.stock_quantity - product.low_stock_threshold) / daily_velocity
                        
                        if days_until_restock <= forecast_days:
                            # Calculate suggested restock quantity
                            # (forecasted sales + buffer) - current stock
                            forecasted_demand = daily_velocity * forecast_days
                            buffer_stock = daily_velocity * 7  # 1 week buffer
                            suggested_quantity = int(forecasted_demand + buffer_stock - product.stock_quantity)
                            
                            predictions.append({
                                "product_id": product.id,
                                "name": product.name,
                                "sku": product.sku,
                                "current_stock": product.stock_quantity,
                                "daily_velocity": round(daily_velocity, 2),
                                "days_until_restock": max(0, int(days_until_restock)),
                                "suggested_restock_quantity": max(0, suggested_quantity),
                                "priority": self._calculate_restock_priority(days_until_restock, daily_velocity)
                            })
            
            # Sort by priority (most urgent first)
            predictions.sort(key=lambda x: (x["priority"], x["days_until_restock"]))
            
            return predictions
            
        except Exception as e:
            logger.error(f"Error predicting restock needs: {str(e)}")
            return []
    
    def get_product_availability(self, product_id: int, variant_id: int = None) -> Dict[str, Any]:
        """
        Check real-time product availability
        """
        try:
            product = self.db.query(Product).filter(Product.id == product_id).first()
            if not product:
                return {"available": False, "reason": "Product not found"}
            
            if not product.is_active:
                return {"available": False, "reason": "Product discontinued"}
            
            if not product.track_inventory:
                return {
                    "available": product.availability_status == "available",
                    "reason": product.availability_status,
                    "unlimited_stock": True
                }
            
            if variant_id:
                variant = self.db.query(ProductVariant).filter(
                    and_(
                        ProductVariant.id == variant_id,
                        ProductVariant.product_id == product_id
                    )
                ).first()
                
                if not variant or not variant.is_active:
                    return {"available": False, "reason": "Variant not available"}
                
                return {
                    "available": variant.stock_quantity > 0,
                    "stock_quantity": variant.stock_quantity,
                    "reason": "In stock" if variant.stock_quantity > 0 else "Out of stock"
                }
            else:
                return {
                    "available": product.stock_quantity > 0,
                    "stock_quantity": product.stock_quantity,
                    "is_low_stock": product.is_low_stock(),
                    "reason": "In stock" if product.stock_quantity > 0 else "Out of stock"
                }
                
        except Exception as e:
            logger.error(f"Error checking product availability: {str(e)}")
            return {"available": False, "reason": "System error"}
    
    # ==========================================
    # BUSINESS-SPECIFIC ADAPTATIONS
    # ==========================================
    
    def get_business_specific_inventory_insights(self, group_id: int) -> Dict[str, Any]:
        """
        Provide inventory insights tailored to the business type
        """
        try:
            group = self.db.query(Group).filter(Group.id == group_id).first()
            if not group:
                return {}
            
            business_type = group.business_type
            base_insights = {
                "business_type": business_type.value,
                "group_name": group.name
            }
            
            if business_type == BusinessType.RESTAURANT:
                return {**base_insights, **self._get_restaurant_insights(group_id)}
            elif business_type == BusinessType.PHARMACY:
                return {**base_insights, **self._get_pharmacy_insights(group_id)}
            elif business_type == BusinessType.FASHION:
                return {**base_insights, **self._get_fashion_insights(group_id)}
            elif business_type == BusinessType.ELECTRONICS:
                return {**base_insights, **self._get_electronics_insights(group_id)}
            else:
                return {**base_insights, **self._get_general_insights(group_id)}
                
        except Exception as e:
            logger.error(f"Error getting business-specific insights: {str(e)}")
            return {}
    
    # ==========================================
    # PRIVATE HELPER METHODS
    # ==========================================
    
    def _check_low_stock_alert(self, product_id: int, variant_id: int = None):
        """
        Check if low stock alert should be sent
        """
        # This would integrate with notification service
        # For now, just log the alert
        if variant_id:
            variant = self.db.query(ProductVariant).filter(
                ProductVariant.id == variant_id
            ).first()
            if variant and variant.stock_quantity <= variant.product.low_stock_threshold:
                logger.warning(f"Low stock alert: Product {product_id}, Variant {variant_id}")
        else:
            product = self.db.query(Product).filter(Product.id == product_id).first()
            if product and product.is_low_stock():
                logger.warning(f"Low stock alert: Product {product_id}")
    
    def _categorize_performance(self, turnover_rate: float) -> str:
        """Categorize product performance based on turnover rate"""
        if turnover_rate >= 4.0:
            return "high_performer"
        elif turnover_rate >= 2.0:
            return "good_performer"
        elif turnover_rate >= 1.0:
            return "average_performer"
        else:
            return "slow_mover"
    
    def _calculate_restock_priority(self, days_until_restock: float, daily_velocity: float) -> int:
        """Calculate restock priority (1=highest, 5=lowest)"""
        if days_until_restock <= 0:
            return 1  # Critical - already at threshold
        elif days_until_restock <= 3:
            return 2  # High priority
        elif days_until_restock <= 7:
            return 3  # Medium priority
        elif days_until_restock <= 14:
            return 4  # Low priority
        else:
            return 5  # Very low priority
    
    def _get_restaurant_insights(self, group_id: int) -> Dict[str, Any]:
        """Restaurant-specific inventory insights"""
        return {
            "recommendations": [
                "Monitor perishable items closely",
                "Track ingredient usage patterns",
                "Plan for peak dining hours"
            ],
            "key_metrics": ["freshness_alerts", "waste_reduction", "prep_time_optimization"]
        }
    
    def _get_pharmacy_insights(self, group_id: int) -> Dict[str, Any]:
        """Pharmacy-specific inventory insights"""
        return {
            "recommendations": [
                "Monitor expiration dates",
                "Track prescription demand patterns",
                "Maintain emergency stock levels"
            ],
            "key_metrics": ["expiry_management", "prescription_fulfillment", "safety_stock"]
        }
    
    def _get_fashion_insights(self, group_id: int) -> Dict[str, Any]:
        """Fashion-specific inventory insights"""
        return {
            "recommendations": [
                "Track seasonal demand patterns",
                "Monitor size distribution",
                "Plan for fashion trends"
            ],
            "key_metrics": ["seasonal_trends", "size_optimization", "style_performance"]
        }
    
    def _get_electronics_insights(self, group_id: int) -> Dict[str, Any]:
        """Electronics-specific inventory insights"""
        return {
            "recommendations": [
                "Track technology lifecycle",
                "Monitor product warranty periods",
                "Plan for new model releases"
            ],
            "key_metrics": ["product_lifecycle", "warranty_tracking", "tech_trends"]
        }
    
    def _get_general_insights(self, group_id: int) -> Dict[str, Any]:
        """General business inventory insights"""
        return {
            "recommendations": [
                "Monitor sales patterns",
                "Optimize stock levels",
                "Track customer preferences"
            ],
            "key_metrics": ["sales_velocity", "stock_optimization", "demand_forecasting"]
        }


def get_inventory_service(db: Session) -> InventoryService:
    """Get inventory service instance"""
    return InventoryService(db)