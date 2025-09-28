"""
AI Integration service for WhatsApp webhooks
Handles AI-powered responses and context management
"""
import logging
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from app import models
from app.services.whatsapp import WhatsAppService
from app.services.ai_agent import AIAgentService

logger = logging.getLogger(__name__)

class AIProcessor:
    """AI-powered message processing and response service"""
    
    def __init__(self, db: Session, whatsapp_service: WhatsAppService):
        self.db = db
        self.whatsapp_service = whatsapp_service
        self.ai_service = AIAgentService(db)
    
    async def handle_customer_message_with_ai_context(self, customer: models.Customer, 
                                                    event_data: dict, 
                                                    current_group_id: Optional[int] = None) -> Dict[str, Any]:
        """Process customer message using AI agent with context"""
        try:
            # Extract message details
            phone_number = customer.phone_number
            message = event_data.get('message', {}).get('text', {}).get('body', '')
            message_type = event_data.get('message', {}).get('type', 'text')
            button_id = event_data.get('message', {}).get('button', {}).get('payload', '')
            
            # Get or create session
            session = self.db.query(models.CustomerSession).filter(
                models.CustomerSession.customer_id == customer.id
            ).first()
            
            if not session:
                session = models.CustomerSession(
                    customer_id=customer.id,
                    group_id=current_group_id or customer.group_id,
                    session_data={}
                )
                self.db.add(session)
                self.db.commit()
                self.db.refresh(session)
            
            # Build context for AI
            context = {
                "customer_state": customer.state.value if customer.state else "NEW",
                "phone_number": phone_number,
                "message": message,
                "message_type": message_type,
                "button_id": button_id,
                "session_data": session.session_data or {},
                "group_id": current_group_id or customer.group_id
            }
            
            # Get recent order history for context
            recent_orders = self.db.query(models.Order).filter(
                models.Order.customer_id == customer.id
            ).order_by(models.Order.created_at.desc()).limit(3).all()
            
            context["recent_orders"] = [
                {
                    "id": order.id,
                    "order_number": order.order_number,
                    "status": order.status.value,
                    "total_amount": order.total_amount,
                    "order_details": order.order_details,
                    "created_at": order.created_at.isoformat(),
                    "payment_status": order.payment_status.value if order.payment_status else None
                }
                for order in recent_orders
            ]
            
            # Get group information
            if current_group_id or customer.group_id:
                group = self.db.query(models.Group).filter(
                    models.Group.id == current_group_id or customer.group_id
                ).first()
                if group:
                    context["group"] = {
                        "id": group.id,
                        "name": group.name,
                        "identifier": group.identifier,
                        "category": group.category,
                        "payment_methods": group.payment_methods
                    }
            
            # Process with AI agent
            ai_result = await self.ai_service.process_customer_message(context)
            
            # Handle AI response
            if ai_result.get("success"):
                await self.handle_ai_agent_response(
                    ai_result, customer, session, phone_number, current_group_id or customer.group_id
                )
            else:
                # Fallback to default response
                await self.whatsapp_service.send_message(
                    phone_number,
                    "I'm having trouble understanding right now. Please try again or contact support."
                )
            
            return ai_result
            
        except Exception as e:
            logger.error(f"Error in AI context handling: {str(e)}")
            return {"success": False, "error": str(e)}
    
    async def handle_ai_agent_response(self, ai_result: Dict[str, Any], customer: models.Customer,
                                     session: models.CustomerSession, phone_number: str, group_id: int):
        """Handle the response from AI agent"""
        try:
            response_data = ai_result.get("response", {})
            
            # Update customer state if specified
            if "customer_state" in response_data:
                customer.state = models.CustomerState(response_data["customer_state"])
                self.db.commit()
            
            # Update session data
            if "session_data" in response_data:
                session.session_data = response_data["session_data"]
                self.db.commit()
            
            # Handle different response types
            response_type = response_data.get("type", "message")
            
            if response_type == "message":
                message_text = response_data.get("message", "")
                if message_text:
                    await self.whatsapp_service.send_message(phone_number, message_text)
            
            elif response_type == "buttons":
                message_text = response_data.get("message", "")
                buttons = response_data.get("buttons", [])
                if message_text and buttons:
                    await self.whatsapp_service.send_quick_reply_buttons(
                        phone_number, message_text, buttons
                    )
            
            elif response_type == "order_created":
                # Handle order creation
                await self.create_ai_enhanced_order(
                    phone_number, customer.id, group_id, response_data.get("order_data", {}), session
                )
            
            elif response_type == "payment_required":
                # Handle payment processing
                await self.handle_ai_payment_processing(
                    phone_number, customer.id, response_data.get("payment_data", {}), session
                )
            
            # Store AI interaction for learning
            await self.store_ai_interaction(customer.id, ai_result)
            
        except Exception as e:
            logger.error(f"Error handling AI agent response: {str(e)}")
            await self.whatsapp_service.send_message(
                phone_number, 
                "I encountered an error processing your request. Please try again."
            )
    
    async def create_ai_enhanced_order(self, phone_number: str, customer_id: int, group_id: int,
                                     order_data: Dict[str, Any], session: models.CustomerSession):
        """Create order from AI-processed data"""
        try:
            # Import here to avoid circular imports
            from app.services.webhook.order_processor import OrderProcessor
            
            order_processor = OrderProcessor(self.db, self.whatsapp_service)
            
            # Enhance order data with AI insights
            enhanced_order_data = {
                **order_data,
                "ai_processed": True,
                "confidence_score": order_data.get("confidence", 0.8),
                "extracted_items": order_data.get("items", []),
                "session_context": session.session_data
            }
            
            # Create the order
            order = await order_processor.create_order(
                phone_number, customer_id, group_id, enhanced_order_data
            )
            
            if order:
                # Send enhanced order confirmation
                await self.send_ai_enhanced_order_tracking(phone_number, {
                    "order_number": order.order_number,
                    "items": enhanced_order_data.get("items", []),
                    "total_amount": order.total_amount,
                    "confidence_score": enhanced_order_data.get("confidence", 0.8)
                })
            
        except Exception as e:
            logger.error(f"Error creating AI enhanced order: {str(e)}")
            await self.whatsapp_service.send_message(
                phone_number, 
                "I had trouble creating your order. Please try again or contact support."
            )
    
    async def send_ai_enhanced_order_tracking(self, phone_number: str, order_data: Dict[str, Any]):
        """Send AI-enhanced order tracking information"""
        try:
            order_number = order_data.get("order_number", "")
            items = order_data.get("items", [])
            total_amount = order_data.get("total_amount", 0)
            confidence = order_data.get("confidence_score", 0.8)
            
            # Build message with AI insights
            message = f"✅ Order {order_number} created successfully!\n\n"
            
            if items:
                message += "📋 **Order Summary:**\n"
                for item in items:
                    item_name = item.get("name", "Unknown item")
                    quantity = item.get("quantity", 1)
                    price = item.get("price", 0)
                    message += f"• {quantity}x {item_name}"
                    if price > 0:
                        message += f" - KSh {price:,.2f}"
                    message += "\n"
                message += "\n"
            
            if total_amount > 0:
                message += f"💰 **Total Amount:** KSh {total_amount:,.2f}\n\n"
            
            # Add confidence indicator if lower than expected
            if confidence < 0.7:
                message += "⚠️ Please confirm your order details are correct.\n\n"
            
            message += "Your order is being processed. You'll receive updates on its progress."
            
            # Add action buttons
            buttons = [
                {"id": f"track_{order_number}", "title": "📦 Track Order"},
                {"id": f"cancel_{order_number}", "title": "❌ Cancel Order"},
                {"id": "contact_support", "title": "💬 Contact Support"}
            ]
            
            await self.whatsapp_service.send_quick_reply_buttons(phone_number, message, buttons)
            
        except Exception as e:
            logger.error(f"Error sending AI enhanced order tracking: {str(e)}")
    
    async def handle_ai_payment_processing(self, phone_number: str, customer_id: int,
                                         payment_data: Dict[str, Any], session: models.CustomerSession):
        """Handle AI-processed payment flow"""
        try:
            # Import here to avoid circular imports
            from app.services.webhook.payment_processor import PaymentProcessor
            
            payment_processor = PaymentProcessor(self.db, self.whatsapp_service)
            
            # Process payment with AI insights
            await payment_processor.handle_ai_payment_request(
                phone_number, customer_id, payment_data, session
            )
            
        except Exception as e:
            logger.error(f"Error handling AI payment processing: {str(e)}")
            await self.whatsapp_service.send_message(
                phone_number, 
                "I had trouble processing your payment request. Please try again."
            )
    
    async def store_ai_interaction(self, customer_id: int, ai_result: Dict[str, Any]):
        """Store AI interaction for learning and analytics"""
        try:
            # Store interaction data for model improvement
            interaction = models.AIInteraction(
                customer_id=customer_id,
                interaction_type="message_processing",
                input_data=ai_result.get("input", {}),
                output_data=ai_result.get("response", {}),
                confidence_score=ai_result.get("confidence", 0.8),
                success=ai_result.get("success", False)
            )
            
            self.db.add(interaction)
            self.db.commit()
            
        except Exception as e:
            logger.error(f"Error storing AI interaction: {str(e)}")
    
    def get_last_assistant_response(self, ai_result: Dict[str, Any]) -> str:
        """Extract the last assistant response from AI result"""
        try:
            response_data = ai_result.get("response", {})
            return response_data.get("message", "")
        except Exception:
            return ""