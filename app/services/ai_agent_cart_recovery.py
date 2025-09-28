"""
AI Agent Cart Recovery Integration
Extends the existing AI agent with cart recovery capabilities
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from app.models import (
    ConversationSession, ConversationState, Customer, Order, OrderStatus,
    CartSession, CartStatus, CartRecoveryCampaign, RecoveryStatus
)
from app.services.cart_abandonment_service import get_cart_abandonment_service

logger = logging.getLogger(__name__)

class AIAgentCartRecoveryMixin:
    """
    Mixin to add cart recovery capabilities to your existing AI agent
    Add these methods to your OrderBotAgent class
    """
    
    async def handle_cart_recovery_response(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Handle customer response to cart recovery message"""
        try:
            messages = state.get("messages", [])
            customer_id = state.get("customer_id")
            
            if not messages or not customer_id:
                return state
            
            latest_message = messages[-1]
            message_content = latest_message.content if hasattr(latest_message, 'content') else str(latest_message)
            
            # Check if this is a response to a recovery campaign
            abandonment_service = get_cart_abandonment_service(self.db)
            is_recovery_response = abandonment_service.track_recovery_response(
                customer_id, message_content
            )
            
            if is_recovery_response:
                # Get the abandoned cart for this customer
                cart_session = self.db.query(CartSession).filter(
                    CartSession.customer_id == customer_id,
                    CartSession.status == CartStatus.ABANDONED
                ).order_by(CartSession.abandoned_at.desc()).first()
                
                if cart_session:
                    # Analyze customer's response intent
                    intent = await self._analyze_recovery_response_intent(message_content, cart_session)
                    
                    # Update state with recovery response handling
                    state["cart_recovery_data"] = {
                        "cart_session_id": cart_session.id,
                        "recovery_intent": intent,
                        "cart_data": cart_session.cart_data,
                        "original_message": message_content
                    }
                    
                    state["last_action"] = "recovery_response_handled"
                    
                    # Generate appropriate response based on intent
                    response = await self._generate_recovery_response(intent, cart_session, message_content)
                    state["order_data"] = response
            
            return state
            
        except Exception as e:
            logger.error(f"Error handling cart recovery response: {e}")
            return state
    
    async def _analyze_recovery_response_intent(self, message: str, cart_session: CartSession) -> str:
        """Analyze customer's intent in response to recovery message"""
        try:
            prompt = f"""Analyze this customer's response to a cart recovery message and determine their intent.

Customer's response: "{message}"

Cart context:
- Items in cart: {len(cart_session.cart_data.get('items', []))} items
- Estimated total: ${cart_session.estimated_total}
- Abandonment reason: {cart_session.abandonment_reason.value if cart_session.abandonment_reason else 'unknown'}

Possible intents:
1. continue_order - Customer wants to proceed with their original order
2. modify_order - Customer wants to change something about their order
3. price_concern - Customer has concerns about pricing/cost
4. not_interested - Customer is not interested in purchasing
5. general - General inquiry or unclear intent

Respond with just the intent name (e.g., "continue_order")."""

            # Use your existing AI call method
            response = await self._rate_limited_llm_call([
                {"role": "user", "content": prompt}
            ], estimated_tokens=len(prompt))
            
            intent = response.content.lower().strip()
            
            # Validate intent
            valid_intents = ["continue_order", "modify_order", "price_concern", "not_interested", "general"]
            if intent in valid_intents:
                return intent
            
            # Fallback to keyword analysis
            message_lower = message.lower()
            if any(word in message_lower for word in ["yes", "continue", "proceed", "complete"]):
                return "continue_order"
            elif any(word in message_lower for word in ["change", "modify", "different", "instead"]):
                return "modify_order"
            elif any(word in message_lower for word in ["expensive", "cost", "price", "discount", "cheaper"]):
                return "price_concern"
            elif any(word in message_lower for word in ["no", "not interested", "cancel", "don't want"]):
                return "not_interested"
            else:
                return "general"
                
        except Exception as e:
            logger.error(f"Error analyzing recovery response intent: {e}")
            return "general"
    
    async def _generate_recovery_response(self, intent: str, cart_session: CartSession, original_message: str) -> Dict[str, Any]:
        """Generate appropriate response based on customer intent"""
        try:
            if intent == "continue_order":
                return {
                    "response_type": "recovery_successful",
                    "cart_session_id": cart_session.id,
                    "cart_data": cart_session.cart_data,
                    "ai_response": "Great! Let me help you complete your order. Here's what you had in your cart:",
                    "next_action": "resume_checkout"
                }
                
            elif intent == "modify_order":
                return {
                    "response_type": "modify_request",
                    "cart_session_id": cart_session.id,
                    "ai_response": "I'd be happy to help you modify your order. What changes would you like to make?",
                    "next_action": "modify_cart"
                }
                
            elif intent == "price_concern":
                return {
                    "response_type": "price_concern",
                    "cart_session_id": cart_session.id,
                    "ai_response": "I understand your concern about pricing. Let me see if I can offer you a better deal! 🎉 Use code SAVE10 for 10% off your order.",
                    "next_action": "offer_discount"
                }
                
            elif intent == "not_interested":
                cart_session.status = CartStatus.EXPIRED
                self.db.commit()
                return {
                    "response_type": "not_interested",
                    "ai_response": "No problem! Your cart will be saved for 7 days if you change your mind. How else can I help you today?"
                }
            
            else:
                return {
                    "response_type": "general",
                    "ai_response": "Thanks for getting back to me! How can I help you today?"
                }
                
        except Exception as e:
            logger.error(f"Error generating recovery response: {e}")
            return {
                "response_type": "error",
                "ai_response": "I'm here to help! How can I assist you today?"
            }
    
    def check_for_cart_abandonment_signals(self, state: Dict[str, Any]) -> bool:
        """Check if current conversation shows cart abandonment signals"""
        try:
            current_state = state.get("conversation_state")
            messages = state.get("messages", [])
            
            # Check if we're in a cart-related state
            cart_states = [
                ConversationState.AWAITING_ORDER_DETAILS,
                ConversationState.AWAITING_PAYMENT,
                ConversationState.AWAITING_PAYMENT_CONFIRMATION
            ]
            
            if current_state not in [s.value for s in cart_states]:
                return False
            
            # Check for abandonment signals in recent messages
            if messages:
                recent_message = messages[-1]
                message_content = recent_message.content if hasattr(recent_message, 'content') else str(recent_message)
                
                # Look for abandonment signals
                abandonment_signals = [
                    "too expensive", "too much", "can't afford", "maybe later",
                    "let me think", "not sure", "nevermind", "cancel"
                ]
                
                message_lower = message_content.lower()
                return any(signal in message_lower for signal in abandonment_signals)
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking for cart abandonment signals: {e}")
            return False
    
    def create_cart_session_from_conversation(self, state: Dict[str, Any]) -> Optional[CartSession]:
        """Create a cart session from current conversation state"""
        try:
            customer_id = state.get("customer_id")
            group_id = state.get("group_id")
            conversation_session_id = state.get("session_id")
            
            if not all([customer_id, group_id]):
                return None
            
            # Extract cart data from conversation context
            order_data = state.get("order_data", {})
            
            if not order_data or not order_data.get("items"):
                return None
            
            # Calculate estimated total
            estimated_total = 0.0
            items_count = 0
            
            for item in order_data.get("items", []):
                quantity = item.get("quantity", 1)
                price = item.get("price", 0.0)
                estimated_total += quantity * price
                items_count += quantity
            
            # Create cart session
            cart_session = CartSession(
                customer_id=customer_id,
                group_id=group_id,
                conversation_session_id=conversation_session_id,
                cart_data=order_data,
                estimated_total=estimated_total,
                items_count=items_count,
                status=CartStatus.ACTIVE,
                last_interaction_at=datetime.utcnow()
            )
            
            self.db.add(cart_session)
            self.db.commit()
            
            logger.info(f"Created cart session {cart_session.id} for customer {customer_id}")
            return cart_session
            
        except Exception as e:
            logger.error(f"Error creating cart session: {e}")
            return None


# Integration functions for webhook handlers
async def handle_cart_recovery_in_webhook(phone_number: str, customer_id: int, 
                                         order_data: Dict[str, Any], db: Session, 
                                         whatsapp_service):
    """Handle cart recovery responses in webhook - add this to your webhook.py"""
    try:
        response_type = order_data.get("response_type")
        
        if response_type == "recovery_successful":
            # Customer wants to continue - resume checkout
            cart_session_id = order_data.get("cart_session_id")
            cart_data = order_data.get("cart_data", {})
            
            # Create order from cart data
            await create_order_from_cart_recovery(
                phone_number, customer_id, cart_session_id, cart_data, db, whatsapp_service
            )
            
        elif response_type == "price_concern":
            # Offer discount was already included in ai_response
            whatsapp_service.send_text_message(phone_number, order_data.get("ai_response"))
            
        elif response_type == "modify_request":
            # Allow order modification
            whatsapp_service.send_text_message(phone_number, order_data.get("ai_response"))
            
        else:
            # General response
            ai_response = order_data.get("ai_response", "How can I help you today?")
            whatsapp_service.send_text_message(phone_number, ai_response)
            
    except Exception as e:
        logger.error(f"Error handling cart recovery in webhook: {e}")


async def create_order_from_cart_recovery(phone_number: str, customer_id: int, 
                                        cart_session_id: int, cart_data: Dict[str, Any], 
                                        db: Session, whatsapp_service):
    """Create an order from recovered cart data"""
    try:
        import json
        from app.models import Order, OrderStatus
        
        # Get cart session
        cart_session = db.query(CartSession).filter(CartSession.id == cart_session_id).first()
        if not cart_session:
            return
        
        # Create order using existing order creation logic
        order = Order(
            customer_id=customer_id,
            group_id=cart_session.group_id,
            order_details=json.dumps(cart_data),
            total_amount=cart_session.estimated_total,
            status=OrderStatus.PENDING
        )
        
        db.add(order)
        db.commit()
        
        # Mark cart as recovered
        abandonment_service = get_cart_abandonment_service(db)
        abandonment_service.mark_cart_recovered(cart_session, order)
        
        # Send order confirmation
        confirmation_message = f"🎉 Great! Your order #{order.order_number} has been created.\n\n"
        confirmation_message += f"Total: ${order.total_amount:.2f}\n"
        confirmation_message += "Please proceed with payment to confirm your order."
        
        whatsapp_service.send_text_message(phone_number, confirmation_message)
        
        logger.info(f"Created order {order.id} from cart recovery {cart_session_id}")
        
    except Exception as e:
        logger.error(f"Error creating order from cart recovery: {e}")
        whatsapp_service.send_text_message(
            phone_number, 
            "Sorry, there was an error processing your order. Please try again."
        )