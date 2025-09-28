"""
Cart Recovery Analytics Service
Provides insights and reporting on cart abandonment and recovery performance
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_, case

from app.models import (
    CartSession, CartStatus, CartRecoveryCampaign, RecoveryStatus, 
    AbandonmentReason, AbandonmentAnalytics
)
from app.models import Order, Customer, Group

logger = logging.getLogger(__name__)

class CartRecoveryAnalyticsService:
    """Service for cart recovery analytics and insights"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_abandonment_overview(self, group_id: int, days: int = 30) -> Dict[str, Any]:
        """Get overview of cart abandonment metrics"""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # Total cart sessions
        total_sessions = self.db.query(CartSession).filter(
            CartSession.group_id == group_id,
            CartSession.created_at >= start_date
        ).count()
        
        # Abandoned sessions
        abandoned_sessions = self.db.query(CartSession).filter(
            CartSession.group_id == group_id,
            CartSession.status == CartStatus.ABANDONED,
            CartSession.created_at >= start_date
        ).count()
        
        # Recovered sessions
        recovered_sessions = self.db.query(CartSession).filter(
            CartSession.group_id == group_id,
            CartSession.status == CartStatus.RECOVERED,
            CartSession.created_at >= start_date
        ).count()
        
        # Completed sessions (direct checkout without abandonment)
        completed_sessions = self.db.query(CartSession).filter(
            CartSession.group_id == group_id,
            CartSession.status == CartStatus.COMPLETED,
            CartSession.created_at >= start_date
        ).count()
        
        # Calculate rates
        abandonment_rate = (abandoned_sessions / total_sessions * 100) if total_sessions > 0 else 0
        recovery_rate = (recovered_sessions / abandoned_sessions * 100) if abandoned_sessions > 0 else 0
        completion_rate = (completed_sessions / total_sessions * 100) if total_sessions > 0 else 0
        
        # Revenue metrics
        total_abandoned_value = self.db.query(func.sum(CartSession.estimated_total)).filter(
            CartSession.group_id == group_id,
            CartSession.status == CartStatus.ABANDONED,
            CartSession.created_at >= start_date
        ).scalar() or 0
        
        recovered_value = self.db.query(func.sum(CartSession.estimated_total)).filter(
            CartSession.group_id == group_id,
            CartSession.status == CartStatus.RECOVERED,
            CartSession.created_at >= start_date
        ).scalar() or 0
        
        return {
            "period_days": days,
            "total_cart_sessions": total_sessions,
            "abandoned_sessions": abandoned_sessions,
            "recovered_sessions": recovered_sessions,
            "completed_sessions": completed_sessions,
            "abandonment_rate": round(abandonment_rate, 2),
            "recovery_rate": round(recovery_rate, 2),
            "completion_rate": round(completion_rate, 2),
            "total_abandoned_value": round(total_abandoned_value, 2),
            "recovered_value": round(recovered_value, 2),
            "recovery_revenue_rate": round((recovered_value / total_abandoned_value * 100) if total_abandoned_value > 0 else 0, 2)
        }
    
    def get_abandonment_reasons_breakdown(self, group_id: int, days: int = 30) -> List[Dict[str, Any]]:
        """Get breakdown of abandonment reasons"""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        reason_breakdown = self.db.query(
            CartSession.abandonment_reason,
            func.count(CartSession.id).label('count'),
            func.sum(CartSession.estimated_total).label('total_value')
        ).filter(
            CartSession.group_id == group_id,
            CartSession.status == CartStatus.ABANDONED,
            CartSession.created_at >= start_date
        ).group_by(CartSession.abandonment_reason).all()
        
        total_abandoned = sum(item.count for item in reason_breakdown)
        
        results = []
        for reason, count, total_value in reason_breakdown:
            results.append({
                "reason": reason.value if reason else "unknown",
                "count": count,
                "percentage": round((count / total_abandoned * 100) if total_abandoned > 0 else 0, 2),
                "total_value": round(total_value or 0, 2),
                "avg_cart_value": round((total_value / count) if count > 0 and total_value else 0, 2)
            })
        
        return sorted(results, key=lambda x: x['count'], reverse=True)
    
    def get_recovery_campaign_performance(self, group_id: int, days: int = 30) -> Dict[str, Any]:
        """Get performance metrics for recovery campaigns"""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # Campaign performance by type
        campaign_performance = self.db.query(
            CartRecoveryCampaign.campaign_type,
            func.count(CartRecoveryCampaign.id).label('total_sent'),
            func.sum(case((CartRecoveryCampaign.resulted_in_recovery == True, 1), else_=0)).label('successful'),
            func.sum(case((CartRecoveryCampaign.customer_responded_at.is_not(None), 1), else_=0)).label('responses')
        ).join(CartSession).filter(
            CartSession.group_id == group_id,
            CartRecoveryCampaign.message_sent_at >= start_date
        ).group_by(CartRecoveryCampaign.campaign_type).all()
        
        campaign_stats = []
        total_campaigns = 0
        total_successful = 0
        
        for campaign_type, total_sent, successful, responses in campaign_performance:
            total_campaigns += total_sent
            total_successful += successful or 0
            
            campaign_stats.append({
                "campaign_type": campaign_type,
                "total_sent": total_sent,
                "successful_recoveries": successful or 0,
                "customer_responses": responses or 0,
                "success_rate": round(((successful or 0) / total_sent * 100) if total_sent > 0 else 0, 2),
                "response_rate": round(((responses or 0) / total_sent * 100) if total_sent > 0 else 0, 2)
            })
        
        return {
            "campaign_stats": campaign_stats,
            "overall_success_rate": round((total_successful / total_campaigns * 100) if total_campaigns > 0 else 0, 2),
            "total_campaigns_sent": total_campaigns,
            "total_successful_recoveries": total_successful
        }
    
    def get_time_based_abandonment_patterns(self, group_id: int, days: int = 30) -> Dict[str, Any]:
        """Analyze abandonment patterns by time of day and day of week"""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # Get all abandoned carts with timestamps
        abandoned_carts = self.db.query(CartSession).filter(
            CartSession.group_id == group_id,
            CartSession.status == CartStatus.ABANDONED,
            CartSession.created_at >= start_date
        ).all()
        
        # Analyze by hour of day
        hourly_abandonment = {}
        daily_abandonment = {}
        
        for cart in abandoned_carts:
            hour = cart.abandoned_at.hour if cart.abandoned_at else cart.created_at.hour
            day = cart.abandoned_at.strftime('%A') if cart.abandoned_at else cart.created_at.strftime('%A')
            
            hourly_abandonment[hour] = hourly_abandonment.get(hour, 0) + 1
            daily_abandonment[day] = daily_abandonment.get(day, 0) + 1
        
        return {
            "hourly_pattern": [{"hour": h, "count": hourly_abandonment.get(h, 0)} for h in range(24)],
            "daily_pattern": [{"day": day, "count": daily_abandonment.get(day, 0)} 
                            for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]],
            "peak_abandonment_hour": max(hourly_abandonment.items(), key=lambda x: x[1])[0] if hourly_abandonment else None,
            "peak_abandonment_day": max(daily_abandonment.items(), key=lambda x: x[1])[0] if daily_abandonment else None
        }
    
    def get_customer_segment_analysis(self, group_id: int, days: int = 30) -> List[Dict[str, Any]]:
        """Analyze abandonment by customer segments"""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # Get abandonment data with customer analytics
        segment_data = self.db.query(
            CartSession,
            Customer
        ).join(Customer).filter(
            CartSession.group_id == group_id,
            CartSession.created_at >= start_date
        ).all()
        
        # Group by customer segments (you'll need to implement customer segmentation)
        # For now, we'll use a simple segmentation based on order history
        segments = {
            "new_customers": {"abandoned": 0, "recovered": 0, "total": 0},
            "returning_customers": {"abandoned": 0, "recovered": 0, "total": 0},
            "vip_customers": {"abandoned": 0, "recovered": 0, "total": 0}
        }
        
        for cart_session, customer in segment_data:
            # Simple segmentation logic
            customer_orders = self.db.query(Order).filter(Order.customer_id == customer.id).count()
            
            if customer_orders == 0:
                segment = "new_customers"
            elif customer_orders >= 10:
                segment = "vip_customers"
            else:
                segment = "returning_customers"
            
            segments[segment]["total"] += 1
            if cart_session.status == CartStatus.ABANDONED:
                segments[segment]["abandoned"] += 1
            elif cart_session.status == CartStatus.RECOVERED:
                segments[segment]["recovered"] += 1
        
        # Calculate rates for each segment
        result = []
        for segment_name, data in segments.items():
            abandonment_rate = (data["abandoned"] / data["total"] * 100) if data["total"] > 0 else 0
            recovery_rate = (data["recovered"] / data["abandoned"] * 100) if data["abandoned"] > 0 else 0
            
            result.append({
                "segment": segment_name,
                "total_sessions": data["total"],
                "abandoned_sessions": data["abandoned"],
                "recovered_sessions": data["recovered"],
                "abandonment_rate": round(abandonment_rate, 2),
                "recovery_rate": round(recovery_rate, 2)
            })
        
        return result
    
    def generate_abandonment_report(self, group_id: int, days: int = 30) -> Dict[str, Any]:
        """Generate comprehensive abandonment report"""
        try:
            overview = self.get_abandonment_overview(group_id, days)
            reasons = self.get_abandonment_reasons_breakdown(group_id, days)
            campaigns = self.get_recovery_campaign_performance(group_id, days)
            time_patterns = self.get_time_based_abandonment_patterns(group_id, days)
            segments = self.get_customer_segment_analysis(group_id, days)
            
            # Generate insights and recommendations
            insights = self._generate_insights(overview, reasons, campaigns, time_patterns)
            
            return {
                "report_period": f"Last {days} days",
                "generated_at": datetime.utcnow().isoformat(),
                "overview": overview,
                "abandonment_reasons": reasons,
                "campaign_performance": campaigns,
                "time_patterns": time_patterns,
                "customer_segments": segments,
                "insights_and_recommendations": insights
            }
            
        except Exception as e:
            logger.error(f"Error generating abandonment report: {e}")
            return {"error": "Failed to generate report"}
    
    def _generate_insights(self, overview: Dict, reasons: List, campaigns: Dict, time_patterns: Dict) -> List[str]:
        """Generate AI-powered insights and recommendations"""
        insights = []
        
        # Abandonment rate insights
        if overview["abandonment_rate"] > 70:
            insights.append("🚨 High abandonment rate detected. Consider simplifying the checkout process.")
        elif overview["abandonment_rate"] < 30:
            insights.append("✅ Excellent abandonment rate! Your checkout flow is working well.")
        
        # Recovery rate insights
        if overview["recovery_rate"] < 20:
            insights.append("📈 Low recovery rate. Consider improving recovery message personalization.")
        elif overview["recovery_rate"] > 40:
            insights.append("🎯 Great recovery rate! Your recovery campaigns are effective.")
        
        # Top abandonment reason insights
        if reasons:
            top_reason = reasons[0]
            if top_reason["reason"] == "pricing_concern":
                insights.append("💰 Price sensitivity is the main abandonment driver. Consider offering targeted discounts.")
            elif top_reason["reason"] == "payment_hesitation":
                insights.append("💳 Payment issues causing abandonment. Simplify payment options or add payment security badges.")
        
        # Time pattern insights
        if time_patterns.get("peak_abandonment_hour"):
            peak_hour = time_patterns["peak_abandonment_hour"]
            insights.append(f"⏰ Peak abandonment occurs at {peak_hour}:00. Schedule recovery campaigns 1-2 hours later.")
        
        # Campaign performance insights
        if campaigns["overall_success_rate"] < 15:
            insights.append("📱 Recovery messages need improvement. Test different message formats and timing.")
        
        return insights

def get_cart_recovery_analytics_service(db: Session) -> CartRecoveryAnalyticsService:
    """Get cart recovery analytics service instance"""
    return CartRecoveryAnalyticsService(db)