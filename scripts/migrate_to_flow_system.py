"""
Migration script to populate the flow system with initial data and create default flows
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import FlowAction, ActionName, Flow, FlowState, FlowTransition, TriggerType, StateType, Group


def populate_flow_actions(db: Session):
    """Populate the FlowAction table with predefined actions"""
    actions_data = [
        # Order management actions
        (ActionName.CREATE_ORDER, "Create Order", "Creates a new order from customer input"),
        (ActionName.TRACK_ORDER, "Track Order", "Shows order status and tracking information"),
        (ActionName.CANCEL_ORDER, "Cancel Order", "Cancels a pending order"),
        
        # Payment actions
        (ActionName.HANDLE_MPESA_PAYMENT, "Handle M-Pesa Payment", "Processes M-Pesa payment selection"),
        (ActionName.HANDLE_CASH_PAYMENT, "Handle Cash Payment", "Processes cash on delivery payment"),
        (ActionName.HANDLE_PAYMENT_CONFIRMATION, "Handle Payment Confirmation", "Processes payment confirmation messages"),
        
        # Communication actions
        (ActionName.SEND_WELCOME_MESSAGE, "Send Welcome Message", "Sends welcome message to customers"),
        (ActionName.SEND_HELP_MESSAGE, "Send Help Message", "Sends help and support information"),
        (ActionName.SEND_PAYMENT_OPTIONS, "Send Payment Options", "Shows available payment methods"),
        (ActionName.CONTACT_SUPPORT, "Contact Support", "Provides support contact information"),
        
        # System actions
        (ActionName.NO_ACTION, "No Action", "Performs no action during transition"),
        (ActionName.RESET_SESSION, "Reset Session", "Resets the conversation session"),
    ]
    
    for action_name, display_name, description in actions_data:
        existing_action = db.query(FlowAction).filter(FlowAction.action_name == action_name).first()
        if not existing_action:
            action = FlowAction(
                action_name=action_name,
                display_name=display_name,
                description=description,
                is_active=True
            )
            db.add(action)
            print(f"Created action: {display_name}")
    
    db.commit()


def create_default_flow(db: Session, group: Group):
    """Create a default flow for a group that mimics the existing hardcoded behavior"""
    
    # Check if group already has an active flow
    existing_flow = db.query(Flow).filter(
        Flow.group_id == group.id,
        Flow.is_active == True
    ).first()
    
    if existing_flow:
        print(f"Group {group.name} already has an active flow")
        return
    
    # Get flow actions
    actions = {action.action_name: action for action in db.query(FlowAction).all()}
    
    # Create the flow
    flow = Flow(
        group_id=group.id,
        name="Default Order Flow",
        description="Default conversation flow for order processing",
        is_active=True
    )
    db.add(flow)
    db.commit()  # Commit to get flow ID
    db.refresh(flow)
    
    # Create states
    states_data = [
        # (name, message_body, state_type, is_start, state_config)
        ("Initial", None, StateType.AWAIT_RESPONSE, True, None),
        ("Welcome", f"👋 Welcome to {group.name}!\n\n{group.welcome_message or 'What would you like to do?'}", StateType.SEND_MESSAGE, False, {
            "buttons": [
                {"id": "place_order", "title": "Place Order"},
                {"id": "track_order", "title": "Track My Order"}
            ]
        }),
        ("Menu", "What would you like to do? Please choose an option below:", StateType.SEND_MESSAGE, False, {
            "buttons": [
                {"id": "place_order", "title": "Place Order"},
                {"id": "track_order", "title": "Track My Order"},
                {"id": "contact_support", "title": "Contact Support"}
            ]
        }),
        ("Awaiting Order Details", "Please type your order details, including:\n\n- Item names\n- Quantities\n- Any special requests\n\nExample: 2 t-shirts size L, 1 hoodie black size XL", StateType.AWAIT_RESPONSE, False, None),
        ("Payment Options", "Please choose your payment method:", StateType.SEND_MESSAGE, False, {
            "buttons": [
                {"id": "pay_with_m-pesa", "title": "M-Pesa"},
                {"id": "pay_cash", "title": "Cash on Delivery"}
            ]
        }),
        ("Awaiting Payment Confirmation", "Please send your payment to our M-Pesa number and then share the transaction message/code/confirmation with us.", StateType.AWAIT_RESPONSE, False, None),
        ("Order Complete", "Thank you for your order! We'll process it and contact you soon.", StateType.SEND_MESSAGE, False, None)
    ]
    
    # Create states
    states = {}
    for name, message_body, state_type, is_start, state_config in states_data:
        state = FlowState(
            flow_id=flow.id,
            name=name,
            message_body=message_body,
            state_type=state_type,
            is_start_state=is_start,
            state_config=state_config
        )
        db.add(state)
        states[name] = state
    
    db.commit()
    
    # Update flow with start state
    flow.start_state_id = states["Initial"].id
    db.commit()
    
    # Create transitions
    transitions_data = [
        # (source, target, trigger_type, trigger_value, action, priority)
        ("Initial", "Welcome", TriggerType.KEYWORD, "order from group:", ActionName.SEND_WELCOME_MESSAGE, 10),
        ("Initial", "Menu", TriggerType.ANY_TEXT, None, ActionName.NO_ACTION, 1),
        
        ("Welcome", "Menu", TriggerType.SYSTEM, None, ActionName.NO_ACTION, 1),
        
        ("Menu", "Awaiting Order Details", TriggerType.BUTTON_ID, "place_order", ActionName.NO_ACTION, 10),
        ("Menu", "Menu", TriggerType.BUTTON_ID, "track_order", ActionName.TRACK_ORDER, 10),
        ("Menu", "Menu", TriggerType.BUTTON_ID, "contact_support", ActionName.CONTACT_SUPPORT, 10),
        ("Menu", "Awaiting Order Details", TriggerType.KEYWORD, "place order", ActionName.NO_ACTION, 5),
        ("Menu", "Menu", TriggerType.KEYWORD, "track order", ActionName.TRACK_ORDER, 5),
        ("Menu", "Menu", TriggerType.KEYWORD, "support", ActionName.CONTACT_SUPPORT, 5),
        ("Menu", "Menu", TriggerType.KEYWORD, "help", ActionName.SEND_HELP_MESSAGE, 5),
        
        ("Awaiting Order Details", "Payment Options", TriggerType.ANY_TEXT, None, ActionName.CREATE_ORDER, 1),
        
        ("Payment Options", "Order Complete", TriggerType.BUTTON_ID, "pay_cash", ActionName.HANDLE_CASH_PAYMENT, 10),
        ("Payment Options", "Awaiting Payment Confirmation", TriggerType.BUTTON_ID, "pay_with_m-pesa", ActionName.HANDLE_MPESA_PAYMENT, 10),
        
        ("Awaiting Payment Confirmation", "Order Complete", TriggerType.ANY_TEXT, None, ActionName.HANDLE_PAYMENT_CONFIRMATION, 1),
        
        ("Order Complete", "Menu", TriggerType.ANY_TEXT, None, ActionName.NO_ACTION, 1),
        
        # Global help transitions (from any state except Initial)
        ("Welcome", "Welcome", TriggerType.KEYWORD, "help", ActionName.SEND_HELP_MESSAGE, 15),
        ("Menu", "Menu", TriggerType.KEYWORD, "help", ActionName.SEND_HELP_MESSAGE, 15),
        ("Awaiting Order Details", "Awaiting Order Details", TriggerType.KEYWORD, "help", ActionName.SEND_HELP_MESSAGE, 15),
        ("Payment Options", "Payment Options", TriggerType.KEYWORD, "help", ActionName.SEND_HELP_MESSAGE, 15),
        ("Awaiting Payment Confirmation", "Awaiting Payment Confirmation", TriggerType.KEYWORD, "help", ActionName.SEND_HELP_MESSAGE, 15),
        ("Order Complete", "Order Complete", TriggerType.KEYWORD, "help", ActionName.SEND_HELP_MESSAGE, 15),
    ]
    
    for source_name, target_name, trigger_type, trigger_value, action_name, priority in transitions_data:
        transition = FlowTransition(
            source_state_id=states[source_name].id,
            target_state_id=states[target_name].id,
            trigger_type=trigger_type,
            trigger_value=trigger_value,
            action_id=actions[action_name].id if action_name else None,
            priority=priority
        )
        db.add(transition)
    
    db.commit()
    print(f"Created default flow for group: {group.name}")


def main():
    """Main migration function"""
    db = SessionLocal()
    try:
        print("Starting flow system migration...")
        
        # Step 1: Populate flow actions
        print("1. Populating flow actions...")
        populate_flow_actions(db)
        
        # Step 2: Create default flows for all active groups
        print("2. Creating default flows for groups...")
        active_groups = db.query(Group).filter(Group.is_active == True).all()
        
        for group in active_groups:
            create_default_flow(db, group)
        
        print("Flow system migration completed successfully!")
        
    except Exception as e:
        print(f"Error during migration: {str(e)}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()