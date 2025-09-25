import json
import logging
import requests
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
from twilio.rest import Client
from twilio.base import values
from app.config import get_settings
from app.utils.security import SecurityValidator

settings = get_settings()
logger = logging.getLogger(__name__)

class WhatsAppService:
    def __init__(self, db=None):
        """
        Initialize the WhatsApp service with Twilio configuration
        """
        # Try to get configuration from database if provided
        if db:
            from app.models import Configuration
            # Get values from database with fallback to environment variables
            account_sid = Configuration.get_value(db, 'twilio_account_sid', settings.twilio_account_sid)
            auth_token = Configuration.get_value(db, 'twilio_auth_token', settings.twilio_auth_token)
            whatsapp_number = Configuration.get_value(db, 'twilio_whatsapp_number', settings.twilio_whatsapp_number)
        else:
            # Use environment variables directly
            account_sid = settings.twilio_account_sid
            auth_token = settings.twilio_auth_token
            whatsapp_number = settings.twilio_whatsapp_number
            
        # Log configuration status (without sensitive values)
        logger.info(f"Twilio WhatsApp service initialized with Account SID: {account_sid[:8]}...")
        logger.info(f"Twilio WhatsApp service initialized with Number: {whatsapp_number}")
        logger.debug(f"Twilio Auth Token configured: {'Yes' if auth_token else 'No'}")
        
        # Validate required credentials
        if not account_sid or not auth_token or not whatsapp_number:
            raise ValueError("Missing required Twilio credentials: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_NUMBER")
        
        # Initialize Twilio client
        try:
            self.client = Client(account_sid, auth_token)
            self.whatsapp_number = f"whatsapp:{whatsapp_number}"
            self.db = db
        except Exception as e:
            logger.error(f"Failed to initialize Twilio client: {e}")
            raise

    def _truncate_string(self, text: str, max_length: int) -> str:
        """
        Truncate a string to max_length, adding '...' if truncated.
        """
        if not isinstance(text, str):
            return str(text)
        if len(text) > max_length:
            return text[:max_length - 3] + "..."
        return text

    def send_text_message(self, to: str, message: str) -> Dict[str, Any]:
        """
        Send a simple text message to a WhatsApp user using Twilio
        """
        # Validate inputs
        if not to or not message:
            return {"error": "Missing required parameters: to and message", "success": False}
            
        message = self._truncate_string(message, 1600)  # Twilio WhatsApp message limit
        
        try:
            # Ensure the 'to' number has the whatsapp: prefix
            if not to.startswith('whatsapp:'):
                to = f"whatsapp:{to}"
                
            # Basic phone number validation
            phone_part = to.replace('whatsapp:', '')
            if not phone_part.startswith('+') or len(phone_part) < 8:
                return {"error": f"Invalid phone number format: {phone_part}", "success": False}
                
            twilio_message = self.client.messages.create(
                from_=self.whatsapp_number,
                body=message,
                to=to
            )
            
            # Track message delivery if database is available
            if self.db:
                self._track_message_delivery({
                    "to": to,
                    "type": "text",
                    "text": {"body": message}
                }, {"messages": [{"id": twilio_message.sid}]})
            
            logger.info(f"Text message sent via Twilio: {twilio_message.sid}")
            return {
                "messages": [{"id": twilio_message.sid}],
                "success": True
            }
            
        except Exception as e:
            logger.error(f"Error sending Twilio WhatsApp message: {str(e)}")
            return {"error": str(e), "success": False}
    
    def send_quick_reply_buttons(self, to: str, message: str, buttons: list) -> Dict[str, Any]:
        """
        Send interactive buttons message using Twilio content templates
        Note: Twilio requires pre-approved templates for interactive messages
        For now, we'll send text with numbered options
        """
        if len(buttons) > 3:
            logger.warning("Limiting to 3 buttons for better user experience")
            buttons = buttons[:3]
        
        # Format message with button options
        button_text = "\n\n"
        for i, button in enumerate(buttons, 1):
            title = self._truncate_string(button["title"], 50)
            button_text += f"{i}. {title}\n"
        
        full_message = self._truncate_string(message, 1400) + button_text
        full_message += "\nReply with the number of your choice."
        
        return self.send_text_message(to, full_message)
    
    def send_list_message(self, to: str, message: str, sections: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Send an interactive list message
        Converts to numbered text format since Twilio requires pre-approved templates
        """
        # Truncate message body
        message = self._truncate_string(message, 1000)
        
        list_text = f"{message}\n\n"
        option_num = 1
        
        for section in sections:
            section_title = self._truncate_string(section["title"], 50)
            list_text += f"*{section_title}*\n"
            
            for row in section.get("rows", []):
                row_title = self._truncate_string(row["title"], 50)
                list_text += f"{option_num}. {row_title}"
                
                if "description" in row:
                    description = self._truncate_string(row["description"], 100)
                    list_text += f" - {description}"
                    
                list_text += "\n"
                option_num += 1
            
            list_text += "\n"
        
        list_text += "Reply with the number of your choice."
        
        return self.send_text_message(to, list_text)
    
    def send_order_confirmation(self, to: str, order_details: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send an order confirmation message with enhanced details and KSH currency
        """
        items_text = ""
        items = order_details.get('items', [])
        order_number = self._truncate_string(order_details.get('order_number', 'N/A'), 20)
        total_amount = order_details.get('total_amount', 0)
        group_name = self._truncate_string(order_details.get('group_name', 'Our store'), 100)
        
        if isinstance(items, list):
            for i, item in enumerate(items, 1):
                name = self._truncate_string(item.get('name', 'Unknown item'), 50)
                quantity = item.get('quantity', 1)
                price = item.get('price', 0)
                items_text += f"{i}. {name} x{quantity} - KSH {price:.2f}\n"
        else:
            # Just use the raw text if not in expected format
            items_text = self._truncate_string(str(items), 1000)
        
        confirmation_text = f"📝 *ORDER SAVED*\n"
        confirmation_text += f"Order #: {order_number}\n"
        confirmation_text += f"Store: {group_name}\n\n"
        confirmation_text += f"*Items:*\n{items_text}\n"
        
        if total_amount > 0:
            confirmation_text += f"*Total:* KSH {total_amount:.2f}\n\n"
        
        confirmation_text += "Thank you for your order! 🙏\n"
        confirmation_text += "Your group admin will confirm your order and update you shortly.\n\n"
        confirmation_text += "For payment please confirm the following:\n\n"
        confirmation_text += "1. Paid with M-Pesa\n"
        confirmation_text += "2. Pay on Delivery\n"
        confirmation_text += "3. Cancel Order\n\n"
        confirmation_text += "Reply with the number of your choice."
        
        return self.send_text_message(to, confirmation_text)

    def send_payment_confirmation(self, to: str, payment_details: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send a payment confirmation message with enhanced details
        """
        payment_method = self._truncate_string(payment_details.get('method', 'Unknown'), 50)
        order_number = self._truncate_string(payment_details.get('order_number', 'N/A'), 20)
        payment_ref = self._truncate_string(payment_details.get('payment_ref', 'N/A'), 50)
        amount = payment_details.get('amount', 0)
        
        if payment_method == 'mpesa':
            message = f"✅ *PAYMENT INFORMATION SAVED*\n\n"
            message += f"Order #: {order_number}\n"
            message += f"Payment Method: M-Pesa\n"
            message += f"Transaction Code: {payment_ref}\n"
            
            if amount > 0:
                message += f"Amount: KSH {amount:.2f}\n"
                
            message += "\n"
            message += "Your payment is pending confirmation. Please wait for your group admin to confirm.\n\n"
            message += "Your order has been received and is being processed. Thank you!"
        else:  # cash on delivery
            message = f"✅ *ORDER CONFIRMED*\n\n"
            message += f"Order #: {order_number}\n"
            message += f"Payment Method: Cash on Delivery\n"
            
            if amount > 0:
                message += f"Amount to Pay: KSH {amount:.2f}\n"
                
            message += "\n"
            message += "Your order has been received and is being processed. You will pay upon delivery. Thank you!"
        
        return self.send_text_message(to, message)
    
    def send_order_status_update(self, to: str, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send a comprehensive order status update message
        """
        order_number = self._truncate_string(order_data.get('order_number', 'N/A'), 20)
        status = order_data.get('status', 'unknown')
        group_name = self._truncate_string(order_data.get('group_name', 'Our store'), 100)
        total_amount = order_data.get('total_amount', 0)
        payment_method = self._truncate_string(order_data.get('payment_method', ''), 50)
        payment_status = self._truncate_string(order_data.get('payment_status', ''), 50)
        payment_ref = self._truncate_string(order_data.get('payment_ref', ''), 50)
        order_details = self._truncate_string(order_data.get('order_details', ''), 1000)
        created_at = order_data.get('created_at', '')
        
        # Status emoji mapping
        status_emoji = {
            'pending': '🕒',
            'processing': '⚙️',
            'completed': '✅',
            'cancelled': '❌',
            'refunded': '💰'
        }
        
        emoji = status_emoji.get(status.lower(), '')
        
        # Build message
        message = f"{emoji} *ORDER STATUS UPDATE*\n\n"
        message += f"Your order #{order_number} with {group_name} "
        
        # Status-specific message
        if status.lower() == 'pending':
            message += "is pending processing. We'll update you soon!"
        elif status.lower() == 'processing':
            message += "is now being processed. We're working on it!"
        elif status.lower() == 'completed':
            message += "has been completed. Thank you for your business!"
        elif status.lower() == 'cancelled':
            message += "has been cancelled. Please contact us if you have any questions."
        elif status.lower() == 'refunded':
            message += "has been refunded. The amount will be credited back to your account."
        else:
            message += f"status has been updated to: {status}"
        
        # Order details section
        message += "\n\n*Order Details:*"
        if created_at:
            message += f"\nDate: {created_at}"
        
        if total_amount > 0:
            message += f"\nAmount: KSH {total_amount:.2f}"
        
        # Payment information
        if payment_method:
            message += f"\nPayment Method: {payment_method}"
            
        if payment_status:
            message += f"\nPayment Status: {payment_status}"
            
        if payment_ref:
            message += f"\nReference: {payment_ref}"
        
        # Order items preview
        if order_details:
            message += f"\n\n*Items:*\n{order_details[:100]}"
            if len(order_details) > 100:
                message += "..."
        
        # Send the message
        return self.send_text_message(to, message)

    def send_payment_status_update(self, to: str, payment_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send a payment status update notification
        """
        order_number = self._truncate_string(payment_data.get('order_number', 'N/A'), 20)
        payment_status = self._truncate_string(payment_data.get('payment_status', 'unknown'), 50)
        payment_method = self._truncate_string(payment_data.get('payment_method', ''), 50)
        payment_ref = self._truncate_string(payment_data.get('payment_ref', ''), 50)
        amount = payment_data.get('amount', 0)
        
        # Payment status emoji mapping
        status_emoji = {
            'unpaid': '⏳',
            'paid': '💵',
            'verified': '✅',
            'failed': '❌',
            'refunded': '↩️'
        }
        
        emoji = status_emoji.get(payment_status.lower(), '')
        
        # Build message
        message = f"{emoji} *PAYMENT STATUS UPDATE*\n\n"
        message += f"Order #: {order_number}\n"
        
        if payment_method:
            message += f"Payment Method: {payment_method}\n"
            
        if amount > 0:
            message += f"Amount: KSH {amount:.2f}\n"
            
        if payment_ref:
            message += f"Reference: {payment_ref}\n"
        
        message += f"\nPayment Status: {payment_status.title()}\n\n"
        
        # Status-specific message
        if payment_status.lower() == 'unpaid':
            message += "Your payment is pending. Please complete your payment to process your order."
        elif payment_status.lower() == 'paid':
            message += "We've received your payment and are verifying it. Your order will be processed soon."
        elif payment_status.lower() == 'verified':
            message += "Your payment has been verified. Thank you! Your order is being processed."
        elif payment_status.lower() == 'failed':
            message += "There was an issue with your payment. Please try again or contact support."
        elif payment_status.lower() == 'refunded':
            message += "Your payment has been refunded. The amount will be credited back to your account."
        
        # Send the message
        return self.send_text_message(to, message)

    def _track_message_delivery(self, payload: Dict[str, Any], response: Dict[str, Any]):
        """
        Track sent message for delivery status monitoring
        """
        try:
            from app.models import MessageDeliveryStatus, Customer
            
            # Extract message details
            recipient_phone = payload.get("to")
            message_type = payload.get("type", "text")
            
            # Get message content based on type
            message_content = ""
            if message_type == "text":
                message_content = payload.get("text", {}).get("body", "")
            
            # Get Twilio message ID from response
            messages = response.get("messages", [])
            if not messages:
                return
            
            twilio_message_id = messages[0].get("id")
            if not twilio_message_id:
                return
            
            # Find customer by phone number
            customer = self.db.query(Customer).filter(
                Customer.phone_number == recipient_phone.replace('whatsapp:', '')
            ).first()
            
            # Create delivery tracking record
            delivery_status = MessageDeliveryStatus(
                message_id=twilio_message_id,
                recipient_phone=recipient_phone,
                customer_id=customer.id if customer else None,
                message_type=message_type,
                message_content=message_content,
                current_status="sent"
            )
            
            self.db.add(delivery_status)
            self.db.commit()
            
            logger.debug(f"Tracking delivery for Twilio message {twilio_message_id} to {recipient_phone}")
            
        except Exception as e:
            logger.error(f"Error in message delivery tracking: {str(e)}")
            if self.db:
                self.db.rollback()

    def process_webhook_event(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Process an incoming Twilio webhook event
        Returns customer phone number and message if a text message was received
        """
        try:
            # Twilio webhook format is different from Meta's format
            # Extract basic message information
            message_sid = data.get("MessageSid")
            from_number = data.get("From", "").replace("whatsapp:", "")  # Remove whatsapp: prefix
            to_number = data.get("To", "").replace("whatsapp:", "")
            body = data.get("Body", "")
            message_status = data.get("MessageStatus")
            
            logger.info(f"Twilio webhook: MessageSid={message_sid}, From={from_number}, To={to_number}, Status={message_status}, Body={body[:50] if body else 'None'}")
            
            # Check if this is a status update (delivery receipt)
            if message_status in ["delivered", "read", "failed", "undelivered"] and not body:
                logger.info(f"Processing status update: {message_status} for message {message_sid}")
                return self._process_twilio_status_update(data)
            
            # Check if this is an incoming message (has body and from customer)
            if not from_number or not body:
                logger.warning(f"Incomplete message data - From: {from_number}, Body: {body}")
                return None
            
            # Process as regular text message from customer
            logger.info(f"Received Twilio WhatsApp message from {from_number}: {body[:50]}...")
            
            # For Twilio, we don't get contact names in webhooks
            contact_name = "Unknown"
            
            return {
                "phone_number": from_number,
                "name": contact_name,
                "message": body,
                "type": "text",
                "message_id": message_sid
            }
            
        except Exception as e:
            logger.error(f"Error processing Twilio webhook event: {str(e)}")
            return None
    
    def _process_twilio_status_update(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process Twilio WhatsApp message status updates
        """
        try:
            message_sid = data.get("MessageSid")
            recipient_id = data.get("To", "").replace("whatsapp:", "")
            status = data.get("MessageStatus", "").lower()
            
            logger.info(f"Twilio message status update: {message_sid} -> {status} for {recipient_id}")
            
            # Map Twilio status to our internal status
            status_mapping = {
                "queued": "sent",
                "sending": "sent", 
                "sent": "sent",
                "delivered": "delivered",
                "read": "read",
                "failed": "failed",
                "undelivered": "failed"
            }
            
            internal_status = status_mapping.get(status, status)
            
            return {
                "type": "status_update",
                "message_id": message_sid,
                "recipient_id": recipient_id,
                "status": internal_status,
                "phone_number": recipient_id  # For compatibility
            }
            
        except Exception as e:
            logger.error(f"Error processing Twilio status update: {str(e)}")
            return None
    
    def download_media(self, media_sid: str, media_url: str = None) -> Optional[Dict[str, Any]]:
        """
        Download media from WhatsApp/Twilio and return file information
        """
        try:
            # Create media directory if it doesn't exist
            media_dir = Path("media/whatsapp")
            media_dir.mkdir(parents=True, exist_ok=True)
            
            # Get media resource from Twilio
            if not media_url:
                media_resource = self.client.api.v2010.accounts(self.client.account_sid).messages(media_sid).media.list()[0]
                media_url = f"https://api.twilio.com{media_resource.uri}"
            
            # Make authenticated request to download media
            auth = (self.client.username, self.client.password)
            response = requests.get(media_url, auth=auth, stream=True)
            response.raise_for_status()
            
            # Get content type and validate
            content_type = response.headers.get('content-type', '')
            if not SecurityValidator.validate_media_type(content_type):
                logger.warning(f"Invalid media type: {content_type}")
                return None
            
            # Generate safe filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_extension = self._get_extension_from_content_type(content_type)
            filename = f"{media_sid}_{timestamp}{file_extension}"
            safe_filename = SecurityValidator.sanitize_filename(filename)
            
            # Save file
            file_path = media_dir / safe_filename
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            # Get file size and validate
            file_size = file_path.stat().st_size
            max_size = 16 * 1024 * 1024  # 16MB max
            
            if file_size > max_size:
                logger.warning(f"File too large: {file_size} bytes > {max_size}")
                file_path.unlink()  # Delete file
                return None
            
            logger.info(f"Downloaded media: {safe_filename} ({file_size} bytes)")
            
            return {
                "media_sid": media_sid,
                "filename": safe_filename,
                "file_path": str(file_path),
                "content_type": content_type,
                "file_size": file_size,
                "downloaded_at": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error downloading media {media_sid}: {str(e)}")
            return None
    
    def _get_extension_from_content_type(self, content_type: str) -> str:
        """Get file extension from content type"""
        extensions = {
            'image/jpeg': '.jpg',
            'image/jpg': '.jpg',
            'image/png': '.png',
            'image/gif': '.gif',
            'image/webp': '.webp',
            'audio/aac': '.aac',
            'audio/mp4': '.m4a',
            'audio/mpeg': '.mp3',
            'audio/amr': '.amr',
            'audio/ogg': '.ogg',
            'video/mp4': '.mp4',
            'video/3gpp': '.3gp',
            'application/pdf': '.pdf',
            'text/plain': '.txt',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
            'application/vnd.openxmlformats-officedocument.presentationml.presentation': '.pptx'
        }
        return extensions.get(content_type.lower(), '.bin')
    
    def process_media_message(self, webhook_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Process incoming media message from WhatsApp
        """
        try:
            # Extract media information from webhook
            if webhook_data.get('MessageType') not in ['image', 'audio', 'video', 'document']:
                return None
            
            media_sid = webhook_data.get('MediaSid')
            media_url = webhook_data.get('MediaUrl')
            media_content_type = webhook_data.get('MediaContentType')
            
            if not media_sid:
                logger.warning("No MediaSid in webhook data")
                return None
            
            # Download the media
            media_info = self.download_media(media_sid, media_url)
            if not media_info:
                return None
            
            # Add additional webhook info
            media_info.update({
                "message_sid": webhook_data.get('MessageSid'),
                "from_number": webhook_data.get('From'),
                "message_type": webhook_data.get('MessageType'),
                "caption": webhook_data.get('Body', ''),  # Caption text if any
            })
            
            return media_info
            
        except Exception as e:
            logger.error(f"Error processing media message: {str(e)}")
            return None
    
    def send_media_message(self, to: str, media_url: str, caption: str = "", media_type: str = "image") -> bool:
        """
        Send a media message via WhatsApp
        """
        try:
            to_whatsapp = f"whatsapp:{to}" if not to.startswith('whatsapp:') else to
            from_whatsapp = self.whatsapp_number
            
            if media_type == "image":
                message = self.client.messages.create(
                    body=caption,
                    media_url=media_url,
                    from_=from_whatsapp,
                    to=to_whatsapp
                )
            elif media_type == "document":
                message = self.client.messages.create(
                    body=caption,
                    media_url=media_url,
                    from_=from_whatsapp,
                    to=to_whatsapp
                )
            else:
                # For audio/video, similar approach
                message = self.client.messages.create(
                    body=caption,
                    media_url=media_url,
                    from_=from_whatsapp,
                    to=to_whatsapp
                )
            
            logger.info(f"Sent {media_type} message {message.sid} to {to}")
            return True
            
        except Exception as e:
            logger.error(f"Error sending {media_type} message: {str(e)}")
            return False


# Helper function to get an initialized WhatsApp service
def get_whatsapp_service(db=None):
    """
    Get a WhatsApp service instance with current Twilio configuration
    """
    return WhatsAppService(db)