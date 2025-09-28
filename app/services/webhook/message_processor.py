"""
Core message processing service for WhatsApp webhooks
Handles incoming message routing and context management
"""
import logging
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from app import models
from app.services.whatsapp import WhatsAppService

logger = logging.getLogger(__name__)

class MessageProcessor:
    """Core message processing and routing service"""
    
    def __init__(self, db: Session, whatsapp_service: WhatsAppService):
        self.db = db
        self.whatsapp_service = whatsapp_service
    
    def detect_customer_intent(self, message: str, message_type: str, button_id: str, 
                             current_state: str, completed_order: bool = False) -> str:
        """Detect customer intent from message content"""
        if not message and not button_id:
            return "unknown"
        
        # Priority: Handle button clicks first
        if button_id:
            if button_id.startswith("track_"):
                return "track_order"
            elif button_id.startswith("cancel_"):
                return "cancel_order"
            elif button_id.startswith("contact_"):
                return "contact_support"
            elif button_id.startswith("help_"):
                return "help"
            elif button_id.startswith("payment_"):
                return "payment_selection"
            elif button_id.startswith("feedback_"):
                return "feedback"
            elif button_id.startswith("reorder_"):
                return "reorder"
        
        # Handle text messages
        if message_type == "text" and message:
            message_lower = message.lower().strip()
            
            # M-Pesa detection - improved pattern
            if self.is_mpesa_message(message, message_type):
                return "mpesa_confirmation"
            
            # Help commands
            if self.is_help_command(message, message_type, button_id):
                return "help"
            
            # Order tracking
            if any(word in message_lower for word in ["track", "status", "where", "order"]):
                return "track_order"
            
            # Cancel order
            if any(word in message_lower for word in ["cancel", "stop", "end"]):
                return "cancel_order"
            
            # Contact support
            if any(word in message_lower for word in ["support", "help", "issue", "problem", "contact"]):
                return "contact_support"
            
            # Group joining detection
            if message_lower.startswith("order from group:"):
                return "join_group"
            
            # Payment method selection
            if current_state == "AWAITING_PAYMENT" and message_lower.isdigit():
                return "payment_selection"
        
        # Default based on customer state and completion status
        if completed_order:
            return "general_inquiry"
        elif current_state in ["AWAITING_PAYMENT", "PAYMENT_PENDING"]:
            return "payment_inquiry"
        else:
            return "place_order"
    
    def is_help_command(self, message: str, message_type: str, button_id: str) -> bool:
        """Check if message is a help command"""
        if button_id and button_id.startswith("help_"):
            return True
        
        if message_type == "text" and message:
            help_keywords = ["help", "menu", "options", "commands", "start", "info"]
            message_lower = message.lower().strip()
            return any(keyword in message_lower for keyword in help_keywords)
        
        return False
    
    def is_mpesa_message(self, message: str, message_type: str) -> bool:
        """Detect M-Pesa confirmation messages"""
        if message_type != "text" or not message:
            return False
        
        message_lower = message.lower()
        
        # M-Pesa confirmation patterns
        mpesa_indicators = [
            "confirmed",
            "m-pesa",
            "mpesa", 
            "transaction",
            "received",
            "sent to",
            "balance is",
            "new balance",
            "transaction cost"
        ]
        
        # Must contain M-Pesa indicator AND appear to be a confirmation
        has_mpesa_indicator = any(indicator in message_lower for indicator in mpesa_indicators)
        
        # Additional validation - should contain transaction-like patterns
        has_transaction_pattern = any([
            "ksh" in message_lower,
            "kes" in message_lower,
            any(char.isdigit() for char in message),
            "confirmed" in message_lower and len(message) > 20
        ])
        
        return has_mpesa_indicator and has_transaction_pattern
    
    async def get_or_create_customer(self, phone_number: str, group_id: Optional[int] = None) -> models.Customer:
        """Get existing customer or create new one"""
        customer = self.db.query(models.Customer).filter(
            models.Customer.phone_number == phone_number
        ).first()
        
        if not customer:
            customer = models.Customer(
                phone_number=phone_number,
                group_id=group_id,
                state=models.CustomerState.NEW
            )
            self.db.add(customer)
            self.db.commit()
            self.db.refresh(customer)
            logger.info(f"Created new customer: {phone_number}")
        
        return customer
    
    async def get_customer_group(self, customer: models.Customer) -> Optional[models.Group]:
        """Get the group associated with a customer"""
        if customer.group_id:
            return self.db.query(models.Group).filter(
                models.Group.id == customer.group_id,
                models.Group.is_active == True
            ).first()
        return None
    
    async def send_welcome_message(self, phone_number: str, group: models.Group):
        """Send welcome message to new customer"""
        try:
            if group and group.welcome_message:
                welcome_text = group.welcome_message
            else:
                welcome_text = (
                    f"Welcome to {group.name if group else 'our store'}! 🎉\n\n"
                    "I'm here to help you place orders easily. "
                    "Just tell me what you'd like to order, or type 'help' for options."
                )
            
            # Add quick action buttons
            buttons = [
                {"id": "help_menu", "title": "📋 Show Menu"},
                {"id": "track_order", "title": "📦 Track Order"},
                {"id": "contact_support", "title": "💬 Contact Support"}
            ]
            
            await self.whatsapp_service.send_quick_reply_buttons(
                phone_number, welcome_text, buttons
            )
            
        except Exception as e:
            logger.error(f"Error sending welcome message: {str(e)}")
            # Fallback to simple text
            await self.whatsapp_service.send_message(
                phone_number, 
                f"Welcome! How can I help you today?"
            )
    
    async def send_help_message(self, phone_number: str, group: models.Group):
        """Send help message with available options"""
        try:
            help_text = (
                f"Here's how I can help you with {group.name if group else 'your orders'}:\n\n"
                "🛒 **Place an Order**: Just tell me what you want to order\n"
                "📦 **Track Order**: Check your order status\n"
                "❌ **Cancel Order**: Cancel a pending order\n"
                "💬 **Contact Support**: Get help from our team\n\n"
                "You can also use the buttons below for quick actions!"
            )
            
            buttons = [
                {"id": "track_order", "title": "📦 Track Order"},
                {"id": "contact_support", "title": "💬 Contact Support"},
                {"id": "help_menu", "title": "📋 Show Menu"}
            ]
            
            await self.whatsapp_service.send_quick_reply_buttons(
                phone_number, help_text, buttons
            )
            
        except Exception as e:
            logger.error(f"Error sending help message: {str(e)}")
            await self.whatsapp_service.send_message(
                phone_number, 
                "I can help you place orders, track orders, or contact support. What would you like to do?"
            )
    
    def send_default_options(self, phone_number: str):
        """Send default options when customer intent is unclear"""
        try:
            default_text = (
                "I'm not sure what you're looking for. Here are some things I can help with:\n\n"
                "• Place a new order\n"
                "• Track existing orders\n"
                "• Get help or contact support\n\n"
                "Please choose an option below or tell me what you need!"
            )
            
            buttons = [
                {"id": "track_order", "title": "📦 Track Order"},
                {"id": "contact_support", "title": "💬 Contact Support"},
                {"id": "help_menu", "title": "📋 Help"}
            ]
            
            self.whatsapp_service.send_quick_reply_buttons(
                phone_number, default_text, buttons
            )
            
        except Exception as e:
            logger.error(f"Error sending default options: {str(e)}")
            self.whatsapp_service.send_message(
                phone_number, 
                "I can help you with orders, tracking, or support. What would you like to do?"
            )