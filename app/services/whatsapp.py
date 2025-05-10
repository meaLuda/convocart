# app/services/whatsapp.py
import json
import logging
import requests
from typing import Dict, Any, Optional
from app.config import WHATSAPP_API_URL, WHATSAPP_PHONE_ID, WHATSAPP_API_TOKEN

logger = logging.getLogger(__name__)

class WhatsAppService:
    def __init__(self):
        self.api_url = f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_ID}/messages"
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {WHATSAPP_API_TOKEN}"
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
    
    def send_order_confirmation(self, to: str, order_details: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send an order confirmation message
        """
        # Format the order details as a string
        confirmation_text = f"🛒 *ORDER CONFIRMATION* 🛒\n\n"
        confirmation_text += f"Order #{order_details.get('order_id', 'N/A')}\n"
        confirmation_text += f"Items: {order_details.get('items', 'N/A')}\n"
        confirmation_text += f"Total: ${order_details.get('total', '0.00')}\n\n"
        confirmation_text += "Thank you for your order! 🙏\n"
        confirmation_text += "Your order has been received and is being processed."
        
        return self.send_text_message(to, confirmation_text)
    
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
            
            return None
        except Exception as e:
            logger.error(f"Error processing webhook event: {str(e)}")
            return None