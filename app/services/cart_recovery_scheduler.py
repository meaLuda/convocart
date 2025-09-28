"""
Automated Cart Recovery Scheduler
Background task scheduler for detecting and recovering abandoned carts
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.services.whatsapp import WhatsAppService
from app.services.cart_abandonment_service import get_cart_abandonment_service
from app.models import CartSession, CartRecoveryCampaign

logger = logging.getLogger(__name__)

class CartRecoveryScheduler:
    """Scheduler for automated cart recovery campaigns"""
    
    def __init__(self):
        self.whatsapp_service = WhatsAppService()
        self.is_running = False
    
    async def start_scheduler(self):
        """Start the background scheduler"""
        self.is_running = True
        logger.info("Cart Recovery Scheduler started")
        
        while self.is_running:
            try:
                await self.run_recovery_cycle()
                # Run every 30 minutes
                await asyncio.sleep(30 * 60)
            except Exception as e:
                logger.error(f"Error in recovery cycle: {e}")
                await asyncio.sleep(5 * 60)  # Wait 5 minutes before retry
    
    def stop_scheduler(self):
        """Stop the scheduler"""
        self.is_running = False
        logger.info("Cart Recovery Scheduler stopped")
    
    async def run_recovery_cycle(self):
        """Run a complete recovery cycle"""
        db = SessionLocal()
        try:
            abandonment_service = get_cart_abandonment_service(db)
            
            # Step 1: Detect new abandonments
            abandoned_carts = abandonment_service.detect_abandonment()
            logger.info(f"Detected {len(abandoned_carts)} newly abandoned carts")
            
            # Step 2: Process recovery campaigns for eligible carts
            await self.process_recovery_campaigns(abandonment_service, db)
            
            # Step 3: Clean up expired carts
            self.cleanup_expired_carts(db)
            
        finally:
            db.close()
    
    async def process_recovery_campaigns(self, abandonment_service, db: Session):
        """Process recovery campaigns for eligible abandoned carts"""
        # Get all abandoned carts eligible for recovery
        eligible_carts = db.query(CartSession).filter(
            CartSession.status == CartSession.CartStatus.ABANDONED
        ).all()
        
        campaigns_sent = 0
        for cart in eligible_carts:
            if cart.is_eligible_for_recovery():
                campaign = abandonment_service.create_recovery_campaign(cart)
                if campaign:
                    # Send the recovery message
                    success = abandonment_service.send_recovery_message(
                        campaign, self.whatsapp_service
                    )
                    if success:
                        campaigns_sent += 1
                    
                    # Add delay between messages to avoid rate limiting
                    await asyncio.sleep(2)
        
        logger.info(f"Sent {campaigns_sent} recovery campaigns")
    
    def cleanup_expired_carts(self, db: Session):
        """Clean up carts that are too old to recover"""
        expiry_threshold = datetime.utcnow() - timedelta(days=7)
        
        expired_carts = db.query(CartSession).filter(
            CartSession.status == CartSession.CartStatus.ABANDONED,
            CartSession.abandoned_at < expiry_threshold
        ).all()
        
        for cart in expired_carts:
            cart.status = CartSession.CartStatus.EXPIRED
        
        db.commit()
        logger.info(f"Marked {len(expired_carts)} carts as expired")


# Celery task integration (if using Celery)
from celery import Celery

app = Celery('cart_recovery', broker='redis://localhost:6379/0', backend='redis://localhost:6379/0')

@app.task
def detect_and_recover_abandoned_carts():
    """Celery task for cart recovery"""
    db = SessionLocal()
    try:
        abandonment_service = get_cart_abandonment_service(db)
        whatsapp_service = WhatsAppService()
        
        # Detect abandonments
        abandoned_carts = abandonment_service.detect_abandonment()
        
        # Process recovery campaigns
        campaigns_sent = 0
        for cart in abandoned_carts:
            if cart.is_eligible_for_recovery():
                campaign = abandonment_service.create_recovery_campaign(cart)
                if campaign:
                    success = abandonment_service.send_recovery_message(
                        campaign, whatsapp_service
                    )
                    if success:
                        campaigns_sent += 1
        
        return {
            "abandoned_carts_detected": len(abandoned_carts),
            "recovery_campaigns_sent": campaigns_sent
        }
    finally:
        db.close()

# Schedule the task to run every 30 minutes
app.conf.beat_schedule = {
    'cart-recovery': {
        'task': 'cart_recovery_scheduler.detect_and_recover_abandoned_carts',
        'schedule': 30 * 60,  # 30 minutes
    },
}