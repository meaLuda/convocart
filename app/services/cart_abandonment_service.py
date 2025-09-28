"""
Cart Abandonment Detection and Recovery Service
Integrates with your existing AI agent and conversation flow
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models import (
    ConversationSession, ConversationState, Customer, Order, OrderStatus,
    CartSession, CartStatus, AbandonmentReason, CartRecoveryCampaign, RecoveryStatus
)
from app.services.ai_agent import get_ai_agent
from app.services.whatsapp import WhatsAppService
from app.services.analytics_service import get_analytics_service

logger = logging.getLogger(__name__)

class CartAbandonmentService:
    """Service for detecting and managing cart abandonment"""
    
    def __init__(self, db: Session):
        self.db = db
        self.ai_agent = get_ai_agent(db)
        self.analytics_service = get_analytics_service(db)
    
    def detect_abandonment(self) -> List[CartSession]:
        """
        Detect abandoned carts based on conversation states and time thresholds
        """
        abandonment_threshold = datetime.utcnow() - timedelta(minutes=15)
        
        # Find active cart sessions that haven't been interacted with
        abandoned_sessions = []
        
        # Query conversation sessions in cart-related states
        stalled_conversations = self.db.query(ConversationSession).filter(
            ConversationSession.is_active == True,
            ConversationSession.current_state.in_([
                ConversationState.AWAITING_ORDER_DETAILS,
                ConversationState.AWAITING_PAYMENT,
                ConversationState.AWAITING_PAYMENT_CONFIRMATION
            ]),
            ConversationSession.last_interaction < abandonment_threshold
        ).all()
        
        for conversation in stalled_conversations:
            cart_session = self._get_or_create_cart_session(conversation)
            if cart_session and cart_session.status == CartStatus.ACTIVE:
                # Analyze abandonment reason using AI
                reason = self._analyze_abandonment_reason(conversation, cart_session)
                cart_session.mark_abandoned(reason)
                abandoned_sessions.append(cart_session)
        
        self.db.commit()
        logger.info(f"Detected {len(abandoned_sessions)} abandoned carts")
        return abandoned_sessions
    
    def _get_or_create_cart_session(self, conversation: ConversationSession) -> Optional[CartSession]:
        """Get existing cart session or create new one"""
        cart_session = self.db.query(CartSession).filter(
            CartSession.conversation_session_id == conversation.id,
            CartSession.status == CartStatus.ACTIVE
        ).first()
        
        if not cart_session:
            # Extract cart data from conversation context
            context = conversation.get_context() or {}
            cart_data = self._extract_cart_data_from_context(context)
            
            if cart_data and cart_data.get("items"):
                cart_session = CartSession(
                    customer_id=conversation.customer_id,
                    group_id=context.get("group_id"),
                    conversation_session_id=conversation.id,
                    cart_data=cart_data,
                    estimated_total=cart_data.get("estimated_total", 0.0),
                    items_count=len(cart_data.get("items", [])),
                    last_interaction_at=conversation.last_interaction
                )
                self.db.add(cart_session)
                self.db.commit()
        
        return cart_session
    
    def _extract_cart_data_from_context(self, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract cart/order data from conversation context"""
        if "order_data" in context:
            return context["order_data"]
        
        if "extracted_items" in context:
            return {
                "items": context["extracted_items"],
                "estimated_total": context.get("estimated_total", 0.0)
            }
        
        return None
    
    def _analyze_abandonment_reason(self, conversation: ConversationSession, 
                                   cart_session: CartSession) -> AbandonmentReason:
        """Use AI to analyze why the cart was abandoned"""
        try:
            context = conversation.get_context() or {}
            conversation_history = context.get('conversation_history', [])
            
            if not conversation_history:
                return AbandonmentReason.UNKNOWN
            
            # Analyze recent messages for abandonment signals
            recent_messages = conversation_history[-5:]  # Last 5 messages
            messages_text = " ".join([msg.get('content', '') for msg in recent_messages])
            
            # Simple keyword-based analysis (can be enhanced with AI)
            if any(word in messages_text.lower() for word in ['expensive', 'cost', 'price', 'too much']):
                return AbandonmentReason.PRICING_CONCERN
            elif any(word in messages_text.lower() for word in ['delivery', 'shipping', 'location']):
                return AbandonmentReason.DELIVERY_ISSUE
            elif any(word in messages_text.lower() for word in ['out of stock', 'unavailable', 'not available']):
                return AbandonmentReason.PRODUCT_UNAVAILABLE
            elif conversation.current_state == ConversationState.AWAITING_PAYMENT:
                return AbandonmentReason.PAYMENT_HESITATION
            else:
                return AbandonmentReason.CUSTOMER_DISTRACTION
                
        except Exception as e:
            logger.error(f"Error analyzing abandonment reason: {e}")
            return AbandonmentReason.UNKNOWN
    
    def create_recovery_campaign(self, cart_session: CartSession) -> Optional[CartRecoveryCampaign]:
        """Create and execute a recovery campaign for abandoned cart"""
        if not cart_session.is_eligible_for_recovery():
            return None
        
        # Determine campaign type based on attempt number and time since abandonment
        campaign_type = self._determine_campaign_type(cart_session)
        
        # Generate personalized recovery message using AI
        recovery_message = self._generate_recovery_message(cart_session, campaign_type)
        
        # Create recovery campaign record
        campaign = CartRecoveryCampaign(
            cart_session_id=cart_session.id,
            campaign_type=campaign_type,
            message_content=recovery_message.get("message"),
            ai_personalization_data=recovery_message.get("personalization_data"),
            incentive_offered=recovery_message.get("incentive")
        )
        
        self.db.add(campaign)
        cart_session.recovery_attempts += 1
        cart_session.last_recovery_message_at = datetime.utcnow()
        self.db.commit()
        
        return campaign
    
    def _determine_campaign_type(self, cart_session: CartSession) -> str:
        """Determine the type of recovery campaign based on context"""
        time_since_abandonment = datetime.utcnow() - cart_session.abandoned_at
        attempt_number = cart_session.recovery_attempts + 1
        
        if time_since_abandonment < timedelta(hours=1):
            return "immediate"
        elif attempt_number == 1:
            return "gentle_reminder"
        elif attempt_number == 2:
            return "urgent"
        else:
            return "final_call"
    
    async def _generate_recovery_message(self, cart_session: CartSession, 
                                       campaign_type: str) -> Dict[str, Any]:
        """Generate personalized recovery message using AI"""
        try:
            customer = cart_session.customer
            cart_data = cart_session.cart_data or {}
            
            # Get customer analytics for personalization
            customer_profile = self.analytics_service.analyze_customer_behavior(
                customer.id, update_analytics=False
            )
            
            # Create AI prompt for recovery message generation
            prompt = f"""Generate a personalized WhatsApp cart recovery message for a customer who abandoned their cart.

Customer Context:
- Name: {customer.name or 'Customer'}
- Abandonment reason: {cart_session.abandonment_reason.value if cart_session.abandonment_reason else 'unknown'}
- Items in cart: {len(cart_data.get('items', []))} items
- Estimated total: {cart_session.estimated_total}
- Campaign type: {campaign_type}
- Recovery attempt: {cart_session.recovery_attempts + 1}
- Customer segment: {customer_profile.get('advanced_metrics', {}).get('customer_segment', 'new')}

Cart Items:
{self._format_cart_items_for_ai(cart_data.get('items', []))}

Generate a recovery message that:
1. Is friendly and not pushy
2. Reminds them of their items
3. Addresses their potential concerns based on abandonment reason
4. Includes an appropriate incentive for {campaign_type} campaign
5. Is under 160 characters for WhatsApp
6. Uses emojis appropriately

Provide response as JSON:
{{
    "message": "WhatsApp message text",
    "incentive": {{"type": "discount/free_shipping/none", "value": "10%/free/none"}},
    "personalization_data": {{"reason_addressed": true, "customer_name_used": true}}
}}"""

            # Use AI agent to generate message
            ai_response = await self.ai_agent._rate_limited_llm_call(
                [{"role": "user", "content": prompt}],
                estimated_tokens=len(prompt)
            )
            
            # Parse AI response (implement JSON parsing)
            import json
            try:
                response_data = json.loads(ai_response.content)
                return response_data
            except json.JSONDecodeError:
                # Fallback to simple message
                return self._get_fallback_recovery_message(campaign_type, cart_session)
                
        except Exception as e:
            logger.error(f"Error generating AI recovery message: {e}")
            return self._get_fallback_recovery_message(campaign_type, cart_session)
    
    def _format_cart_items_for_ai(self, items: List[Dict[str, Any]]) -> str:
        """Format cart items for AI prompt"""
        if not items:
            return "No items"
        
        formatted_items = []
        for item in items[:3]:  # Limit to first 3 items
            name = item.get('name', 'Unknown item')
            quantity = item.get('quantity', 1)
            formatted_items.append(f"- {quantity}x {name}")
        
        if len(items) > 3:
            formatted_items.append(f"... and {len(items) - 3} more items")
        
        return "\n".join(formatted_items)
    
    def _get_fallback_recovery_message(self, campaign_type: str, 
                                     cart_session: CartSession) -> Dict[str, Any]:
        """Fallback recovery messages when AI generation fails"""
        messages = {
            "immediate": {
                "message": "👋 Hi! You left some items in your cart. Complete your order now? 🛒",
                "incentive": {"type": "none", "value": "none"}
            },
            "gentle_reminder": {
                "message": "🛍️ Your cart is waiting! Complete your order and get 5% off. Use code SAVE5 📱",
                "incentive": {"type": "discount", "value": "5%"}
            },
            "urgent": {
                "message": "⏰ Last chance! Your cart expires soon. Complete now and get FREE delivery! 🚚",
                "incentive": {"type": "free_shipping", "value": "free"}
            },
            "final_call": {
                "message": "🎯 Final reminder: 10% off your cart + FREE delivery expires in 2 hours! ⏰",
                "incentive": {"type": "discount", "value": "10%"}
            }
        }
        
        return {
            **messages.get(campaign_type, messages["gentle_reminder"]),
            "personalization_data": {"fallback_used": True}
        }
    
    def send_recovery_message(self, campaign: CartRecoveryCampaign, 
                            whatsapp_service: WhatsAppService) -> bool:
        """Send recovery message via WhatsApp"""
        try:
            customer = campaign.cart_session.customer
            message_id = whatsapp_service.send_text_message(
                customer.phone_number,
                campaign.message_content
            )
            
            if message_id:
                campaign.whatsapp_message_id = message_id
                campaign.status = RecoveryStatus.IN_PROGRESS
                self.db.commit()
                logger.info(f"Sent recovery message to {customer.phone_number}")
                return True
            else:
                campaign.status = RecoveryStatus.FAILED
                self.db.commit()
                return False
                
        except Exception as e:
            logger.error(f"Error sending recovery message: {e}")
            campaign.status = RecoveryStatus.FAILED
            self.db.commit()
            return False
    
    def track_recovery_response(self, customer_id: int, message_content: str) -> bool:
        """Track if customer responds to recovery message"""
        # Find recent recovery campaigns for this customer
        recent_campaigns = self.db.query(CartRecoveryCampaign).join(CartSession).filter(
            CartSession.customer_id == customer_id,
            CartRecoveryCampaign.status == RecoveryStatus.IN_PROGRESS,
            CartRecoveryCampaign.message_sent_at > datetime.utcnow() - timedelta(hours=24)
        ).all()
        
        for campaign in recent_campaigns:
            campaign.customer_responded_at = datetime.utcnow()
            campaign.customer_response = message_content
            # Additional analysis can be added here
        
        self.db.commit()
        return len(recent_campaigns) > 0
    
    def mark_cart_recovered(self, cart_session: CartSession, order: Order):
        """Mark cart as successfully recovered"""
        cart_session.status = CartStatus.RECOVERED
        cart_session.recovered_at = datetime.utcnow()
        cart_session.completed_order_id = order.id
        
        # Mark relevant recovery campaigns as successful
        active_campaigns = self.db.query(CartRecoveryCampaign).filter(
            CartRecoveryCampaign.cart_session_id == cart_session.id,
            CartRecoveryCampaign.status == RecoveryStatus.IN_PROGRESS
        ).all()
        
        for campaign in active_campaigns:
            campaign.status = RecoveryStatus.SUCCESSFUL
            campaign.resulted_in_recovery = True
        
        self.db.commit()
        logger.info(f"Cart {cart_session.id} marked as recovered with order {order.id}")


def get_cart_abandonment_service(db: Session) -> CartAbandonmentService:
    """Get cart abandonment service instance"""
    return CartAbandonmentService(db)