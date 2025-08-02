import json
import logging
import requests
from typing import Dict, Any, Optional, List
from app.config import get_settings

settings = get_settings()


logger = logging.getLogger(__name__)

class WhatsAppService:
    def __init__(self, db=None):
        """
        Initialize the WhatsApp service with configuration from database or environment variables
        """
        # Try to get configuration from database if provided
        if db:
            from app.models import Configuration
            # Get values from database with fallback to environment variables
            api_url = Configuration.get_value(db, 'whatsapp_api_url', settings.whatsapp_api_url )
            phone_id = Configuration.get_value(db, 'whatsapp_phone_id',settings.whatsapp_phone_id)
            api_token = Configuration.get_value(db, 'whatsapp_api_token', settings.whatsapp_api_token)
        else:
            # Use environment variables directly
            api_url = settings.whatsapp_api_url
            phone_id = settings.whatsapp_phone_id
            api_token = settings.whatsapp_api_token
            
        # Log configuration status (without sensitive values)
        logger.info(f"WhatsApp service initialized with API URL: {api_url}")
        logger.info(f"WhatsApp service initialized with Phone ID: {phone_id}")
        logger.debug(f"WhatsApp service API token configured: {'Yes' if api_token else 'No'}")
        
        # Set up the API URL and headers as in original implementation
        self.api_url = f"{api_url}/{phone_id}/messages"
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_token}"
        }

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
        Send a simple text message to a WhatsApp user
        """
        message = self._truncate_string(message, 4096) # WhatsApp text message limit
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": message
            }
        }
        
        return self._make_request(payload)
    
    def send_quick_reply_buttons(self, to: str, message: str, buttons: list) -> Dict[str, Any]:
        """
        Send interactive buttons message
        buttons should be a list of dictionaries with 'id' and 'title' keys
        """
        if len(buttons) > 3:
            logger.warning("WhatsApp only supports up to 3 quick reply buttons, truncating list")
            buttons = buttons[:3]
            
        button_items = [
            {
                "type": "reply",
                "reply": {
                    "id": self._truncate_string(button["id"], 256), # Button ID limit
                    "title": self._truncate_string(button["title"], 20) # Button title limit
                }
            } for button in buttons
        ]
        
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {
                    "text": self._truncate_string(message, 1024) # Interactive message body limit
                },
                "action": {
                    "buttons": button_items
                }
            }
        }
        
        return self._make_request(payload)
    
    def send_list_message(self, to: str, message: str, sections: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Send an interactive list message
        sections: list of section dictionaries with 'title' and 'rows' keys
        """
        # Truncate message body
        message = self._truncate_string(message, 1024) # Interactive message body limit

        # Truncate section and row titles/descriptions
        for section in sections:
            section["title"] = self._truncate_string(section["title"], 24) # Section title limit
            for row in section.get("rows", []):
                row["id"] = self._truncate_string(row["id"], 256) # Row ID limit
                row["title"] = self._truncate_string(row["title"], 24) # Row title limit
                if "description" in row:
                    row["description"] = self._truncate_string(row["description"], 72) # Row description limit

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {
                    "text": message
                },
                "action": {
                    "button": "View Options",
                    "sections": sections
                }
            }
        }
        
        return self._make_request(payload)
    
    def send_order_confirmation(self, to: str, order_details: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send an order confirmation message with enhanced details and KSH currency
        """
        items_text = ""
        items = order_details.get('items', [])
        order_number = self._truncate_string(order_details.get('order_number', 'N/A'), 20) # Order number limit
        total_amount = order_details.get('total_amount', 0)
        group_name = self._truncate_string(order_details.get('group_name', 'Our store'), 100) # Group name limit
        
        if isinstance(items, list):
            for i, item in enumerate(items, 1):
                name = self._truncate_string(item.get('name', 'Unknown item'), 50) # Item name limit
                quantity = item.get('quantity', 1)
                price = item.get('price', 0)
                items_text += f"{i}. {name} x{quantity} - KSH {price:.2f}\n"
        else:
            # Just use the raw text if not in expected format
            items_text = self._truncate_string(str(items), 1000) # Items text limit
        
        confirmation_text = f"📝 *ORDER SAVED*\n"
        confirmation_text += f"Order #: {order_number}\n"
        confirmation_text += f"Store: {group_name}\n\n"
        confirmation_text += f"*Items:*\n{items_text}\n"
        
        if total_amount > 0:
            confirmation_text += f"*Total:* KSH {total_amount:.2f}\n\n"
        
        confirmation_text += "Thank you for your order! 🙏\n"
        confirmation_text += "Your group admin will confirm your order and update you shortly.\n\n"
        confirmation_text += "For payment please confirm the following.\n\n"
        
        # Add payment options buttons
        buttons = [
            {"id": "mpesa_message", "title": "Paid with M-Pesa"},
            {"id": "pay_cash", "title": "Pay on Delivery"},
            {"id": "cancel_order", "title": "Cancel Order"}
        ]
        
        return self.send_quick_reply_buttons(to, confirmation_text, buttons)

    def send_payment_confirmation(self, to: str, payment_details: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send a payment confirmation message with enhanced details
        """
        payment_method = self._truncate_string(payment_details.get('method', 'Unknown'), 50) # Payment method limit
        order_number = self._truncate_string(payment_details.get('order_number', 'N/A'), 20) # Order number limit
        payment_ref = self._truncate_string(payment_details.get('payment_ref', 'N/A'), 50) # Payment ref limit
        amount = payment_details.get('amount', 0)
        
        if payment_method == 'mpesa':
            message = f"✅ *PAYMENT INFORMATION SAVED*\n\n"
            message += f"Order #: {order_number}\n"
            message += f"Payment Method: M-Pesa\n"
            message += f"Transaction Code: {payment_ref}\n"
            
            if amount > 0:
                message += f"Amount: KSH {amount:.2f}\n"
                
            message += "\n"
            # payment pending confirmation
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
        order_number = self._truncate_string(order_data.get('order_number', 'N/A'), 20) # Order number limit
        status = order_data.get('status', 'unknown')
        group_name = self._truncate_string(order_data.get('group_name', 'Our store'), 100) # Group name limit
        total_amount = order_data.get('total_amount', 0)
        payment_method = self._truncate_string(order_data.get('payment_method', ''), 50) # Payment method limit
        payment_status = self._truncate_string(order_data.get('payment_status', ''), 50) # Payment status limit
        payment_ref = self._truncate_string(order_data.get('payment_ref', ''), 50) # Payment ref limit
        order_details = self._truncate_string(order_data.get('order_details', ''), 1000) # Order details limit
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
        order_number = self._truncate_string(payment_data.get('order_number', 'N/A'), 20) # Order number limit
        payment_status = self._truncate_string(payment_data.get('payment_status', 'unknown'), 50) # Payment status limit
        payment_method = self._truncate_string(payment_data.get('payment_method', ''), 50) # Payment method limit
        payment_ref = self._truncate_string(payment_data.get('payment_ref', ''), 50) # Payment ref limit
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

    def _make_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Make a request to the WhatsApp API
        """
        try:
            response = requests.post(
                self.api_url,
                headers=self.headers,
                data=json.dumps(payload)
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Error sending WhatsApp message: {str(e)}")
            return {"error": str(e)}

    def process_webhook_event(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Process an incoming webhook event
        Returns customer phone number and message if a text message was received
        """
        try:
            # Check if this is a valid webhook event with message data
            if not data or "object" not in data or data["object"] != "whatsapp_business_account":
                return None
                
            # Extract entry data
            entries = data.get("entry", [])
            if not entries:
                return None
                
            # Process each entry (usually there's just one)
            for entry in entries:
                changes = entry.get("changes", [])
                for change in changes:
                    if change.get("field") != "messages":
                        continue
                        
                    value = change.get("value", {})
                    if "messages" not in value:
                        continue
                        
                    messages = value.get("messages", [])
                    if not messages:
                        continue
                        
                    # Process the first message
                    message = messages[0]
                    
                    # Get sender info
                    contacts = value.get("contacts", [])
                    contact_name = contacts[0].get("profile", {}).get("name") if contacts else "Unknown"
                    
                    message_type = message.get("type")
                    from_number = message.get("from")
                    
                    if message_type == "text":
                        # It's a text message
                        text_body = message.get("text", {}).get("body", "")
                        return {
                            "phone_number": from_number,
                            "name": contact_name,
                            "message": text_body,
                            "type": "text"
                        }
                    elif message_type == "interactive":
                        # It's an interactive message (button click, etc.)
                        interactive = message.get("interactive", {})
                        
                        if interactive.get("type") == "button_reply":
                            button_reply = interactive.get("button_reply", {})
                            button_id = button_reply.get("id", "")
                            button_title = button_reply.get("title", "")
                            
                            return {
                                "phone_number": from_number,
                                "name": contact_name,
                                "message": button_title,
                                "button_id": button_id,
                                "type": "button"
                            }
                        elif interactive.get("type") == "list_reply":
                            list_reply = interactive.get("list_reply", {})
                            list_id = list_reply.get("id", "")
                            list_title = list_reply.get("title", "")
                            
                            return {
                                "phone_number": from_number,
                                "name": contact_name,
                                "message": list_title,
                                "list_id": list_id,
                                "type": "list"
                            }
            
            return None
        except Exception as e:
            logger.error(f"Error processing webhook event: {str(e)}")
            return None

# Helper function to get an initialized WhatsApp service
def get_whatsapp_service(db=None):
    """
    Get a WhatsApp service instance with current configuration
    """
    return WhatsAppService(db)