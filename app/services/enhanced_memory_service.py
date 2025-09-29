"""
Enhanced PostgreSQL-based conversation memory service
Builds on existing ConversationSession model with intelligent caching and context management
"""
import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.models import ConversationSession, Customer, Order, Product
from app.services.cache_service import get_cache_service

logger = logging.getLogger(__name__)

class EnhancedMemoryService:
    """
    Advanced memory management service using PostgreSQL + DiskCache
    Provides multi-layered memory: short-term, session, and long-term
    """
    
    def __init__(self, db_session: Session):
        self.db = db_session
        self._cache = None
        
    async def _get_cache(self):
        """Lazy cache initialization"""
        if self._cache is None:
            self._cache = await get_cache_service()
        return self._cache
    
    def get_conversation_context(self, customer_id: int) -> Dict[str, Any]:
        """
        Get comprehensive conversation context with intelligent caching
        """
        # Try cache first for performance
        cached_context = self.cache.get_conversation_context(customer_id)
        if cached_context:
            return cached_context
        
        # Get or create session
        session = ConversationSession.get_or_create_session(self.db, customer_id)
        base_context = session.get_context() or {}
        
        # Enhance with real-time data
        enhanced_context = self._enhance_context_with_realtime_data(customer_id, base_context)
        
        # Cache for quick access
        self.cache.set_conversation_context(customer_id, enhanced_context)
        
        return enhanced_context
    
    def update_conversation_context(self, customer_id: int, updates: Dict[str, Any]):
        """
        Update conversation context with intelligent merging
        """
        session = ConversationSession.get_or_create_session(self.db, customer_id)
        current_context = session.get_context() or {}
        
        # Intelligent context merging
        merged_context = self._merge_context_intelligently(current_context, updates)
        
        # Update database
        session.update_state(session.current_state, merged_context)
        self.db.commit()
        
        # Update cache
        self.cache.set_conversation_context(customer_id, merged_context)
        
        # Invalidate related caches
        self.cache.invalidate_customer_cache(customer_id)
    
    def add_conversation_turn(self, customer_id: int, user_message: str, assistant_response: str):
        """
        Add a complete conversation turn with context preservation
        """
        session = ConversationSession.get_or_create_session(self.db, customer_id)
        context = session.get_context() or {}
        
        # Get or initialize conversation history
        history = context.get('conversation_history', [])
        
        # Add user message
        history.append({
            'role': 'user',
            'content': user_message,
            'timestamp': datetime.utcnow().isoformat(),
            'message_id': f"user_{len(history)}"
        })
        
        # Add assistant response
        history.append({
            'role': 'assistant',
            'content': assistant_response,
            'timestamp': datetime.utcnow().isoformat(),
            'message_id': f"assistant_{len(history)}"
        })
        
        # Maintain rolling window of last 20 messages (10 turns)
        if len(history) > 20:
            # Keep recent messages and create summary of older ones
            old_messages = history[:-20]
            recent_messages = history[-20:]
            
            # Create summary of old conversation
            old_summary = self._create_conversation_summary(old_messages)
            
            context.update({
                'conversation_history': recent_messages,
                'conversation_summary': old_summary,
                'total_message_count': len(history)
            })
        else:
            context['conversation_history'] = history
        
        # Update session
        session.update_state(session.current_state, context)
        self.db.commit()
        
        # Clear cache to force refresh
        self.cache.session_cache.delete(f"conversation_{customer_id}")
    
    def get_customer_memory_profile(self, customer_id: int) -> Dict[str, Any]:
        """
        Get comprehensive memory profile including preferences, patterns, and history
        """
        # Check cache first
        cache_key = f"memory_profile_{customer_id}"
        cached_profile = self.cache.analytics_cache.get(cache_key)
        if cached_profile:
            return cached_profile
        
        # Build comprehensive profile
        profile = {
            'customer_id': customer_id,
            'generated_at': datetime.utcnow().isoformat(),
        }
        
        # 1. Recent conversation context
        conversation_context = self.get_conversation_context(customer_id)
        profile['conversation_context'] = conversation_context
        
        # 2. Order history and patterns
        profile['order_patterns'] = self._analyze_order_patterns(customer_id)
        
        # 3. Product preferences
        profile['product_preferences'] = self._analyze_product_preferences(customer_id)
        
        # 4. Communication preferences
        profile['communication_patterns'] = self._analyze_communication_patterns(customer_id)
        
        # 5. Temporal patterns (when customer usually orders)
        profile['temporal_patterns'] = self._analyze_temporal_patterns(customer_id)
        
        # Cache for 2 hours
        self.cache.analytics_cache.set(cache_key, profile, expire=7200)
        
        return profile
    
    def get_contextual_recommendations(self, customer_id: int, current_context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Get intelligent recommendations based on conversation context and customer history
        """
        memory_profile = self.get_customer_memory_profile(customer_id)
        
        recommendations = []
        
        # 1. Context-aware product recommendations
        current_intent = current_context.get('current_intent', 'unknown')
        if current_intent == 'place_order':
            recommendations.extend(self._get_order_context_recommendations(customer_id, memory_profile))
        
        # 2. Time-based recommendations
        current_hour = datetime.now().hour
        temporal_recs = self._get_temporal_recommendations(customer_id, current_hour, memory_profile)
        recommendations.extend(temporal_recs)
        
        # 3. Conversation history based recommendations
        conversation_recs = self._get_conversation_based_recommendations(customer_id, memory_profile)
        recommendations.extend(conversation_recs)
        
        # Deduplicate and rank
        unique_recommendations = self._deduplicate_and_rank_recommendations(recommendations)
        
        return unique_recommendations[:5]  # Top 5 recommendations
    
    def store_interaction_outcome(self, customer_id: int, interaction_data: Dict[str, Any]):
        """
        Store interaction outcome for learning and improvement
        """
        session = ConversationSession.get_or_create_session(self.db, customer_id)
        context = session.get_context() or {}
        
        # Get or initialize interaction history
        interactions = context.get('interaction_outcomes', [])
        
        # Add new interaction with timestamp
        interaction_entry = {
            **interaction_data,
            'timestamp': datetime.utcnow().isoformat(),
            'interaction_id': f"interaction_{len(interactions)}"
        }
        
        interactions.append(interaction_entry)
        
        # Keep last 50 interactions
        if len(interactions) > 50:
            interactions = interactions[-50:]
        
        context['interaction_outcomes'] = interactions
        
        # Update session
        session.update_state(session.current_state, context)
        self.db.commit()
        
        # Invalidate related caches
        self.cache.invalidate_customer_cache(customer_id)
    
    def _enhance_context_with_realtime_data(self, customer_id: int, base_context: Dict[str, Any]) -> Dict[str, Any]:
        """Enhance base context with real-time customer data"""
        enhanced = base_context.copy()
        
        try:
            # Add recent order information
            recent_orders = self.db.query(Order).filter(
                Order.customer_id == customer_id
            ).order_by(Order.created_at.desc()).limit(3).all()
            
            enhanced['recent_orders'] = [
                {
                    'order_number': order.order_number,
                    'status': order.status.value,
                    'total_amount': float(order.total_amount) if order.total_amount else 0,
                    'created_at': order.created_at.isoformat(),
                    'payment_method': order.payment_method.value if order.payment_method else None
                }
                for order in recent_orders
            ]
            
            # Add customer info
            customer = self.db.query(Customer).filter(Customer.id == customer_id).first()
            if customer:
                enhanced['customer_info'] = {
                    'name': customer.name,
                    'phone_number': customer.phone_number,
                    'group_id': customer.group_id,
                    'active_group_id': customer.active_group_id
                }
            
            # Add session metadata
            enhanced['session_metadata'] = {
                'last_updated': datetime.utcnow().isoformat(),
                'context_version': '2.0'
            }
            
        except Exception as e:
            logger.error(f"Error enhancing context for customer {customer_id}: {e}")
        
        return enhanced
    
    def _merge_context_intelligently(self, current: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
        """Intelligent context merging that preserves important data"""
        merged = current.copy()
        
        for key, value in updates.items():
            if key == 'conversation_history':
                # Special handling for conversation history
                existing_history = merged.get('conversation_history', [])
                if isinstance(value, list):
                    existing_history.extend(value)
                    # Maintain size limit
                    if len(existing_history) > 20:
                        existing_history = existing_history[-20:]
                    merged['conversation_history'] = existing_history
            elif key in ['preferences', 'cart_state', 'session_data']:
                # Merge nested dictionaries
                if isinstance(value, dict) and isinstance(merged.get(key), dict):
                    merged[key].update(value)
                else:
                    merged[key] = value
            else:
                # Direct replacement for other keys
                merged[key] = value
        
        return merged
    
    def _create_conversation_summary(self, messages: List[Dict[str, Any]]) -> str:
        """Create a concise summary of older conversation messages"""
        if not messages:
            return ""
        
        user_messages = [msg['content'] for msg in messages if msg['role'] == 'user']
        assistant_messages = [msg['content'] for msg in messages if msg['role'] == 'assistant']
        
        summary = f"Previous conversation covered {len(user_messages)} user messages. "
        
        # Extract key topics (simple keyword extraction)
        all_text = " ".join(user_messages + assistant_messages).lower()
        common_keywords = ['order', 'payment', 'delivery', 'price', 'menu', 'food', 'drink']
        mentioned_topics = [keyword for keyword in common_keywords if keyword in all_text]
        
        if mentioned_topics:
            summary += f"Topics discussed: {', '.join(mentioned_topics)}. "
        
        return summary
    
    def _analyze_order_patterns(self, customer_id: int) -> Dict[str, Any]:
        """Analyze customer's ordering patterns"""
        try:
            orders = self.db.query(Order).filter(
                Order.customer_id == customer_id
            ).order_by(Order.created_at.desc()).limit(20).all()
            
            if not orders:
                return {'total_orders': 0, 'patterns': []}
            
            patterns = {
                'total_orders': len(orders),
                'average_order_value': sum(float(o.total_amount or 0) for o in orders) / len(orders),
                'preferred_payment_methods': self._get_payment_method_preferences(orders),
                'order_frequency': self._calculate_order_frequency(orders),
                'last_order_date': orders[0].created_at.isoformat() if orders else None
            }
            
            return patterns
            
        except Exception as e:
            logger.error(f"Error analyzing order patterns for customer {customer_id}: {e}")
            return {'total_orders': 0, 'error': str(e)}
    
    def _analyze_product_preferences(self, customer_id: int) -> Dict[str, Any]:
        """Analyze customer's product preferences from order history"""
        try:
            # This is a simplified version - in practice, you'd analyze OrderItems
            orders = self.db.query(Order).filter(
                Order.customer_id == customer_id
            ).limit(10).all()
            
            # For now, return basic structure
            return {
                'favorite_categories': [],
                'price_sensitivity': 'medium',
                'order_size_preference': 'medium'
            }
            
        except Exception as e:
            logger.error(f"Error analyzing product preferences for customer {customer_id}: {e}")
            return {}
    
    def _analyze_communication_patterns(self, customer_id: int) -> Dict[str, Any]:
        """Analyze how the customer prefers to communicate"""
        session = ConversationSession.get_or_create_session(self.db, customer_id)
        context = session.get_context() or {}
        
        conversation_history = context.get('conversation_history', [])
        
        if not conversation_history:
            return {'communication_style': 'unknown', 'message_length_preference': 'medium'}
        
        user_messages = [msg for msg in conversation_history if msg['role'] == 'user']
        
        if user_messages:
            avg_message_length = sum(len(msg['content']) for msg in user_messages) / len(user_messages)
            
            if avg_message_length < 20:
                message_style = 'brief'
            elif avg_message_length > 100:
                message_style = 'detailed'
            else:
                message_style = 'moderate'
        else:
            message_style = 'unknown'
        
        return {
            'communication_style': message_style,
            'message_length_preference': message_style,
            'interaction_count': len(user_messages)
        }
    
    def _analyze_temporal_patterns(self, customer_id: int) -> Dict[str, Any]:
        """Analyze when the customer typically interacts"""
        try:
            orders = self.db.query(Order).filter(
                Order.customer_id == customer_id
            ).all()
            
            if not orders:
                return {'peak_hours': [], 'preferred_days': []}
            
            # Extract hours and days from order timestamps
            hours = [order.created_at.hour for order in orders]
            days = [order.created_at.strftime('%A') for order in orders]
            
            # Find most common hours and days
            from collections import Counter
            hour_counts = Counter(hours)
            day_counts = Counter(days)
            
            return {
                'peak_hours': [h for h, _ in hour_counts.most_common(3)],
                'preferred_days': [d for d, _ in day_counts.most_common(2)]
            }
            
        except Exception as e:
            logger.error(f"Error analyzing temporal patterns for customer {customer_id}: {e}")
            return {'peak_hours': [], 'preferred_days': []}
    
    def _get_payment_method_preferences(self, orders: List[Order]) -> List[str]:
        """Get preferred payment methods from order history"""
        from collections import Counter
        
        payment_methods = [
            order.payment_method.value for order in orders 
            if order.payment_method
        ]
        
        if not payment_methods:
            return []
        
        method_counts = Counter(payment_methods)
        return [method for method, _ in method_counts.most_common(2)]
    
    def _calculate_order_frequency(self, orders: List[Order]) -> str:
        """Calculate how frequently the customer orders"""
        if len(orders) < 2:
            return 'insufficient_data'
        
        # Calculate average days between orders
        time_diffs = []
        for i in range(1, len(orders)):
            diff = (orders[i-1].created_at - orders[i].created_at).days
            time_diffs.append(diff)
        
        if not time_diffs:
            return 'insufficient_data'
        
        avg_days_between = sum(time_diffs) / len(time_diffs)
        
        if avg_days_between <= 7:
            return 'frequent'
        elif avg_days_between <= 30:
            return 'regular'
        else:
            return 'occasional'
    
    def _get_order_context_recommendations(self, customer_id: int, memory_profile: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get recommendations when customer wants to place an order"""
        recommendations = []
        
        # Based on order patterns
        order_patterns = memory_profile.get('order_patterns', {})
        if order_patterns.get('total_orders', 0) > 0:
            recommendations.append({
                'type': 'repeat_order',
                'reason': 'based_on_order_history',
                'confidence': 0.8
            })
        
        return recommendations
    
    def _get_temporal_recommendations(self, customer_id: int, current_hour: int, memory_profile: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get time-based recommendations"""
        recommendations = []
        
        temporal_patterns = memory_profile.get('temporal_patterns', {})
        peak_hours = temporal_patterns.get('peak_hours', [])
        
        if current_hour in peak_hours:
            recommendations.append({
                'type': 'peak_time_recommendation',
                'reason': 'customer_usually_orders_at_this_time',
                'confidence': 0.7
            })
        
        return recommendations
    
    def _get_conversation_based_recommendations(self, customer_id: int, memory_profile: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get recommendations based on conversation history"""
        recommendations = []
        
        context = memory_profile.get('conversation_context', {})
        history = context.get('conversation_history', [])
        
        # Look for mentioned but not ordered items
        user_messages = [msg['content'].lower() for msg in history if msg['role'] == 'user']
        mentioned_items = []
        
        # Simple keyword extraction for food items
        food_keywords = ['pizza', 'burger', 'coffee', 'tea', 'sandwich', 'salad']
        for message in user_messages:
            for keyword in food_keywords:
                if keyword in message and keyword not in mentioned_items:
                    mentioned_items.append(keyword)
        
        for item in mentioned_items:
            recommendations.append({
                'type': 'mentioned_item',
                'item': item,
                'reason': 'mentioned_in_conversation',
                'confidence': 0.6
            })
        
        return recommendations
    
    def _deduplicate_and_rank_recommendations(self, recommendations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicates and rank recommendations by confidence"""
        # Simple deduplication by type
        seen_types = set()
        unique_recs = []
        
        for rec in recommendations:
            rec_type = rec.get('type', 'unknown')
            if rec_type not in seen_types:
                seen_types.add(rec_type)
                unique_recs.append(rec)
        
        # Sort by confidence score
        return sorted(unique_recs, key=lambda x: x.get('confidence', 0), reverse=True)

def get_enhanced_memory_service(db: Session) -> EnhancedMemoryService:
    """Get enhanced memory service instance"""
    return EnhancedMemoryService(db)