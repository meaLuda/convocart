import json
import logging
import re
from typing import Dict, Any, Optional, List
from datetime import datetime
from fastapi import APIRouter, Request, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.whatsapp import WhatsAppService
from app.services.flow_engine import GenericFlowEngine
from app import models
from app.models import ConversationState
from app.config import get_settings

SETTINGS = get_settings()

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
    if hub_mode == "subscribe" and hub_verify_token == SETTINGS.webhook_verify_token:
        logger.info("Webhook verified successfully")
        return int(hub_challenge)
    
    logger.warning("Webhook verification failed")
    raise HTTPException(status_code=403, detail="Verification failed")

async def _get_customer_and_group(db: Session, phone_number: str, message: str, event_data: Dict[str, Any]):
    customer = db.query(models.Customer).filter(
        models.Customer.phone_number == phone_number
    ).first()

    group_identifier = None
    if message.startswith("order from group:"):
        group_identifier = message.replace("order from group:", "").strip()
        group_identifier = group_identifier.lower().replace(" ", "-")
        group_identifier = re.sub(r'[^a-z0-9_-]', '', group_identifier)

    group = None
    if group_identifier:
        group = db.query(models.Group).filter(
            models.Group.identifier == group_identifier,
            models.Group.is_active == True
        ).first()

    if group:
        if not customer:
            customer = models.Customer(
                phone_number=phone_number,
                name=event_data.get("name", "New Customer"),
                group_id=group.id,
                active_group_id=group.id
            )
            db.add(customer)
            db.commit()
            db.refresh(customer)
        else:
            customer.active_group_id = group.id
            db.commit()
        
        session = models.ConversationSession.get_or_create_session(db, customer.id)
        session.update_state(ConversationState.INITIAL)
        db.commit()

    return customer, group

@router.post("/webhook")
async def process_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Process incoming webhook events from WhatsApp
    """
    try:
        data = await request.json()
        event_data = whatsapp_service.process_webhook_event(data)
        
        if not event_data or not event_data.get("phone_number"):
            return {"success": True, "message": "Event processed but no action taken"}

        phone_number = event_data.get("phone_number")
        message = event_data.get("message", "").strip()

        customer, group = await _get_customer_and_group(db, phone_number, message, event_data)

        if not customer:
            welcome_msg = "👋 Welcome to our Order Bot!\n\nIt seems you\'re trying to place an order, but we couldn\'t identify which business you\'re trying to order from.\n\nPlease use the link that the business shared with you to start your order properly."
            whatsapp_service.send_text_message(phone_number, welcome_msg)
            return {"success": True, "message": "Sent help message to new customer"}

        flow_engine = GenericFlowEngine(db, whatsapp_service)
        await flow_engine.process_message(customer, event_data, group.id if group else None)
        
        return {"success": True, "message": "Webhook processed successfully"}
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        return {"success": False, "error": str(e)}

