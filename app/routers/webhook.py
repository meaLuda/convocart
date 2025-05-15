# routes/webhook.py
import json
import logging
import re
from typing import Dict, Any, Optional, List
from datetime import datetime
from fastapi import APIRouter, Request, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.whatsapp import WhatsAppService
from app.config import WEBHOOK_VERIFY_TOKEN
from app import models
from app.models import ConversationState

router = APIRouter()
logger = logging.getLogger(__name__)

# Initialize WhatsApp service - will be updated when configuration changes
whatsapp_service = WhatsAppService()

@router.get("/webhook")
async def verify_webhook(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
):
    """
    Verify the webhook endpoint for WhatsApp
    """
    if hub_mode == "subscribe" and hub_verify_token == WEBHOOK_VERIFY_TOKEN:
        logger.info("Webhook verified successfully")
        return int(hub_challenge)
    
    logger.warning("Webhook verification failed")
    raise HTTPException(status_code=403, detail="Verification failed")

@router.post("/webhook")
async def process_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Process incoming webhook events from WhatsApp
    """
    try:
        data = await request.json()
        logger.info(f"Received webhook data: {data}")
        
        # Process the webhook event data
        event_data = whatsapp_service.process_webhook_event(data)
        logger.info(f"Processed event data: {event_data}")
        
        if not event_data:
            logger.warning("No event data extracted from webhook payload")
            return {"success": True, "message": "Event processed but no action taken"}
        
        # Get the phone number of the sender
        phone_number = event_data.get("phone_number")
        if not phone_number:
            logger.warning("No phone number found in event data")
            return {"success": False, "error": "Missing phone number"}
        
        # Look for the customer across all groups first
        customer = db.query(models.Customer).filter(
            models.Customer.phone_number == phone_number
        ).first()
        
        # Extract the message and its type
        message = event_data.get("message", "").strip()
        message_type = event_data.get("type")
        
        # Extract current group context
        current_group_id = None
        
        # Check if this is the initial click-to-chat message which contains the group info
        if message_type == "text" and message.startswith("order from group:"):
            group_identifier = message.replace("order from group:", "").strip()
            logger.info(f"Looking for group with identifier: {group_identifier}")
            
            group = db.query(models.Group).filter(
                models.Group.identifier == group_identifier,
                models.Group.is_active == True
            ).first()
            
            if group:
                current_group_id = group.id
                
                # If customer doesn't exist yet, create them
                if not customer:
                    customer = models.Customer(
                        phone_number=phone_number,
                        name=event_data.get("name", "New Customer"),
                        group_id=current_group_id,
                        active_group_id=current_group_id  # Set active group to current group
                    )
                    db.add(customer)
                    db.commit()
                    db.refresh(customer)
                    logger.info(f"Created new customer with ID {customer.id} for phone {phone_number}")
                else:
                    # If customer exists, update their active_group_id
                    customer.active_group_id = current_group_id
                    db.commit()
                    logger.info(f"Updated customer {customer.id} with active_group_id {current_group_id}")
                    
                # Now we need to reset or create a new conversation session since this is a new interaction
                # But only if it's not from an existing active conversation
                if customer:
                    session = models.ConversationSession.get_or_create_session(db, customer.id)
                    # Override the state to INITIAL since this is a new group interaction
                    session.update_state(ConversationState.INITIAL)
                    db.commit()
        
        # If we still don't have a customer record, we can't proceed
        if not customer:
            logger.warning(f"No customer found and couldn't create one. Sending help message to {phone_number}")
            # Send a welcome message guiding them to use a proper link
            welcome_msg = "👋 Welcome to our Order Bot!\n\n"
            welcome_msg += "It seems you're trying to place an order, but we couldn't identify which business you're trying to order from.\n\n"
            welcome_msg += "Please use the link that the business shared with you to start your order properly."
            whatsapp_service.send_text_message(phone_number, welcome_msg)
            return {"success": True, "message": "Sent help message to new customer"}
        
        # Now handle the customer's message with conversation context
        await handle_customer_message_with_context(customer, event_data, db, current_group_id)
        
        return {"success": True, "message": "Webhook processed successfully"}
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        return {"success": False, "error": str(e)}
    
async def handle_customer_message_with_context(customer, event_data, db, current_group_id=None):
    """
    Process the customer message with conversation context awareness
    """
    phone_number = customer.phone_number
    message = event_data.get("message", "").strip()
    message_type = event_data.get("type")
    button_id = event_data.get("button_id", "") if message_type == "button" else None
    
    # Get or create conversation session
    session = models.ConversationSession.get_or_create_session(db, customer.id)
    current_state = session.current_state
    context = session.get_context()
    
    # Prioritize explicitly provided group_id, then active_group_id, then default group_id
    group_id = current_group_id or customer.active_group_id or customer.group_id
    
    # Debug log to help diagnose issues
    logger.info(f"CONVERSATION CONTEXT: state={current_state}, customer_id={customer.id}, group_id={group_id}")
    logger.info(f"Processing message: type={message_type}, content_preview={message[:30]}...")
    
    group = db.query(models.Group).filter(models.Group.id == group_id).first()
    
    # First, handle system-wide commands that override conversation state
    if is_help_command(message, message_type, button_id):
        await send_help_message(phone_number, group, whatsapp_service)
        return
        
    # STEP 1: Handle the initial welcome flow
    if current_state == ConversationState.INITIAL:
        if message_type == "text" and message.startswith("order from group:"):
            # New conversation from click-to-chat link
            await send_welcome_message(phone_number, group, whatsapp_service)
            session.update_state(ConversationState.WELCOME)
            db.commit()
            return
        else:
            # We're in INITIAL state but didn't get an initial group message
            # This might be a continuation of an existing conversation
            # Move to IDLE state and proceed with intent detection
            session.update_state(ConversationState.IDLE)
            db.commit()
    
    # STEP 2: Handle primary menu options and commands
    # Detect intent from message or button press
    intent = detect_customer_intent(message, message_type, button_id, current_state)
    
    # Handle detected intent
    if intent == "place_order":
        # User wants to place an order
        place_order_msg = "Please type your order details, including:\n\n"
        place_order_msg += "- Item names\n- Quantities\n- Any special requests\n\n"
        place_order_msg += "Example: 2 t-shirts size L, 1 hoodie black size XL"
        
        whatsapp_service.send_text_message(phone_number, place_order_msg)
        session.update_state(ConversationState.AWAITING_ORDER_DETAILS)
        db.commit()
        return
        
    elif intent == "track_order":
        # User wants to track orders
        await handle_track_order(phone_number, customer.id, db, whatsapp_service)
        session.update_state(ConversationState.IDLE)
        db.commit()
        return
        
    elif intent == "cancel_order":
        # User wants to cancel an order
        whatsapp_service.handle_cancel_order(phone_number, customer.id, db, whatsapp_service)
        session.update_state(ConversationState.IDLE)
        db.commit()
        return
        
    elif intent == "contact_support":
        # User wants to contact support
        whatsapp_service.handle_contact_support(phone_number, group, whatsapp_service)
        session.update_state(ConversationState.WAITING_FOR_SUPPORT)
        db.commit()
        return
    
    elif intent == "mpesa_payment":
        # User indicates they want to pay with M-Pesa
        mpesa_msg = "Please send your payment to our M-Pesa number and then share the transaction message/code/confirmation with us."
        whatsapp_service.send_text_message(phone_number, mpesa_msg)
        session.update_state(ConversationState.AWAITING_PAYMENT_CONFIRMATION)
        db.commit()
        return
        
    elif intent == "cash_payment":
        # User wants to pay with cash on delivery
        whatsapp_service.handle_cash_payment(phone_number, customer.id, db, whatsapp_service)
        session.update_state(ConversationState.IDLE)
        db.commit()
        return
    
    # STEP 3: Handle state-specific message processing
    if current_state == ConversationState.AWAITING_ORDER_DETAILS:
        # User is providing order details
        if message_type == "text" and len(message) > 5:
            await create_order(phone_number, customer.id, group_id, message, db, whatsapp_service)
            session.update_state(ConversationState.AWAITING_PAYMENT)
            db.commit()
            return
        else:
            # Not enough detail, ask again
            whatsapp_service.send_text_message(
                phone_number, 
                "Please provide more details about your order. Include items, quantities, and any special requests."
            )
            return
    
    elif current_state == ConversationState.AWAITING_PAYMENT_CONFIRMATION:
        # User is providing payment confirmation
        if is_mpesa_message(message, message_type):
            whatsapp_service.handle_mpesa_confirmation(phone_number, customer.id, message, db, whatsapp_service)
            session.update_state(ConversationState.IDLE)
            db.commit()
            return
    
    elif current_state == ConversationState.WELCOME:
        # We sent welcome message but didn't get a valid menu selection
        # Send default options
        send_default_options(phone_number, whatsapp_service)
        session.update_state(ConversationState.IDLE)
        db.commit()
        return
    
    # If we reach here, we couldn't determine what to do
    # Send default options
    send_default_options(phone_number, whatsapp_service)
    session.update_state(ConversationState.IDLE)
    db.commit()

def detect_customer_intent(message, message_type, button_id, current_state, completed_order=False):
    """
    Detect customer intent from message content and type
    """
    # First priority: Check button_id for explicit intent
    if button_id:
        if button_id == "place_order":
            return "place_order"
        elif button_id == "track_order":
            return "track_order"
        elif button_id == "cancel_order":
            return "cancel_order"
        elif button_id == "contact_support":
            return "contact_support"
        elif button_id in ["mpesa_message", "pay_with_m-pesa"]:
            # Don't allow payment changes for completed orders
            if completed_order:
                return "invalid_payment_for_completed"
            return "mpesa_payment"
        elif button_id == "pay_cash":
            # Don't allow payment changes for completed orders
            if completed_order:
                return "invalid_payment_for_completed"
            return "cash_payment"
    
    # Second priority: Check message text for intent
    if message_type == "text":
        # Normalize message text
        normalized_message = message.lower().strip()
        
        # Check for order placement intent
        if normalized_message in ["place order", "order", "new order", "i want to order"]:
            return "place_order"
            
        # Check for order tracking intent
        if normalized_message in ["track order", "track my order", "where is my order", "my orders", "status"]:
            return "track_order"
            
        # Check for order cancellation intent
        if normalized_message in ["cancel order", "cancel my order", "cancel"]:
            return "cancel_order"
            
        # Check for support intent
        if normalized_message in ["support", "help", "contact", "contact support", "talk to agent"]:
            return "contact_support"
            
        # Check for payment intent - Only if not a completed order
        if not completed_order and ("mpesa" in normalized_message or "m-pesa" in normalized_message or "pay" in normalized_message):
            return "mpesa_payment"
            
        if not completed_order and ("cash" in normalized_message or "deliver" in normalized_message or "cod" in normalized_message):
            return "cash_payment"
    
    # No clear intent detected
    return None


def is_help_command(message, message_type, button_id):
    """Check if message is a help command"""
    if message_type == "text":
        help_terms = ["help", "menu", "options", "commands", "assist", "support"]
        normalized_message = message.lower().strip()
        return any(term == normalized_message for term in help_terms)
    return False

def is_mpesa_message(message, message_type):
    """Check if message is an M-Pesa confirmation"""
    if message_type != "text":
        return False
        
    # Comprehensive pattern matching for M-Pesa transaction messages
    return (
        (len(message) >= 8 and len(message) <= 12 and message.isalnum()) or 
        message.upper().startswith("M-PESA") or 
        "TRANSACTION" in message.upper() or
        "CONFIRMED" in message.upper() or
        "RECEIVED KSH" in message.upper() or
        "MPESA" in message.upper()
    )

async def send_welcome_message(phone_number, group, whatsapp_service):
    """Send welcome message with options"""
    if not group:
        whatsapp_service.send_text_message(
            phone_number, 
            "Sorry, we couldn't identify the business you're trying to order from. Please use the correct link."
        )
        return
    
    # Send welcome message with quick options
    welcome_message = f"👋 Welcome to {group.name}!\n\n"
    
    if group.welcome_message:
        welcome_message += f"{group.welcome_message}\n\n"
    
    welcome_message += "What would you like to do?"
    
    buttons = [
        {"id": "place_order", "title": "Place Order"},
        {"id": "track_order", "title": "Track My Order"},
    ]
    
    whatsapp_service.send_quick_reply_buttons(phone_number, welcome_message, buttons)

async def send_help_message(phone_number, group, whatsapp_service):
    """Send help message with available options"""
    help_message = "Here are the commands you can use:\n\n"
    help_message += "• Type 'Place Order' to place a new order\n"
    help_message += "• Type 'Track Order' to check your orders\n"
    help_message += "• Type 'Cancel Order' to cancel a pending order\n"
    help_message += "• Type 'Help' to see this menu again\n\n"
    
    if group and group.contact_phone:
        help_message += f"Need more help? Contact {group.name} directly at {group.contact_phone}"
    
    whatsapp_service.send_text_message(phone_number, help_message)

def send_default_options(phone_number, whatsapp_service):
    """Send default options menu"""
    default_message = "What would you like to do? Please choose an option below:"
    
    buttons = [
        {"id": "place_order", "title": "Place Order"},
        {"id": "track_order", "title": "Track My Order"},
        {"id": "contact_support", "title": "Contact Support"}
    ]
    
    whatsapp_service.send_quick_reply_buttons(phone_number, default_message, buttons)

async def handle_track_order(phone_number, customer_id, db, whatsapp_service: WhatsAppService):
    """Handle order tracking request with consolidated details in a single message"""
    # Find recent orders for this customer
    recent_orders = db.query(models.Order).filter(
        models.Order.customer_id == customer_id
    ).order_by(models.Order.created_at.desc()).limit(3).all()
    
    if not recent_orders:
        whatsapp_service.send_text_message(
            phone_number,
            "You don't have any recent orders. Would you like to place a new order?"
        )
        return
    
    # Create a single consolidated message for all orders
    consolidated_message = "📋 *YOUR RECENT ORDERS*\n\n"
    
    # Add each order to the consolidated message
    for i, order in enumerate(recent_orders, 1):
        # Get group name
        group_name = "Our store"
        if order.group_id:
            group = db.query(models.Group).filter(models.Group.id == order.group_id).first()
            if group:
                group_name = group.name
        
        # Status emoji mapping
        status_emoji = {
            'pending': '🕒',
            'processing': '⚙️',
            'completed': '✅',
            'cancelled': '❌',
            'refunded': '💰'
        }
        
        emoji = status_emoji.get(order.status.value.lower(), '')
        
        # Add order header with separator if not the first order
        if i > 1:
            consolidated_message += "\n\n" + ("-" * 30) + "\n\n"
            
        consolidated_message += f"{emoji} *Order #{order.order_number}*\n"
        consolidated_message += f"Status: {order.status.value.title()}\n"
        consolidated_message += f"Store: {group_name}\n"
        consolidated_message += f"Date: {order.created_at.strftime('%Y-%m-%d %H:%M')}\n"
        
        if order.total_amount > 0:
            consolidated_message += f"Amount: KSH {order.total_amount:.2f}\n"
        
        # Payment information
        if hasattr(order, 'payment_method') and order.payment_method:
            payment_method = order.payment_method.value.replace('_', ' ').title()
            consolidated_message += f"Payment Method: {payment_method}\n"
            
            if hasattr(order, 'payment_status') and order.payment_status:
                payment_status = order.payment_status.value.title()
                consolidated_message += f"Payment Status: {payment_status}\n"
                
            if hasattr(order, 'payment_ref') and order.payment_ref:
                consolidated_message += f"Reference: {order.payment_ref}\n"
        
        # Order items preview (shortened)
        if order.order_details:
            consolidated_message += f"\nItems: {order.order_details[:50]}"
            if len(order.order_details) > 50:
                consolidated_message += "..."
    
    # Add footer
    consolidated_message += "\n\nTo place a new order, type 'Place Order'."
    
    # Send the consolidated message
    whatsapp_service.send_text_message(phone_number, consolidated_message)

async def handle_cancel_order(phone_number, customer_id, db, whatsapp_service):
    """Handle order cancellation request"""
    # Find the customer's last pending order
    last_order = db.query(models.Order).filter(
        models.Order.customer_id == customer_id,
        models.Order.status == models.OrderStatus.PENDING
    ).order_by(models.Order.created_at.desc()).first()
    
    if last_order:
        last_order.status = models.OrderStatus.CANCELLED
        db.commit()
        whatsapp_service.send_text_message(
            phone_number, 
            f"Your order #{last_order.order_number} has been cancelled. We hope to serve you again soon!"
        )
    else:
        whatsapp_service.send_text_message(
            phone_number,
            "You don't have any pending orders to cancel."
        )

async def handle_contact_support(phone_number, group, whatsapp_service):
    """Handle support contact request"""
    support_msg = "Need help with your order? You can contact support:\n\n"
    
    if group and group.contact_phone:
        support_msg += f"📞 Phone: {group.contact_phone}\n"
        
    if group and group.contact_email:
        support_msg += f"📧 Email: {group.contact_email}\n"
    else:
        support_msg += "📧 Email: support@example.com\n"
        
    support_msg += "\nOr reply with your question and we'll get back to you soon!"
    
    whatsapp_service.send_text_message(phone_number, support_msg)

async def handle_cash_payment(phone_number, customer_id, db, whatsapp_service):
    """Handle cash on delivery payment option"""
    # Update the most recent pending order to cash on delivery
    last_order = db.query(models.Order).filter(
        models.Order.customer_id == customer_id,
        models.Order.status == models.OrderStatus.PENDING
    ).order_by(models.Order.created_at.desc()).first()
    
    if last_order:
        last_order.payment_method = models.PaymentMethod.CASH_ON_DELIVERY
        db.commit()
        
        # Send confirmation
        whatsapp_service.send_payment_confirmation(
            phone_number,
            {
                "method": "cash",
                "order_number": last_order.order_number
            }
        )
    else:
        whatsapp_service.send_text_message(
            phone_number,
            "Sorry, we couldn't find a pending order to update. Please place a new order first."
        )

async def handle_mpesa_confirmation(phone_number, customer_id, message, db, whatsapp_service: WhatsAppService):
    """Handle M-Pesa confirmation message with improved notifications"""
    # Extract what might be the transaction code
    transaction_code = message.upper()
    
    if len(message) > 12:  # Long message - try to extract code
        # Try to extract just the code from messages like "M-PESA TRANSACTION AB12345678"
        match = re.search(r'[A-Z0-9]{8,12}', transaction_code)
        if match:
            transaction_code = match.group(0)
            logger.info(f"Extracted transaction code: {transaction_code}")
    
    # Find the customer's most recent pending order
    last_order = db.query(models.Order).filter(
        models.Order.customer_id == customer_id,
        models.Order.status == models.OrderStatus.PENDING
    ).order_by(models.Order.created_at.desc()).first()
    
    if last_order:
        # Update the order with payment information
        last_order.payment_method = models.PaymentMethod.MPESA
        last_order.payment_ref = transaction_code
        last_order.payment_status = models.PaymentStatus.PAID  # Mark as paid but not verified
        db.commit()
        logger.info(f"Updated order {last_order.order_number} with M-Pesa payment: {transaction_code}")
        
        # Get group information for more detailed messaging
        group_name = "Our store"
        if last_order.group_id:
            group = db.query(models.Group).filter(models.Group.id == last_order.group_id).first()
            if group:
                group_name = group.name
        
        # Use the payment status update template
        payment_data = {
            "order_number": last_order.order_number,
            "payment_status": last_order.payment_status.value,
            "payment_method": "M-Pesa",
            "payment_ref": transaction_code,
            "amount": last_order.total_amount
        }
        
        whatsapp_service.send_payment_status_update(phone_number, payment_data)
    else:
        logger.warning(f"Received M-Pesa payment but no pending order found for customer {customer_id}")
        whatsapp_service.send_text_message(
            phone_number,
            "Thank you for the payment information, but we couldn't find a pending order. Please place an order first."
        )

async def create_order(phone_number, customer_id, group_id, message, db, whatsapp_service: WhatsAppService):
    """Create a new order from customer details with improved notifications"""
    try:
        logger.info(f"Creating new order for customer {customer_id} in group {group_id}")
        # Create a new order with the text as details
        order = models.Order(
            customer_id=customer_id,
            group_id=group_id,
            order_details=message,
            status=models.OrderStatus.PENDING,
            total_amount=0.00  # This will be updated by the admin later
        )
        
        db.add(order)
        db.commit()
        db.refresh(order)
        logger.info(f"Created new order with ID {order.id}, number {order.order_number}")
        
        # Get group information for more detailed messaging
        group_name = "Our store"
        if group_id:
            group = db.query(models.Group).filter(models.Group.id == group_id).first()
            if group:
                group_name = group.name
        
        # Send order confirmation with payment options
        # We'll continue to use the specific order_confirmation template
        # because it includes the payment buttons
        whatsapp_service.send_order_confirmation(
            phone_number,
            {
                "order_number": order.order_number,
                "items": message,
                "total_amount": order.total_amount,
                "group_name": group_name  
            }
        )
    except Exception as e:
        logger.error(f"Error creating order: {str(e)}")
        whatsapp_service.send_text_message(
            phone_number,
            "Sorry, we couldn't process your order. Please try again or contact support."
        )