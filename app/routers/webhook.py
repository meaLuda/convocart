# app/routers/webhook.py
import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, Request, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.whatsapp import WhatsAppService
from app.config import WEBHOOK_VERIFY_TOKEN
from app import models

router = APIRouter()
logger = logging.getLogger(__name__)
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
        # Get the raw JSON data
        data = await request.json()
        logger.info(f"Received webhook data: {data}")
        
        # Process the webhook event
        event_data = whatsapp_service.process_webhook_event(data)
        if not event_data:
            return {"success": True, "message": "Event processed but no action taken"}
        
        # Check if customer exists, create if not
        customer = db.query(models.Customer).filter(
            models.Customer.phone_number == event_data["phone_number"]
        ).first()
        
        if not customer:
            customer = models.Customer(
                phone_number=event_data["phone_number"],
                name=event_data["name"]
            )
            db.add(customer)
            db.commit()
            db.refresh(customer)
        
        # Handle the event based on message type or content
        await handle_customer_message(customer, event_data, db)
        
        return {"success": True, "message": "Webhook processed successfully"}
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        return {"success": False, "error": str(e)}

async def handle_customer_message(customer, event_data, db):
    """
    Process the customer message and respond accordingly
    """
    phone_number = customer.phone_number
    message = event_data.get("message", "").strip().lower()
    message_type = event_data.get("type")
    
    # Check if this is a feedback response
    if message_type == "button" and event_data.get("button_id", "").startswith("feedback_"):
        feedback_type = event_data.get("button_id").replace("feedback_", "")
        
        # Store the feedback in the database (could add a Feedback model)
        # For now, just acknowledge the feedback
        thank_you_message = "Thank you for your feedback! We appreciate you taking the time to let us know."
        whatsapp_service.send_text_message(phone_number, thank_you_message)
        return
        
    # Check if this is the initial click-to-chat message
    if message.startswith("order from group:"):
        # This is the pre-filled identifier text from click-to-chat link
        group_identifier = message.replace("order from group:", "").strip()
        
        # Look up the group from the database
        group = db.query(models.Group).filter(
            models.Group.identifier == group_identifier
        ).first()
        
        # Default message if group not found
        welcome_message = f"👋 Welcome to our Ordering Bot!\n\nWhat would you like to do today?"
        
        buttons = [
            {"id": "quick_order", "title": "Quick Order"},
            {"id": "list_products", "title": "List Products"},
            {"id": "help", "title": "Help"}
        ]
        
        if group:
            # Use custom welcome message if available
            if group.welcome_message:
                welcome_message = group.welcome_message
            else:
                welcome_message = f"👋 Welcome to our Ordering Bot!\n\nYou've connected through group: {group.name}. What would you like to do?"
            
            # If group has custom products, modify the button options
            if group.products:
                buttons = [
                    {"id": "quick_order", "title": "Quick Order"},
                    {"id": f"list_products_{group.id}", "title": "List Products"},
                    {"id": "help", "title": "Help"}
                ]
        
        whatsapp_service.send_quick_reply_buttons(phone_number, welcome_message, buttons)
        return
    
    # Handle button responses
    if message_type == "button":
        button_id = event_data.get("button_id")
        
        if button_id == "quick_order":
            message = "Please tell us what you'd like to order. Just describe the items you want to purchase."
            whatsapp_service.send_text_message(phone_number, message)
            return
            
        elif button_id == "list_products":
            # In a real app, you would fetch products from database
            products_message = "Here are our available products:\n\n" + \
                              "1. Product A - $10\n" + \
                              "2. Product B - $15\n" + \
                              "3. Product C - $20"
            
            buttons = [
                {"id": "order_productA", "title": "Order Product A"},
                {"id": "order_productB", "title": "Order Product B"},
                {"id": "order_productC", "title": "Order Product C"}
            ]
            
            whatsapp_service.send_quick_reply_buttons(phone_number, products_message, buttons)
            return
            
        elif button_id == "help":
            help_message = "Need help? Here's how to use our ordering bot:\n\n" + \
                          "1. Select 'Quick Order' to place an order directly\n" + \
                          "2. Select 'List Products' to see what we offer\n\n" + \
                          "If you need to speak with a human, reply with 'agent'."
            
            whatsapp_service.send_text_message(phone_number, help_message)
            return
            
        elif button_id.startswith("order_product"):
            # Handle product order button clicks
            product = button_id.replace("order_product", "")
            
            # Create a new order
            order = models.Order(
                customer_id=customer.id,
                order_details=f"Product {product}",
                status="pending",
                total_amount=10.0 if product == "A" else (15.0 if product == "B" else 20.0)
            )
            
            db.add(order)
            db.commit()
            db.refresh(order)
            
            # Send order confirmation
            order_details = {
                "order_id": order.id,
                "items": f"Product {product} x 1",
                "total": order.total_amount
            }
            
            whatsapp_service.send_order_confirmation(phone_number, order_details)
            
            # Ask if they want to add anything else
            follow_up_message = "Is there anything else you'd like to order?"
            
            buttons = [
                {"id": "order_more", "title": "Order More"},
                {"id": "checkout", "title": "Checkout"}
            ]
            
            whatsapp_service.send_quick_reply_buttons(phone_number, follow_up_message, buttons)
            return
    
    # Handle text input for quick order
    if message and len(message) > 3 and not message.startswith("order from group:"):
        # Create a new order from the text message
        order = models.Order(
            customer_id=customer.id,
            order_details=message,
            status="pending",
            # Placeholder amount - in a real app, you would calculate based on items
            total_amount=25.0
        )
        
        db.add(order)
        db.commit()
        db.refresh(order)
        
        # Send order confirmation
        order_details = {
            "order_id": order.id,
            "items": message[:50] + "..." if len(message) > 50 else message,
            "total": order.total_amount
        }
        
        whatsapp_service.send_order_confirmation(phone_number, order_details)
        
        # Provide follow-up options
        follow_up_message = "Thank you for your order! What would you like to do next?"
        
        buttons = [
            {"id": "checkout", "title": "Checkout"},
            {"id": "track_order", "title": "Track Order"},
            {"id": "cancel_order", "title": "Cancel Order"}
        ]
        
        whatsapp_service.send_quick_reply_buttons(phone_number, follow_up_message, buttons)
        return
    
    # Default response for unrecognized messages
    default_message = "I'm not sure what you're asking. Please choose an option below:"
    
    buttons = [
        {"id": "quick_order", "title": "Quick Order"},
        {"id": "list_products", "title": "List Products"},
        {"id": "help", "title": "Help"}
    ]
    
    whatsapp_service.send_quick_reply_buttons(phone_number, default_message, buttons)