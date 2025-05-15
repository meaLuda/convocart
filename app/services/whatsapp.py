# app/services/whatsapp.py
import json
import logging
import requests
from typing import Dict, Any, Optional, List
from app.config import WHATSAPP_API_URL, WHATSAPP_PHONE_ID, WHATSAPP_API_TOKEN

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
            api_url = Configuration.get_value(db, 'whatsapp_api_url', WHATSAPP_API_URL)
            phone_id = Configuration.get_value(db, 'whatsapp_phone_id', WHATSAPP_PHONE_ID)
            api_token = Configuration.get_value(db, 'whatsapp_api_token', WHATSAPP_API_TOKEN)
        else:
            # Use environment variables directly
            api_url = WHATSAPP_API_URL
            phone_id = WHATSAPP_PHONE_ID
            api_token = WHATSAPP_API_TOKEN
            
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

    def send_text_message(self, to: str, message: str) -> Dict[str, Any]:
        """
        Send a simple text message to a WhatsApp user
        """
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
                    "id": button["id"],
                    "title": button["title"]
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
                    "text": message
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
        Send an order confirmation message
        """
        # Format order items nicely if provided as JSON
        items_text = ""
        items = order_details.get('items', [])
        
        if isinstance(items, list):
            for i, item in enumerate(items, 1):
                name = item.get('name', 'Unknown item')
                quantity = item.get('quantity', 1)
                price = item.get('price', 0)
                items_text += f"{i}. {name} x{quantity} - ${price:.2f}\n"
        else:
            # Just use the raw text if not in expected format
            items_text = str(items)
        
        confirmation_text = f"📝 *ORDER SAVED*\n"
        confirmation_text += f"Order #: {order_details.get('order_number', 'N/A')}\n\n"
        confirmation_text += f"*Items:*\n{items_text}\n"
        
        if 'total_amount' in order_details:
            # Only show total amount if it's greater than 0
            if order_details['total_amount'] > 0:
                confirmation_text += f"*Total:* ${order_details.get('total_amount', 0):.2f}\n\n"
            
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
        Send a payment confirmation message
        """
        payment_method = payment_details.get('method', 'Unknown')
        order_number = payment_details.get('order_number', 'N/A')
        payment_ref = payment_details.get('payment_ref', 'N/A')
        
        if payment_method == 'mpesa':
            message = f"✅ *PAYMENT INFORMATION SAVED*\n\n"
            message += f"Order #: {order_number}\n"
            message += f"Payment Method: M-Pesa\n"
            message += f"Transaction Code: {payment_ref}\n\n"
            # payment pending confirmation
            message += "Your payment is pending confirmation. Please wait for your group admin to confirm.\n\n"
            message += "Your order has been received and is being processed. Thank you!"
        else:  # cash on delivery
            message = f"✅ *ORDER CONFIRMED*\n\n"
            message += f"Order #: {order_number}\n"
            message += f"Payment Method: Cash on Delivery\n\n"
            message += "Your order has been received and is being processed. You will pay upon delivery. Thank you!"
        
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