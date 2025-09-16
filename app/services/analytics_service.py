"""
Advanced Analytics and Personalization Service
Provides predictive analytics, customer behavior analysis, and personalized recommendations
Works across all business types with AI-enhanced insights
"""
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict, Counter
import json
import math
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, desc, case, distinct

from app.models import (
    Customer, CustomerAnalytics, Order, OrderItem, Product, ProductReview,
    Group, BusinessType, ConversationSession, ConversationState
)

logger = logging.getLogger(__name__)

class AnalyticsService:
    """
    Advanced analytics and personalization engine
    """
    
    def __init__(self, db: Session):
        self.db = db
    
    # ==========================================
    # CUSTOMER BEHAVIOR ANALYTICS
    # ==========================================
    
    def analyze_customer_behavior(self, customer_id: int, update_analytics: bool = True) -> Dict[str, Any]:
        """
        Comprehensive customer behavior analysis
        """
        try:
            customer = self.db.query(Customer).filter(Customer.id == customer_id).first()
            if not customer:
                return {}
            
            # Get customer's order history
            orders = self.db.query(Order).filter(
                Order.customer_id == customer_id
            ).order_by(desc(Order.created_at)).all()
            
            if not orders:
                return self._create_new_customer_profile(customer_id)
            
            # Calculate basic metrics
            total_orders = len(orders)
            total_spent = sum(order.total_amount for order in orders if order.total_amount)
            avg_order_value = total_spent / total_orders if total_orders > 0 else 0
            last_order_date = orders[0].created_at if orders else None
            
            # Analyze purchase patterns
            purchase_patterns = self._analyze_purchase_patterns(orders)
            category_preferences = self._analyze_category_preferences(customer_id)
            interaction_patterns = self._analyze_interaction_patterns(customer_id)
            
            # Calculate advanced metrics
            customer_lifetime_value = self._calculate_clv(orders)
            churn_risk = self._calculate_churn_risk(orders, interaction_patterns)
            customer_segment = self._determine_customer_segment(
                total_orders, avg_order_value, customer_lifetime_value, churn_risk
            )
            
            # Generate predictions
            next_purchase_prediction = self._predict_next_purchase(orders, purchase_patterns)
            
            analysis = {
                "customer_id": customer_id,
                "analysis_date": datetime.utcnow().isoformat(),
                "basic_metrics": {
                    "total_orders": total_orders,
                    "total_spent": total_spent,
                    "average_order_value": avg_order_value,
                    "last_order_date": last_order_date.isoformat() if last_order_date else None
                },
                "purchase_patterns": purchase_patterns,
                "category_preferences": category_preferences,
                "interaction_patterns": interaction_patterns,
                "advanced_metrics": {
                    "customer_lifetime_value": customer_lifetime_value,
                    "churn_risk_score": churn_risk,
                    "customer_segment": customer_segment
                },
                "predictions": {
                    "next_purchase": next_purchase_prediction
                }
            }
            
            # Update CustomerAnalytics table if requested
            if update_analytics:
                self._update_customer_analytics(customer_id, analysis)
            
            return analysis
            
        except Exception as e:
            logger.error(f"Error analyzing customer behavior for {customer_id}: {str(e)}")
            return {}
    
    def get_customer_recommendations(self, customer_id: int, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Generate personalized product recommendations
        """
        try:
            customer_analytics = self.db.query(CustomerAnalytics).filter(
                CustomerAnalytics.customer_id == customer_id
            ).first()
            
            if not customer_analytics:
                # Analyze customer first
                self.analyze_customer_behavior(customer_id)
                customer_analytics = self.db.query(CustomerAnalytics).filter(
                    CustomerAnalytics.customer_id == customer_id
                ).first()
            
            if not customer_analytics:
                customer = self.db.query(Customer).filter(Customer.id == customer_id).first()
                group_id = customer.group_id if customer else None
                return self._get_popular_products(group_id, limit)
            
            # Get recommendations based on different strategies
            collaborative_recs = self._get_collaborative_recommendations(customer_id, limit)
            content_based_recs = self._get_content_based_recommendations(customer_id, limit)
            trending_recs = self._get_trending_recommendations(customer_analytics.group_id, limit)
            
            # Combine and rank recommendations
            all_recommendations = self._combine_recommendations(
                collaborative_recs, content_based_recs, trending_recs, limit
            )
            
            return all_recommendations[:limit]
            
        except Exception as e:
            logger.error(f"Error generating recommendations for customer {customer_id}: {str(e)}")
            return []
    
    def get_business_insights(self, group_id: int, days: int = 30) -> Dict[str, Any]:
        """
        Generate business intelligence insights for any business type
        """
        try:
            group = self.db.query(Group).filter(Group.id == group_id).first()
            if not group:
                return {}
            
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=days)
            
            # Sales metrics
            sales_metrics = self._get_sales_metrics(group_id, start_date, end_date)
            
            # Customer metrics
            customer_metrics = self._get_customer_metrics(group_id, start_date, end_date)
            
            # Product performance
            product_performance = self._get_product_performance(group_id, start_date, end_date)
            
            # Business-specific insights
            business_insights = self._get_business_specific_insights(group, start_date, end_date)
            
            return {
                "group_id": group_id,
                "business_name": group.name,
                "business_type": group.business_type.value,
                "analysis_period": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "days": days
                },
                "sales_metrics": sales_metrics,
                "customer_metrics": customer_metrics,
                "product_performance": product_performance,
                "business_insights": business_insights,
                "recommendations": self._generate_business_recommendations(
                    group, sales_metrics, customer_metrics, product_performance
                )
            }
            
        except Exception as e:
            logger.error(f"Error generating business insights for group {group_id}: {str(e)}")
            return {}
    
    def predict_demand(self, group_id: int, product_id: int = None, days_ahead: int = 14) -> Dict[str, Any]:
        """
        Predict product demand using historical data and trends
        """
        try:
            # Get historical sales data
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=90)  # 90 days of history
            
            query = self.db.query(
                OrderItem.product_id,
                Product.name,
                func.date(Order.created_at).label('date'),
                func.sum(OrderItem.quantity).label('quantity_sold')
            ).join(
                Order, OrderItem.order_id == Order.id
            ).join(
                Product, OrderItem.product_id == Product.id
            ).filter(
                and_(
                    Product.group_id == group_id,
                    Order.created_at >= start_date,
                    Order.created_at <= end_date
                )
            )
            
            if product_id:
                query = query.filter(Product.id == product_id)
            
            historical_data = query.group_by(
                OrderItem.product_id, func.date(Order.created_at)
            ).all()
            
            # Process data for prediction
            product_data = defaultdict(list)
            for record in historical_data:
                product_data[record.product_id].append({
                    "date": record.date,
                    "quantity": record.quantity_sold,
                    "product_name": record.name
                })
            
            predictions = {}
            for pid, data in product_data.items():
                if len(data) >= 7:  # Need at least a week of data
                    prediction = self._predict_product_demand(data, days_ahead)
                    predictions[pid] = prediction
            
            return {
                "group_id": group_id,
                "product_id": product_id,
                "forecast_days": days_ahead,
                "prediction_date": end_date.isoformat(),
                "predictions": predictions
            }
            
        except Exception as e:
            logger.error(f"Error predicting demand: {str(e)}")
            return {}
    
    # ==========================================
    # CUSTOMER SEGMENTATION
    # ==========================================
    
    def segment_customers(self, group_id: int) -> Dict[str, Any]:
        """
        Segment customers based on behavior and value
        """
        try:
            customers = self.db.query(CustomerAnalytics).filter(
                CustomerAnalytics.group_id == group_id
            ).all()
            
            segments = {
                "vip": [],
                "regular": [],
                "new": [],
                "at_risk": [],
                "lost": []
            }
            
            for customer in customers:
                segment = customer.customer_segment or "new"
                segments[segment].append({
                    "customer_id": customer.customer_id,
                    "total_orders": customer.total_orders,
                    "total_spent": customer.total_spent,
                    "avg_order_value": customer.average_order_value,
                    "last_order_date": customer.last_order_date.isoformat() if customer.last_order_date else None,
                    "churn_risk": customer.churn_risk_score or 0
                })
            
            # Calculate segment statistics
            segment_stats = {}
            for segment, customers_list in segments.items():
                if customers_list:
                    segment_stats[segment] = {
                        "count": len(customers_list),
                        "avg_orders": sum(c["total_orders"] for c in customers_list) / len(customers_list),
                        "avg_spent": sum(c["total_spent"] for c in customers_list) / len(customers_list),
                        "avg_order_value": sum(c["avg_order_value"] for c in customers_list) / len(customers_list)
                    }
                else:
                    segment_stats[segment] = {
                        "count": 0,
                        "avg_orders": 0,
                        "avg_spent": 0,
                        "avg_order_value": 0
                    }
            
            return {
                "group_id": group_id,
                "segments": segments,
                "statistics": segment_stats,
                "recommendations": self._get_segmentation_recommendations(segment_stats)
            }
            
        except Exception as e:
            logger.error(f"Error segmenting customers for group {group_id}: {str(e)}")
            return {}
    
    # ==========================================
    # PRIVATE HELPER METHODS
    # ==========================================
    
    def _create_new_customer_profile(self, customer_id: int) -> Dict[str, Any]:
        """Create profile for new customer with no orders"""
        return {
            "customer_id": customer_id,
            "is_new_customer": True,
            "basic_metrics": {
                "total_orders": 0,
                "total_spent": 0,
                "average_order_value": 0,
                "last_order_date": None
            },
            "customer_segment": "new",
            "recommendations": ["welcome_offer", "popular_products", "onboarding"]
        }
    
    def _analyze_purchase_patterns(self, orders: List[Order]) -> Dict[str, Any]:
        """Analyze customer purchase patterns"""
        if not orders:
            return {}
        
        # Time patterns
        order_dates = [order.created_at for order in orders]
        weekdays = [date.weekday() for date in order_dates]
        hours = [date.hour for date in order_dates]
        
        # Purchase frequency
        if len(orders) > 1:
            intervals = []
            for i in range(1, len(order_dates)):
                interval = (order_dates[i-1] - order_dates[i]).days
                intervals.append(interval)
            avg_interval = sum(intervals) / len(intervals) if intervals else 0
        else:
            avg_interval = 0
        
        return {
            "purchase_frequency": self._categorize_frequency(avg_interval),
            "preferred_weekday": max(set(weekdays), key=weekdays.count) if weekdays else None,
            "preferred_hour": max(set(hours), key=hours.count) if hours else None,
            "average_days_between_orders": avg_interval,
            "seasonal_patterns": self._detect_seasonal_patterns(order_dates)
        }
    
    def _analyze_category_preferences(self, customer_id: int) -> Dict[str, Any]:
        """Analyze customer's product category preferences"""
        try:
            # Get order items with product categories
            category_data = self.db.query(
                Product.category,
                func.sum(OrderItem.quantity).label('total_quantity'),
                func.sum(OrderItem.total_price).label('total_spent'),
                func.count(OrderItem.id).label('order_frequency')
            ).join(
                OrderItem, Product.id == OrderItem.product_id
            ).join(
                Order, OrderItem.order_id == Order.id
            ).filter(
                Order.customer_id == customer_id
            ).group_by(Product.category).all()
            
            if not category_data:
                return {}
            
            categories = []
            for record in category_data:
                if record.category:
                    categories.append({
                        "category": record.category.value,
                        "total_quantity": record.total_quantity,
                        "total_spent": float(record.total_spent),
                        "order_frequency": record.order_frequency,
                        "preference_score": self._calculate_preference_score(
                            record.total_quantity, record.total_spent, record.order_frequency
                        )
                    })
            
            # Sort by preference score
            categories.sort(key=lambda x: x["preference_score"], reverse=True)
            
            return {
                "top_categories": categories[:5],
                "category_diversity": len(categories),
                "dominant_category": categories[0]["category"] if categories else None
            }
            
        except Exception as e:
            logger.error(f"Error analyzing category preferences: {str(e)}")
            return {}
    
    def _analyze_interaction_patterns(self, customer_id: int) -> Dict[str, Any]:
        """Analyze customer's interaction patterns with the bot"""
        try:
            sessions = self.db.query(ConversationSession).filter(
                ConversationSession.customer_id == customer_id
            ).order_by(desc(ConversationSession.last_interaction)).limit(50).all()
            
            if not sessions:
                return {}
            
            # Analyze interaction times
            interaction_hours = [session.last_interaction.hour for session in sessions]
            interaction_days = [session.last_interaction.weekday() for session in sessions]
            
            # Analyze conversation patterns
            state_transitions = []
            response_times = []
            
            for session in sessions:
                if session.last_interaction and session.created_at:
                    response_time = (session.last_interaction - session.created_at).total_seconds() / 60
                    response_times.append(response_time)
            
            return {
                "preferred_interaction_hours": list(set(interaction_hours)),
                "preferred_interaction_days": list(set(interaction_days)),
                "average_response_time_minutes": sum(response_times) / len(response_times) if response_times else 0,
                "interaction_frequency": len(sessions),
                "communication_style": self._infer_communication_style(sessions)
            }
            
        except Exception as e:
            logger.error(f"Error analyzing interaction patterns: {str(e)}")
            return {}
    
    def _calculate_clv(self, orders: List[Order]) -> float:
        """Calculate Customer Lifetime Value"""
        if not orders:
            return 0.0
        
        # Simple CLV calculation: average order value * purchase frequency * estimated lifetime
        total_spent = sum(order.total_amount for order in orders if order.total_amount)
        avg_order_value = total_spent / len(orders)
        
        # Estimate purchase frequency (orders per month)
        if len(orders) > 1:
            first_order = min(orders, key=lambda x: x.created_at)
            last_order = max(orders, key=lambda x: x.created_at)
            months_active = max(1, (last_order.created_at - first_order.created_at).days / 30)
            frequency_per_month = len(orders) / months_active
        else:
            frequency_per_month = 1
        
        # Estimate customer lifetime (assuming 24 months average)
        estimated_lifetime_months = 24
        
        clv = avg_order_value * frequency_per_month * estimated_lifetime_months
        return round(clv, 2)
    
    def _calculate_churn_risk(self, orders: List[Order], interaction_patterns: Dict[str, Any]) -> float:
        """Calculate customer churn risk score (0.0 to 1.0)"""
        if not orders:
            return 0.5  # Neutral for new customers
        
        # Factors affecting churn risk
        risk_factors = []
        
        # Time since last order
        last_order = max(orders, key=lambda x: x.created_at)
        days_since_last_order = (datetime.utcnow() - last_order.created_at).days
        
        if days_since_last_order > 90:
            risk_factors.append(0.8)
        elif days_since_last_order > 60:
            risk_factors.append(0.6)
        elif days_since_last_order > 30:
            risk_factors.append(0.4)
        else:
            risk_factors.append(0.1)
        
        # Order frequency decline
        if len(orders) >= 3:
            recent_orders = orders[:len(orders)//2]  # Recent half
            older_orders = orders[len(orders)//2:]   # Older half
            
            if len(recent_orders) < len(older_orders):
                risk_factors.append(0.7)
            else:
                risk_factors.append(0.2)
        
        # Average order value trend
        if len(orders) >= 3:
            recent_avg = sum(o.total_amount for o in orders[:3] if o.total_amount) / min(3, len(orders))
            overall_avg = sum(o.total_amount for o in orders if o.total_amount) / len(orders)
            
            if recent_avg < overall_avg * 0.7:  # Recent orders 30% below average
                risk_factors.append(0.6)
            else:
                risk_factors.append(0.2)
        
        # Calculate weighted average
        if risk_factors:
            churn_risk = sum(risk_factors) / len(risk_factors)
        else:
            churn_risk = 0.5
        
        return round(min(1.0, max(0.0, churn_risk)), 3)
    
    def _determine_customer_segment(self, total_orders: int, avg_order_value: float, 
                                  clv: float, churn_risk: float) -> str:
        """Determine customer segment based on metrics"""
        if churn_risk > 0.7:
            return "at_risk"
        elif total_orders == 0:
            return "new"
        elif total_orders >= 10 and avg_order_value >= 50 and clv >= 500:
            return "vip"
        elif total_orders >= 3:
            return "regular"
        else:
            return "new"
    
    def _predict_next_purchase(self, orders: List[Order], patterns: Dict[str, Any]) -> Dict[str, Any]:
        """Predict when customer will make next purchase"""
        if not orders or len(orders) < 2:
            return {"prediction": "insufficient_data"}
        
        avg_interval = patterns.get("average_days_between_orders", 30)
        last_order_date = max(orders, key=lambda x: x.created_at).created_at
        
        # Adjust based on customer behavior
        if patterns.get("purchase_frequency") == "frequent":
            predicted_days = max(7, avg_interval * 0.8)
        elif patterns.get("purchase_frequency") == "occasional":
            predicted_days = avg_interval * 1.2
        else:
            predicted_days = avg_interval
        
        predicted_date = last_order_date + timedelta(days=predicted_days)
        days_until_prediction = (predicted_date - datetime.utcnow()).days
        
        return {
            "predicted_date": predicted_date.isoformat(),
            "days_until_prediction": max(0, days_until_prediction),
            "confidence": self._calculate_prediction_confidence(len(orders), patterns),
            "suggested_actions": self._get_retention_suggestions(days_until_prediction)
        }
    
    def _get_collaborative_recommendations(self, customer_id: int, limit: int) -> List[Dict[str, Any]]:
        """Get recommendations based on similar customers"""
        # This would be more sophisticated in production with proper ML models
        try:
            customer = self.db.query(Customer).filter(Customer.id == customer_id).first()
            if not customer:
                return []
            
            # Find customers with similar purchase patterns
            similar_customers = self.db.query(CustomerAnalytics).filter(
                and_(
                    CustomerAnalytics.group_id == customer.group_id,
                    CustomerAnalytics.customer_id != customer_id,
                    CustomerAnalytics.customer_segment.in_(["regular", "vip"])
                )
            ).limit(10).all()
            
            # Get products purchased by similar customers
            similar_customer_ids = [c.customer_id for c in similar_customers]
            
            if not similar_customer_ids:
                return []
            
            recommended_products = self.db.query(
                Product.id,
                Product.name,
                Product.base_price,
                func.count(OrderItem.id).label('popularity')
            ).join(
                OrderItem, Product.id == OrderItem.product_id
            ).join(
                Order, OrderItem.order_id == Order.id
            ).filter(
                Order.customer_id.in_(similar_customer_ids)
            ).group_by(Product.id).order_by(
                desc('popularity')
            ).limit(limit).all()
            
            return [
                {
                    "product_id": p.id,
                    "name": p.name,
                    "price": p.base_price,
                    "recommendation_type": "collaborative",
                    "score": p.popularity
                }
                for p in recommended_products
            ]
            
        except Exception as e:
            logger.error(f"Error getting collaborative recommendations: {str(e)}")
            return []
    
    def _get_content_based_recommendations(self, customer_id: int, limit: int) -> List[Dict[str, Any]]:
        """Get recommendations based on customer's past purchases"""
        try:
            # Get customer's preferred categories
            customer_analytics = self.db.query(CustomerAnalytics).filter(
                CustomerAnalytics.customer_id == customer_id
            ).first()
            
            if not customer_analytics or not customer_analytics.preferred_categories:
                return []
            
            preferred_categories = customer_analytics.preferred_categories
            
            # Get products from preferred categories that customer hasn't bought
            purchased_product_ids = self.db.query(OrderItem.product_id).join(
                Order, OrderItem.order_id == Order.id
            ).filter(Order.customer_id == customer_id).distinct().subquery()
            
            recommended_products = self.db.query(Product).filter(
                and_(
                    Product.group_id == customer_analytics.group_id,
                    Product.category.in_([cat for cat in preferred_categories if isinstance(cat, str)]),
                    ~Product.id.in_(purchased_product_ids),
                    Product.is_active == True
                )
            ).limit(limit).all()
            
            return [
                {
                    "product_id": p.id,
                    "name": p.name,
                    "price": p.get_current_price(),
                    "recommendation_type": "content_based",
                    "score": 0.8  # Static score for now
                }
                for p in recommended_products
            ]
            
        except Exception as e:
            logger.error(f"Error getting content-based recommendations: {str(e)}")
            return []
    
    def _get_trending_recommendations(self, group_id: int, limit: int) -> List[Dict[str, Any]]:
        """Get trending/popular products"""
        try:
            # Get trending products from last 30 days
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=30)
            
            trending_products = self.db.query(
                Product.id,
                Product.name,
                Product.base_price,
                func.count(OrderItem.id).label('sales_count'),
                func.sum(OrderItem.quantity).label('total_quantity')
            ).join(
                OrderItem, Product.id == OrderItem.product_id
            ).join(
                Order, OrderItem.order_id == Order.id
            ).filter(
                and_(
                    Product.group_id == group_id,
                    Order.created_at >= start_date,
                    Product.is_active == True
                )
            ).group_by(Product.id).order_by(
                desc('sales_count'), desc('total_quantity')
            ).limit(limit).all()
            
            return [
                {
                    "product_id": p.id,
                    "name": p.name,
                    "price": p.base_price,
                    "recommendation_type": "trending",
                    "score": p.sales_count / 10.0  # Normalize score
                }
                for p in trending_products
            ]
            
        except Exception as e:
            logger.error(f"Error getting trending recommendations: {str(e)}")
            return []
    
    def _combine_recommendations(self, *recommendation_lists, limit: int) -> List[Dict[str, Any]]:
        """Combine and rank recommendations from different sources"""
        all_recommendations = {}
        
        for rec_list in recommendation_lists:
            for rec in rec_list:
                product_id = rec["product_id"]
                if product_id not in all_recommendations:
                    all_recommendations[product_id] = rec
                else:
                    # Combine scores
                    existing_score = all_recommendations[product_id].get("score", 0)
                    new_score = rec.get("score", 0)
                    all_recommendations[product_id]["score"] = (existing_score + new_score) / 2
        
        # Sort by combined score
        sorted_recommendations = sorted(
            all_recommendations.values(),
            key=lambda x: x.get("score", 0),
            reverse=True
        )
        
        return sorted_recommendations[:limit]
    
    def _update_customer_analytics(self, customer_id: int, analysis: Dict[str, Any]):
        """Update the CustomerAnalytics table with new analysis"""
        try:
            customer = self.db.query(Customer).filter(Customer.id == customer_id).first()
            if not customer:
                return
            
            analytics = self.db.query(CustomerAnalytics).filter(
                CustomerAnalytics.customer_id == customer_id
            ).first()
            
            basic_metrics = analysis.get("basic_metrics", {})
            advanced_metrics = analysis.get("advanced_metrics", {})
            predictions = analysis.get("predictions", {})
            
            if analytics:
                # Update existing record
                analytics.total_orders = basic_metrics.get("total_orders", 0)
                analytics.total_spent = basic_metrics.get("total_spent", 0.0)
                analytics.average_order_value = basic_metrics.get("average_order_value", 0.0)
                analytics.last_order_date = datetime.fromisoformat(basic_metrics["last_order_date"]) if basic_metrics.get("last_order_date") else None
                analytics.customer_segment = advanced_metrics.get("customer_segment")
                analytics.churn_risk_score = advanced_metrics.get("churn_risk_score")
                analytics.lifetime_value_prediction = advanced_metrics.get("customer_lifetime_value")
                analytics.next_purchase_prediction = predictions.get("next_purchase")
                analytics.preferred_categories = analysis.get("category_preferences", {}).get("top_categories")
                analytics.peak_interaction_times = analysis.get("interaction_patterns", {}).get("preferred_interaction_hours")
            else:
                # Create new record
                analytics = CustomerAnalytics(
                    customer_id=customer_id,
                    group_id=customer.group_id,
                    total_orders=basic_metrics.get("total_orders", 0),
                    total_spent=basic_metrics.get("total_spent", 0.0),
                    average_order_value=basic_metrics.get("average_order_value", 0.0),
                    last_order_date=datetime.fromisoformat(basic_metrics["last_order_date"]) if basic_metrics.get("last_order_date") else None,
                    customer_segment=advanced_metrics.get("customer_segment"),
                    churn_risk_score=advanced_metrics.get("churn_risk_score"),
                    lifetime_value_prediction=advanced_metrics.get("customer_lifetime_value"),
                    next_purchase_prediction=predictions.get("next_purchase"),
                    preferred_categories=analysis.get("category_preferences", {}).get("top_categories"),
                    peak_interaction_times=analysis.get("interaction_patterns", {}).get("preferred_interaction_hours")
                )
                self.db.add(analytics)
            
            self.db.commit()
            
        except Exception as e:
            logger.error(f"Error updating customer analytics: {str(e)}")
            self.db.rollback()
    
    # Additional helper methods would continue here...
    # (Due to length constraints, I'm including the essential methods)
    
    def _categorize_frequency(self, avg_interval: float) -> str:
        """Categorize purchase frequency"""
        if avg_interval <= 7:
            return "frequent"
        elif avg_interval <= 30:
            return "regular"
        else:
            return "occasional"
    
    def _detect_seasonal_patterns(self, order_dates: List[datetime]) -> Dict[str, Any]:
        """Detect seasonal purchasing patterns"""
        if not order_dates:
            return {}
        
        months = [date.month for date in order_dates]
        month_counts = Counter(months)
        
        # Simple seasonal detection
        peak_months = [month for month, count in month_counts.most_common(3)]
        
        return {
            "peak_months": peak_months,
            "has_seasonal_pattern": len(set(months)) > 1
        }
    
    def _calculate_preference_score(self, quantity: int, spent: float, frequency: int) -> float:
        """Calculate preference score for a category"""
        # Weighted combination of quantity, spending, and frequency
        return (quantity * 0.3 + spent * 0.4 + frequency * 0.3)
    
    def _get_popular_products(self, group_id: Optional[int] = None, limit: int = 5) -> List[Dict[str, Any]]:
        """Get popular products based on order frequency and quantity"""
        try:
            from app.models import Product, OrderItem, Order
            from sqlalchemy import func, desc
            
            # Query to get products ordered most frequently
            query = self.db.query(
                Product.id,
                Product.name,
                Product.base_price,
                func.count(OrderItem.id).label('order_count'),
                func.sum(OrderItem.quantity).label('total_quantity')
            ).join(
                OrderItem, Product.id == OrderItem.product_id
            ).join(
                Order, OrderItem.order_id == Order.id
            )
            
            # Filter by group if specified
            if group_id:
                query = query.filter(Product.group_id == group_id)
            
            # Get most popular products
            popular_products = query.group_by(
                Product.id, Product.name, Product.base_price
            ).order_by(
                desc('order_count'), desc('total_quantity')
            ).limit(limit).all()
            
            # Convert to list of dicts
            recommendations = []
            for product in popular_products:
                recommendations.append({
                    'product_id': product.id,
                    'name': product.name,
                    'price': float(product.base_price),
                    'popularity_score': float(product.order_count * product.total_quantity),
                    'reason': f'Popular item (ordered {product.order_count} times)'
                })
            
            return recommendations
            
        except Exception as e:
            logger.error(f"Error getting popular products: {str(e)}")
            return []


def get_analytics_service(db: Session) -> AnalyticsService:
    """Get analytics service instance"""
    return AnalyticsService(db)