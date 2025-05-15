# app/routers/webhook.py
import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
from fastapi import APIRouter, Request, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.whatsapp import WhatsAppService
from app.config import WEBHOOK_VERIFY_TOKEN
from app import models

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
        
        # If we still don't have a customer record, we can't proceed
        if not customer:
            logger.warning(f"No customer found and couldn't create one. Sending help message to {phone_number}")
            # Send a welcome message guiding them to use a proper link
            welcome_msg = "👋 Welcome to our Order Bot!\n\n"
            welcome_msg += "It seems you're trying to place an order, but we couldn't identify which business you're trying to order from.\n\n"
            welcome_msg += "Please use the link that the business shared with you to start your order properly."
            whatsapp_service.send_text_message(phone_number, welcome_msg)
            return {"success": True, "message": "Sent help message to new customer"}
        
        # Now handle the customer's message appropriately
        await handle_customer_message(customer, event_data, db, current_group_id)
        
        return {"success": True, "message": "Webhook processed successfully"}
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        return {"success": False, "error": str(e)}
    

async def handle_customer_message(customer, event_data, db, current_group_id=None):
    """
    Process the customer message and respond accordingly
    """
    phone_number = customer.phone_number
    message = event_data.get("message", "").strip()
    message_type = event_data.get("type")
    
    # Prioritize explicitly provided group_id, then active_group_id, then default group_id
    # This ensures we're always using the correct context
    group_id = current_group_id or customer.active_group_id or customer.group_id
    
    # Debug log to help diagnose issues
    logger.info(f"ORDER CONTEXT: current_group_id={current_group_id}, active_group_id={customer.active_group_id}, default_group_id={customer.group_id}, using={group_id}")
    
    group = db.query(models.Group).filter(models.Group.id == group_id).first()
    
    logger.info(f"Processing message: type={message_type}, content_preview={message[:30]}...")
    
    # STEP 1: Handle the initial welcome/group identification message
    if message_type == "text" and message.lower().startswith("order from group:"):
        group_identifier = message.replace("order from group:", "").strip()
        group = db.query(models.Group).filter(models.Group.identifier == group_identifier).first()
        
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
        return
    
    # STEP 2: Handle button responses
    if message_type == "button":
        button_id = event_data.get("button_id", "")
        logger.info(f"Processing button click: {button_id}")
        
        # Handle main menu options
        if button_id == "place_order":
            place_order_msg = "Please type your order details, including:\n\n"
            place_order_msg += "- Item names\n- Quantities\n- Any special requests\n\n"
            place_order_msg += "Example: 2 t-shirts size L, 1 hoodie black size XL"
            
            whatsapp_service.send_text_message(phone_number, place_order_msg)
            return
            
        elif button_id == "track_order":
            # Find recent orders for this customer
            recent_orders = db.query(models.Order).filter(
                models.Order.customer_id == customer.id
            ).order_by(models.Order.created_at.desc()).limit(3).all()
            
            if not recent_orders:
                whatsapp_service.send_text_message(
                    phone_number,
                    "You don't have any recent orders. Would you like to place a new order?"
                )
                return
                
            # Display recent orders
            orders_message = "📦 *Your Recent Orders*\n\n"
            
            for order in recent_orders:
                # Get emoji for order status
                status_emoji = {
                    models.OrderStatus.PENDING: "🕒",
                    models.OrderStatus.PROCESSING: "⚙️",
                    models.OrderStatus.COMPLETED: "✅",
                    models.OrderStatus.CANCELLED: "❌",
                    models.OrderStatus.REFUNDED: "💰"
                }
                
                emoji = status_emoji.get(order.status, "")
                
                # Format order details
                orders_message += f"{emoji} Order #{order.order_number}\n"
                orders_message += f"Status: {order.status.value.capitalize()}\n"
                orders_message += f"Date: {order.created_at.strftime('%Y-%m-%d %H:%M')}\n"
                orders_message += f"Amount: ${order.total_amount:.2f}\n\n"
            
            whatsapp_service.send_text_message(phone_number, orders_message)
            return
            
        elif button_id == "contact_support":
            support_msg = "Need help with your order? You can contact support:\n\n"
            
            if group and group.contact_phone:
                support_msg += f"📞 Phone: {group.contact_phone}\n"
                
            if group and group.contact_email:
                support_msg += f"📧 Email: {group.contact_email}\n"
            else:
                support_msg += "📧 Email: support@example.com\n"
                
            support_msg += "\nOr reply with your question and we'll get back to you soon!"
            
            whatsapp_service.send_text_message(phone_number, support_msg)
            return
        
        # Handle payment options
        elif button_id == "mpesa_message" or button_id == "pay_with_m-pesa":
            mpesa_msg = "Please send your payment to our M-Pesa number and then share the transaction message/code/confirmation with us."
            whatsapp_service.send_text_message(phone_number, mpesa_msg)
            return
            
        elif button_id == "pay_cash":
            # Update the most recent pending order to cash on delivery
            last_order = db.query(models.Order).filter(
                models.Order.customer_id == customer.id,
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
            return
            
        elif button_id == "cancel_order":
            # Find the customer's last pending order
            last_order = db.query(models.Order).filter(
                models.Order.customer_id == customer.id,
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
            return
            
        # Handle feedback buttons
        elif button_id.startswith("feedback_"):
            feedback_type = button_id.replace("feedback_", "")
            
            # You could store this feedback in a database table
            thank_you_message = "Thank you for your feedback! We appreciate you taking the time to let us know."
            whatsapp_service.send_text_message(phone_number, thank_you_message)
            return
    
    # STEP 3: Handle M-Pesa transaction codes
    # More comprehensive pattern matching for M-Pesa transaction messages
    if message_type == "text" and (
        (len(message) >= 8 and len(message) <= 12 and message.isalnum()) or 
        message.upper().startswith("M-PESA") or 
        "TRANSACTION" in message.upper() or
        "CONFIRMED" in message.upper() or
        "RECEIVED KSH" in message.upper() or
        "MPESA" in message.upper()
    ):
        logger.info(f"Detected M-Pesa transaction message: {message[:30]}...")
        
        # Extract what might be the transaction code
        transaction_code = message.upper()
        import re
        if len(message) > 12:  # Long message - try to extract code
            # Try to extract just the code from messages like "M-PESA TRANSACTION AB12345678"
            match = re.search(r'[A-Z0-9]{8,12}', transaction_code)
            if match:
                transaction_code = match.group(0)
                logger.info(f"Extracted transaction code: {transaction_code}")
        
        # Find the customer's most recent pending order
        last_order = db.query(models.Order).filter(
            models.Order.customer_id == customer.id,
            models.Order.status == models.OrderStatus.PENDING
        ).order_by(models.Order.created_at.desc()).first()
        
        if last_order:
            # Update the order with payment information
            last_order.payment_method = models.PaymentMethod.MPESA
            last_order.payment_ref = transaction_code
            last_order.payment_status = models.PaymentStatus.PAID  # Mark as paid but not verified
            db.commit()
            logger.info(f"Updated order {last_order.order_number} with M-Pesa payment: {transaction_code}")
            
            # Send confirmation
            whatsapp_service.send_payment_confirmation(
                phone_number,
                {
                    "method": "mpesa",
                    "order_number": last_order.order_number,
                    "payment_ref": transaction_code
                }
            )
        else:
            logger.warning(f"Received M-Pesa payment but no pending order found for customer {customer.id}")
            whatsapp_service.send_text_message(
                phone_number,
                "Thank you for the payment information, but we couldn't find a pending order. Please place an order first."
            )
        return  # This return is crucial to prevent falling through to order creation
    
    # STEP 4: Handle order placement from text
    if message_type == "text" and len(message) > 10 and not message.startswith("order from group:"):
        # Double-check this isn't an M-Pesa message that somehow got through the filter
        if (message.upper().startswith("M-PESA") or 
            "TRANSACTION" in message.upper() or 
            "CONFIRMED" in message.upper() or
            "RECEIVED KSH" in message.upper()
        ):
            logger.warning(f"Prevented M-Pesa message from creating order: {message[:30]}...")
            
            # Try to handle it as an M-Pesa message
            # This duplicates the logic from above which isn't ideal but provides a safety net
            # Find the customer's most recent pending order
            last_order = db.query(models.Order).filter(
                models.Order.customer_id == customer.id,
                models.Order.status == models.OrderStatus.PENDING
            ).order_by(models.Order.created_at.desc()).first()
            
            if last_order:
                last_order.payment_method = models.PaymentMethod.MPESA
                last_order.payment_ref = "EXTRACTED_FROM_MESSAGE"
                last_order.payment_status = models.PaymentStatus.PAID
                db.commit()
                
                whatsapp_service.send_payment_confirmation(
                    phone_number,
                    {
                        "method": "mpesa",
                        "order_number": last_order.order_number,
                        "payment_ref": "Your payment"
                    }
                )
            else:
                whatsapp_service.send_text_message(
                    phone_number,
                    "Thank you for the payment information, but we couldn't find a pending order. Please place an order first."
                )
            return
        
        try:
            logger.info(f"Creating new order for customer {customer.id} in group {group_id}")
            # Create a new order with the text as details
            order = models.Order(
                customer_id=customer.id,
                group_id=group_id,
                order_details=message,
                status=models.OrderStatus.PENDING,
                total_amount=0.00  # This will be updated by the admin later
            )
            
            db.add(order)
            db.commit()
            db.refresh(order)
            logger.info(f"Created new order with ID {order.id}, number {order.order_number}")
            
            # Send confirmation with payment options
            whatsapp_service.send_order_confirmation(
                phone_number,
                {
                    "order_number": order.order_number,
                    "items": message,
                    "total_amount": order.total_amount  
                }
            )
        except Exception as e:
            logger.error(f"Error creating order: {str(e)}")
            whatsapp_service.send_text_message(
                phone_number,
                "Sorry, we couldn't process your order. Please try again or contact support."
            )
        return
    
    # STEP 5: Default response for unrecognized messages
    logger.info(f"Unrecognized message, sending default options menu")
    default_message = "I'm not sure what you're asking. Please choose an option below:"
    
    buttons = [
        {"id": "place_order", "title": "Place Order"},
        {"id": "track_order", "title": "Track My Order"},
        {"id": "contact_support", "title": "Contact Support"}
    ]
    
    whatsapp_service.send_quick_reply_buttons(phone_number, default_message, buttons)