"""
Generic Flow Engine for processing customer conversations based on database-defined flows
"""
import logging
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from app import models
from app.models import TriggerType, ActionName
from app.services.whatsapp import WhatsAppService

logger = logging.getLogger(__name__)


class FlowActionHandler:
    """Handles execution of predefined flow actions"""
    
    def __init__(self, db: Session, whatsapp_service: WhatsAppService):
        self.db = db
        self.whatsapp_service = whatsapp_service
    
    async def execute_action(self, action_name: ActionName, context: Dict[str, Any]) -> bool:
        """Execute a specific action and return success status"""
        try:
            action_map = {
                ActionName.CREATE_ORDER: self._create_order,
                ActionName.TRACK_ORDER: self._track_order,
                ActionName.CANCEL_ORDER: self._cancel_order,
                ActionName.HANDLE_MPESA_PAYMENT: self._handle_mpesa_payment,
                ActionName.HANDLE_CASH_PAYMENT: self._handle_cash_payment,
                ActionName.HANDLE_PAYMENT_CONFIRMATION: self._handle_payment_confirmation,
                ActionName.SEND_WELCOME_MESSAGE: self._send_welcome_message,
                ActionName.SEND_HELP_MESSAGE: self._send_help_message,
                ActionName.SEND_PAYMENT_OPTIONS: self._send_payment_options,
                ActionName.CONTACT_SUPPORT: self._contact_support,
                ActionName.NO_ACTION: self._no_action,
                ActionName.RESET_SESSION: self._reset_session,
            }
            
            handler = action_map.get(action_name)
            if handler:
                await handler(context)
                return True
            else:
                logger.warning(f"Unknown action: {action_name}")
                return False
                
        except Exception as e:
            logger.error(f"Error executing action {action_name}: {str(e)}")
            return False
    
    async def _create_order(self, context: Dict[str, Any]):
        """Create a new order"""
        from app.routers.webhook import create_order
        await create_order(
            context["phone_number"],
            context["customer_id"],
            context["group_id"],
            context["message"],
            self.db,
            self.whatsapp_service
        )
    
    async def _track_order(self, context: Dict[str, Any]):
        """Track existing orders"""
        from app.routers.webhook import handle_track_order
        await handle_track_order(
            context["phone_number"],
            context["customer_id"],
            self.db,
            self.whatsapp_service
        )
    
    async def _cancel_order(self, context: Dict[str, Any]):
        """Cancel an order"""
        from app.routers.webhook import handle_cancel_order
        await handle_cancel_order(
            context["phone_number"],
            context["customer_id"],
            self.db,
            self.whatsapp_service
        )
    
    async def _handle_mpesa_payment(self, context: Dict[str, Any]):
        """Handle M-Pesa payment selection"""
        phone_number = context["phone_number"]
        mpesa_msg = "Please send your payment to our M-Pesa number and then share the transaction message/code/confirmation with us."
        self.whatsapp_service.send_text_message(phone_number, mpesa_msg)
    
    async def _handle_cash_payment(self, context: Dict[str, Any]):
        """Handle cash payment selection"""
        from app.routers.webhook import handle_cash_payment
        await handle_cash_payment(
            context["phone_number"],
            context["customer_id"],
            self.db,
            self.whatsapp_service
        )
    
    async def _handle_payment_confirmation(self, context: Dict[str, Any]):
        """Handle payment confirmation"""
        from app.routers.webhook import handle_mpesa_confirmation
        await handle_mpesa_confirmation(
            context["phone_number"],
            context["customer_id"],
            context["message"],
            self.db,
            self.whatsapp_service
        )
    
    async def _send_welcome_message(self, context: Dict[str, Any]):
        """Send welcome message"""
        from app.routers.webhook import send_welcome_message
        group = self.db.query(models.Group).filter(models.Group.id == context["group_id"]).first()
        await send_welcome_message(
            context["phone_number"],
            group,
            self.whatsapp_service
        )
    
    async def _send_help_message(self, context: Dict[str, Any]):
        """Send help message"""
        from app.routers.webhook import send_help_message
        group = self.db.query(models.Group).filter(models.Group.id == context["group_id"]).first()
        await send_help_message(
            context["phone_number"],
            group,
            self.whatsapp_service
        )
    
    async def _send_payment_options(self, context: Dict[str, Any]):
        """Send payment options"""
        phone_number = context["phone_number"]
        payment_msg = "Please choose your payment method:"
        buttons = [
            {"id": "pay_with_m-pesa", "title": "M-Pesa"},
            {"id": "pay_cash", "title": "Cash on Delivery"}
        ]
        self.whatsapp_service.send_quick_reply_buttons(phone_number, payment_msg, buttons)
    
    async def _contact_support(self, context: Dict[str, Any]):
        """Handle contact support"""
        from app.routers.webhook import handle_contact_support
        group = self.db.query(models.Group).filter(models.Group.id == context["group_id"]).first()
        await handle_contact_support(
            context["phone_number"],
            group,
            self.whatsapp_service
        )
    
    async def _no_action(self, context: Dict[str, Any]):
        """No action - used for state transitions without side effects"""
        pass
    
    async def _reset_session(self, context: Dict[str, Any]):
        """Reset conversation session"""
        session = context.get("session")
        if session:
            session.is_active = False
            self.db.commit()


class GenericFlowEngine:
    """Generic conversation flow engine that reads flow definitions from database"""
    
    def __init__(self, db: Session, whatsapp_service: WhatsAppService):
        self.db = db
        self.whatsapp_service = whatsapp_service
        self.action_handler = FlowActionHandler(db, whatsapp_service)
    
    async def process_message(self, customer: models.Customer, event_data: Dict[str, Any], current_group_id: Optional[int] = None):
        """Process a customer message using the flow engine"""
        phone_number = customer.phone_number
        message = event_data.get("message", "").strip()
        message_type = event_data.get("type")
        button_id = event_data.get("button_id", "") if message_type == "button" else None
        
        # Determine group context
        group_id = current_group_id or customer.active_group_id or customer.group_id
        
        # Get or create conversation session
        session = models.ConversationSession.get_or_create_session(self.db, customer.id)
        
        # Load active flow for the group
        active_flow = self.db.query(models.Flow).filter(
            models.Flow.group_id == group_id,
            models.Flow.is_active == True
        ).first()
        
        if not active_flow:
            logger.warning(f"No active flow found for group {group_id}")
            await self._send_fallback_message(phone_number)
            return
        
        # Get current state
        current_state_name = session.current_state
        current_state = None
        
        # Find current state in the flow
        for state in active_flow.states:
            if state.name.lower().replace(" ", "_") == current_state_name.lower():
                current_state = state
                break
        
        # If no matching state found, start from the beginning
        if not current_state:
            if active_flow.start_state:
                current_state = active_flow.start_state
            else:
                # Find the state marked as start state
                current_state = next((state for state in active_flow.states if state.is_start_state), None)
                if not current_state and active_flow.states:
                    current_state = active_flow.states[0]  # Fallback to first state
        
        if not current_state:
            logger.error(f"No valid state found for flow {active_flow.id}")
            await self._send_fallback_message(phone_number)
            return
        
        logger.info(f"Processing message in state: {current_state.name} for customer {customer.id}")
        
        # Find matching transition
        matching_transition = await self._find_matching_transition(
            current_state, message, message_type, button_id
        )
        
        if matching_transition:
            # Execute transition action if present
            if matching_transition.action:
                context = {
                    "phone_number": phone_number,
                    "customer_id": customer.id,
                    "group_id": group_id,
                    "message": message,
                    "session": session,
                    "current_state": current_state,
                    "target_state": matching_transition.target_state
                }
                
                await self.action_handler.execute_action(
                    matching_transition.action.action_name, context
                )
            
            # Transition to new state
            new_state = matching_transition.target_state
            session.update_state(new_state.name.lower().replace(" ", "_"))
            self.db.commit()
            
            # Send message for new state if it has one
            if new_state.message_body:
                # Handle state configuration for buttons
                state_config = new_state.state_config or {}
                buttons = state_config.get("buttons", [])
                
                if buttons:
                    self.whatsapp_service.send_quick_reply_buttons(
                        phone_number, new_state.message_body, buttons
                    )
                else:
                    self.whatsapp_service.send_text_message(phone_number, new_state.message_body)
        else:
            # No matching transition found, send fallback or stay in current state
            await self._handle_no_matching_transition(phone_number, current_state, message)
    
    async def _find_matching_transition(self, current_state: models.FlowState, message: str, message_type: str, button_id: Optional[str]) -> Optional[models.FlowTransition]:
        """Find a transition that matches the current input"""
        # Get all transitions from current state, ordered by priority (descending)
        transitions = sorted(
            current_state.outgoing_transitions,
            key=lambda t: t.priority,
            reverse=True
        )
        
        for transition in transitions:
            if await self._matches_trigger(transition, message, message_type, button_id):
                return transition
        
        return None
    
    async def _matches_trigger(self, transition: models.FlowTransition, message: str, message_type: str, button_id: Optional[str]) -> bool:
        """Check if a transition's trigger matches the current input"""
        trigger_type = transition.trigger_type
        trigger_value = transition.trigger_value
        
        if trigger_type == TriggerType.BUTTON_ID:
            return button_id == trigger_value
        
        elif trigger_type == TriggerType.KEYWORD:
            if message_type == "text" and trigger_value:
                return message.lower().strip() == trigger_value.lower().strip()
        
        elif trigger_type == TriggerType.ANY_TEXT:
            return message_type == "text" and len(message.strip()) > 0
        
        elif trigger_type == TriggerType.SYSTEM:
            # System triggers are for automatic transitions, not user input
            return False
        
        return False
    
    async def _handle_no_matching_transition(self, phone_number: str, current_state: models.FlowState, message: str):
        """Handle case where no transition matches the input"""
        # If current state has a message, resend it (stay in state)
        if current_state.message_body:
            fallback_msg = f"I didn't understand that. {current_state.message_body}"
            
            state_config = current_state.state_config or {}
            buttons = state_config.get("buttons", [])
            
            if buttons:
                self.whatsapp_service.send_quick_reply_buttons(phone_number, fallback_msg, buttons)
            else:
                self.whatsapp_service.send_text_message(phone_number, fallback_msg)
        else:
            await self._send_fallback_message(phone_number)
    
    async def _send_fallback_message(self, phone_number: str):
        """Send a generic fallback message"""
        fallback_msg = "I'm sorry, I didn't understand that. Please try again or contact support."
        self.whatsapp_service.send_text_message(phone_number, fallback_msg)