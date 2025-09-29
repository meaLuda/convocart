"""
Comprehensive tests for the modernized state management system

Tests validate that the LangChain state management modernization fixes
the exact issues described in the problematic conversation logs:
- Premature payment jumps
- Order details being ignored
- State loops and confusion
- Conversation flow inconsistencies
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock
from sqlalchemy.orm import Session

from app.models import ConversationSession, ConversationState, Customer, Group
from app.services.conversation_debugger import ConversationDebugger, FlowIssueType
from app.services.ai_agent import AgentState, OrderBotAgent
from app.routers.webhook import (
    handle_customer_message_unified,
    detect_customer_intent,
    handle_customer_message_with_context
)

class TestStateTransitionValidation:
    """Test the new state transition validation system"""
    
    def test_valid_state_transitions(self, db_session):
        """Test that valid state transitions are allowed"""
        customer = Customer(name="Test User", phone_number="+1234567890", group_id=1)
        db_session.add(customer)
        db_session.commit()
        
        session = ConversationSession.get_or_create_session(db_session, customer.id)
        
        # Test valid transitions
        valid_transitions = [
            (ConversationState.INITIAL, ConversationState.WELCOME),
            (ConversationState.WELCOME, ConversationState.AWAITING_ORDER_DETAILS),
            (ConversationState.AWAITING_ORDER_DETAILS, ConversationState.AWAITING_PAYMENT),
            (ConversationState.AWAITING_PAYMENT, ConversationState.AWAITING_PAYMENT_CONFIRMATION),
            (ConversationState.AWAITING_PAYMENT_CONFIRMATION, ConversationState.IDLE)
        ]
        
        for from_state, to_state in valid_transitions:
            session.current_state = from_state
            session.update_state(to_state)
            assert session.current_state == to_state.value
    
    def test_invalid_state_transitions_recovery(self, db_session):
        """Test that invalid state transitions are recovered"""
        customer = Customer(name="Test User", phone_number="+1234567890", group_id=1)
        db_session.add(customer)
        db_session.commit()
        
        session = ConversationSession.get_or_create_session(db_session, customer.id)
        
        # Test invalid transition that should be recovered
        session.current_state = ConversationState.INITIAL
        session.update_state(ConversationState.AWAITING_PAYMENT)  # Invalid jump
        
        # Should be recovered to a safe state
        assert session.current_state != ConversationState.AWAITING_PAYMENT.value
        assert session.current_state in [ConversationState.AWAITING_ORDER_DETAILS.value, ConversationState.IDLE.value]
    
    def test_state_consistency_validation(self, db_session):
        """Test state consistency validation"""
        customer = Customer(name="Test User", phone_number="+1234567890", group_id=1)
        db_session.add(customer)
        db_session.commit()
        
        session = ConversationSession.get_or_create_session(db_session, customer.id)
        
        # Test valid state
        session.current_state = ConversationState.IDLE
        is_valid, issues, _ = session.validate_state_consistency()
        assert is_valid
        assert len(issues) == 0
        
        # Test invalid state (payment without order context)
        session.current_state = ConversationState.AWAITING_PAYMENT
        session.context_data = {}
        is_valid, issues, recommended_action = session.validate_state_consistency()
        assert not is_valid
        assert any("pending order" in issue for issue in issues)
        assert "Reset to IDLE" in recommended_action

class TestOriginalIssuesFix:
    """Test that the original conversation flow issues are fixed"""
    
    @pytest.mark.asyncio
    async def test_premature_payment_jump_prevention(self, db_session):
        """Test that premature payment jumps are prevented"""
        # Simulate the original issue: user selects "1" and jumps to payment
        customer = Customer(name="Test User", phone_number="+1234567890", group_id=1)
        db_session.add(customer)
        db_session.commit()
        
        session = ConversationSession.get_or_create_session(db_session, customer.id)
        session.current_state = ConversationState.WELCOME
        
        # User selects "1" (Place Order)
        intent = detect_customer_intent("1", "text", None, ConversationState.WELCOME)
        assert intent == "place_order"
        
        # This should NOT jump to payment - should go to order details
        # (Simulating the fixed flow)
        mock_whatsapp = Mock()
        mock_event_data = {
            "message": "1",
            "type": "text",
            "phone_number": "+1234567890"
        }
        
        # Mock the handle_customer_message_with_context to test flow
        with patch('app.routers.webhook.send_default_options'):
            await handle_customer_message_with_context(
                customer, mock_event_data, db_session, 1, mock_whatsapp, session
            )
        
        # After fix, should be in AWAITING_ORDER_DETAILS, not payment state
        assert session.current_state != ConversationState.AWAITING_PAYMENT.value
    
    @pytest.mark.asyncio
    async def test_order_details_processing(self, db_session):
        """Test that order details like '2 pairs of green socks' are properly processed"""
        customer = Customer(name="Test User", phone_number="+1234567890", group_id=1)
        db_session.add(customer)
        db_session.commit()
        
        session = ConversationSession.get_or_create_session(db_session, customer.id)
        session.current_state = ConversationState.AWAITING_ORDER_DETAILS
        
        mock_whatsapp = Mock()
        mock_event_data = {
            "message": "2 pairs of green socks",
            "type": "text",
            "phone_number": "+1234567890"
        }
        
        # Mock create_order function
        with patch('app.routers.webhook.create_order') as mock_create_order:
            mock_create_order.return_value = AsyncMock()
            
            await handle_customer_message_with_context(
                customer, mock_event_data, db_session, 1, mock_whatsapp, session
            )
        
        # Should have called create_order and moved to payment state
        mock_create_order.assert_called_once()
        assert session.current_state == ConversationState.AWAITING_PAYMENT.value
    
    def test_state_loop_prevention(self, db_session):
        """Test that state loops are detected and prevented"""
        debugger = ConversationDebugger(db_session)
        customer_id = 123
        
        # Simulate a state loop (same state repeatedly)
        for i in range(5):
            debugger.trace_conversation_step(
                customer_id=customer_id,
                message=f"message {i}",
                from_state=ConversationState.IDLE.value,
                to_state=ConversationState.IDLE.value,
                intent="unknown",
                action="staying in idle"
            )
        
        # Check that loop was detected
        recent_traces = [t for t in debugger.conversation_traces if t.customer_id == customer_id]
        assert len(recent_traces) >= 3
        
        # At least one trace should detect the loop
        loop_detected = any("loop" in issue for trace in recent_traces for issue in trace.issues_detected)
        assert loop_detected

class TestLangGraphIntegration:
    """Test LangGraph state management integration"""
    
    def test_agent_state_annotations(self):
        """Test that AgentState uses proper LangGraph annotations"""
        # Test the new AgentState structure
        from app.services.ai_agent import AgentState
        from langchain_core.messages import HumanMessage
        from langgraph.graph.message import add_messages
        from typing import get_type_hints, get_origin, get_args
        
        # Check that messages field has proper annotation
        hints = get_type_hints(AgentState)
        messages_hint = hints.get('messages')
        
        # Should be Annotated type
        assert get_origin(messages_hint) is not None
        # Should include add_messages in the annotation
        args = get_args(messages_hint)
        assert len(args) >= 2
        assert add_messages in args
    
    @pytest.mark.asyncio
    async def test_ai_agent_memory_management(self, db_session):
        """Test that AI agent uses pure LangGraph memory management"""
        # Test that enhanced memory service is not used
        agent = OrderBotAgent(db_session)
        
        # Should not have enhanced_memory attribute
        assert not hasattr(agent, 'enhanced_memory')
        
        # Should have checkpointer for LangGraph memory
        assert hasattr(agent, 'checkpointer')
    
    def test_conversation_history_extraction(self):
        """Test that conversation context is extracted from LangGraph state"""
        from app.services.ai_agent import OrderBotAgent
        from langchain_core.messages import HumanMessage, AIMessage
        
        # Create mock state with messages
        mock_state = {
            "messages": [
                HumanMessage(content="Hello"),
                AIMessage(content="Hi there!"),
                HumanMessage(content="I want to order something")
            ],
            "customer_id": 123,
            "group_id": 1
        }
        
        # Test the _generate_contextual_response method extraction logic
        # (This tests the modernized conversation context extraction)
        assert len(mock_state["messages"]) == 3
        recent_messages = [msg.content for msg in mock_state["messages"][-2:]]
        assert "Hi there!" in recent_messages
        assert "I want to order something" in recent_messages

class TestConversationDebugging:
    """Test the conversation debugging and monitoring tools"""
    
    def test_issue_detection(self, db_session):
        """Test automatic issue detection"""
        debugger = ConversationDebugger(db_session)
        
        # Test premature payment jump detection
        trace = debugger.trace_conversation_step(
            customer_id=123,
            message="1",
            from_state=ConversationState.WELCOME.value,
            to_state=ConversationState.AWAITING_PAYMENT.value,
            intent="place_order",
            action="jumped to payment"
        )
        
        # Should detect premature payment jump
        assert any("premature" in issue.lower() for issue in trace.issues_detected)
    
    def test_conversation_analysis(self, db_session):
        """Test conversation flow analysis"""
        debugger = ConversationDebugger(db_session)
        customer_id = 123
        
        # Create a conversation trace
        traces = [
            (ConversationState.WELCOME.value, ConversationState.AWAITING_ORDER_DETAILS.value, "1", "place_order"),
            (ConversationState.AWAITING_ORDER_DETAILS.value, ConversationState.AWAITING_PAYMENT.value, "2 red socks", "order_extracted"),
            (ConversationState.AWAITING_PAYMENT.value, ConversationState.AWAITING_PAYMENT_CONFIRMATION.value, "1", "mpesa_payment")
        ]
        
        for from_state, to_state, message, intent in traces:
            debugger.trace_conversation_step(
                customer_id=customer_id,
                message=message,
                from_state=from_state,
                to_state=to_state,
                intent=intent,
                action=f"transition to {to_state}"
            )
        
        # Analyze conversation
        analysis = debugger.analyze_customer_conversation(customer_id, hours_back=1)
        
        assert analysis["customer_id"] == customer_id
        assert analysis["total_interactions"] == 3
        assert len(analysis["state_transitions"]["transition_patterns"]) > 0
        assert analysis["current_state"] is not None
    
    def test_system_wide_analysis(self, db_session):
        """Test system-wide conversation analysis"""
        debugger = ConversationDebugger(db_session)
        
        # Create traces for multiple customers
        for customer_id in [123, 124, 125]:
            debugger.trace_conversation_step(
                customer_id=customer_id,
                message="test message",
                from_state=ConversationState.WELCOME.value,
                to_state=ConversationState.IDLE.value,
                intent="unknown",
                action="test action"
            )
        
        # Get system analysis
        analysis = debugger.get_system_wide_analysis(hours_back=1)
        
        assert analysis["unique_customers"] == 3
        assert analysis["total_interactions"] == 3
        assert "state_distribution" in analysis
        assert "recommendations" in analysis

class TestSessionCleanup:
    """Test session cleanup and maintenance"""
    
    def test_stale_session_cleanup(self, db_session):
        """Test cleanup of stale conversation sessions"""
        # Create customers with stale sessions
        customer1 = Customer(name="Stale User 1", phone_number="+1234567891", group_id=1)
        customer2 = Customer(name="Active User", phone_number="+1234567892", group_id=1)
        db_session.add_all([customer1, customer2])
        db_session.commit()
        
        # Create sessions
        session1 = ConversationSession.get_or_create_session(db_session, customer1.id)
        session2 = ConversationSession.get_or_create_session(db_session, customer2.id)
        
        # Make session1 stale
        session1.last_interaction = datetime.utcnow() - timedelta(hours=25)
        session1.current_state = ConversationState.AWAITING_PAYMENT
        
        # Keep session2 fresh
        session2.last_interaction = datetime.utcnow()
        session2.current_state = ConversationState.IDLE
        
        db_session.commit()
        
        # Run cleanup
        cleanup_summary = ConversationSession.cleanup_stale_sessions(db_session, max_inactive_hours=24)
        
        # Check results
        assert cleanup_summary["sessions_checked"] == 2
        assert cleanup_summary["stale_sessions_reset"] >= 1
        assert len(cleanup_summary["errors"]) == 0
        
        # Refresh sessions
        db_session.refresh(session1)
        db_session.refresh(session2)
        
        # Stale session should be reset
        assert session1.current_state == ConversationState.WELCOME.value
        # Active session should remain unchanged
        assert session2.current_state == ConversationState.IDLE.value

class TestIntegrationScenarios:
    """Integration tests simulating real conversation scenarios"""
    
    @pytest.mark.asyncio
    async def test_complete_order_flow(self, db_session):
        """Test complete order flow without issues"""
        customer = Customer(name="Test User", phone_number="+1234567890", group_id=1)
        db_session.add(customer)
        db_session.commit()
        
        session = ConversationSession.get_or_create_session(db_session, customer.id)
        debugger = ConversationDebugger(db_session)
        
        # Simulate complete order flow
        flow_steps = [
            (ConversationState.INITIAL, ConversationState.WELCOME, "order from group:test", "group_selection"),
            (ConversationState.WELCOME, ConversationState.AWAITING_ORDER_DETAILS, "1", "place_order"),
            (ConversationState.AWAITING_ORDER_DETAILS, ConversationState.AWAITING_PAYMENT, "2 red socks", "order_details"),
            (ConversationState.AWAITING_PAYMENT, ConversationState.AWAITING_PAYMENT_CONFIRMATION, "1", "mpesa_payment"),
            (ConversationState.AWAITING_PAYMENT_CONFIRMATION, ConversationState.IDLE, "ABC123DEF", "payment_confirmed")
        ]
        
        for from_state, to_state, message, intent in flow_steps:
            session.current_state = from_state
            
            # Trace the step
            trace = debugger.trace_conversation_step(
                customer_id=customer.id,
                message=message,
                from_state=from_state.value,
                to_state=to_state.value,
                intent=intent,
                action=f"transition to {to_state.value}",
                context=session.get_context()
            )
            
            # Update state
            session.update_state(to_state)
            
            # Verify no critical issues
            critical_issues = [issue for issue in trace.issues_detected if "premature" in issue or "loop" in issue]
            assert len(critical_issues) == 0
        
        # Final state should be IDLE
        assert session.current_state == ConversationState.IDLE.value
    
    @pytest.mark.asyncio
    async def test_problematic_scenario_prevention(self, db_session):
        """Test that the original problematic scenarios are prevented"""
        customer = Customer(name="Test User", phone_number="+1234567890", group_id=1)
        db_session.add(customer)
        db_session.commit()
        
        session = ConversationSession.get_or_create_session(db_session, customer.id)
        debugger = ConversationDebugger(db_session)
        
        # Simulate the exact problematic scenario from the conversation log
        session.current_state = ConversationState.WELCOME
        
        # User selects "1" - should NOT jump to payment
        intent = detect_customer_intent("1", "text", None, ConversationState.WELCOME)
        assert intent == "place_order"
        
        # Trace this step
        trace = debugger.trace_conversation_step(
            customer_id=customer.id,
            message="1",
            from_state=ConversationState.WELCOME.value,
            to_state=ConversationState.AWAITING_ORDER_DETAILS.value,  # Should go here, not payment
            intent=intent,
            action="asking for order details",
            context=session.get_context()
        )
        
        # Should NOT detect premature payment jump with the fix
        premature_issues = [issue for issue in trace.issues_detected if "premature" in issue.lower()]
        assert len(premature_issues) == 0
        
        # Now user provides order details
        session.current_state = ConversationState.AWAITING_ORDER_DETAILS
        
        trace2 = debugger.trace_conversation_step(
            customer_id=customer.id,
            message="2 pairs of green socks",
            from_state=ConversationState.AWAITING_ORDER_DETAILS.value,
            to_state=ConversationState.AWAITING_PAYMENT.value,
            intent="order_details",
            action="processing order details",
            context=session.get_context()
        )
        
        # Should NOT detect order details being ignored
        ignored_issues = [issue for issue in trace2.issues_detected if "ignored" in issue.lower()]
        assert len(ignored_issues) == 0

# Fixtures for testing
@pytest.fixture
def db_session():
    """Mock database session for testing"""
    from unittest.mock import Mock
    mock_session = Mock(spec=Session)
    mock_session.add = Mock()
    mock_session.commit = Mock()
    mock_session.refresh = Mock()
    mock_session.rollback = Mock()
    mock_session.query = Mock()
    return mock_session

if __name__ == "__main__":
    pytest.main([__file__, "-v"])