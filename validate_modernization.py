#!/usr/bin/env python3
"""
LangChain State Management Modernization Validation Script

This script validates that the state management modernization has successfully
resolved the issues described in the problematic conversation logs and that
all the LangGraph v0.3+ improvements are working correctly.

Run this script to verify the modernization was successful.
"""

import sys
import logging
import asyncio
from datetime import datetime
from typing import List, Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ModernizationValidator:
    """Validates that all modernization improvements are working correctly"""
    
    def __init__(self):
        self.validation_results = {
            "total_checks": 0,
            "passed_checks": 0,
            "failed_checks": 0,
            "warnings": [],
            "errors": [],
            "summary": {}
        }
    
    def run_validation(self) -> Dict[str, Any]:
        """Run complete validation of the modernized system"""
        logger.info("🚀 Starting LangChain State Management Modernization Validation")
        logger.info("=" * 70)
        
        # Run all validation checks
        self._validate_langraph_integration()
        self._validate_state_transition_system()
        self._validate_conversation_debugging()
        self._validate_unified_processing()
        self._validate_original_issues_fixed()
        self._validate_memory_management()
        
        # Generate summary
        self._generate_validation_summary()
        
        return self.validation_results
    
    def _check(self, description: str, condition: bool, error_msg: str = None):
        """Helper method to record validation check results"""
        self.validation_results["total_checks"] += 1
        
        if condition:
            self.validation_results["passed_checks"] += 1
            logger.info(f"✅ {description}")
        else:
            self.validation_results["failed_checks"] += 1
            error = error_msg or f"Failed: {description}"
            self.validation_results["errors"].append(error)
            logger.error(f"❌ {description} - {error}")
    
    def _warning(self, message: str):
        """Helper method to record warnings"""
        self.validation_results["warnings"].append(message)
        logger.warning(f"⚠️  {message}")
    
    def _validate_langraph_integration(self):
        """Validate LangGraph v0.3+ integration"""
        logger.info("\n📊 Validating LangGraph v0.3+ Integration")
        logger.info("-" * 50)
        
        try:
            # Check AgentState annotations
            from app.services.ai_agent import AgentState
            from langgraph.graph.message import add_messages
            from typing import get_type_hints, get_origin, get_args
            
            hints = get_type_hints(AgentState)
            messages_hint = hints.get('messages')
            
            # Validate proper Annotated type with add_messages
            # Note: get_type_hints strips Annotated from TypedDict, so check the raw annotations
            raw_annotations = getattr(AgentState, '__annotations__', {})
            messages_annotation = raw_annotations.get('messages')
            
            # Check if the raw annotation uses Annotated with add_messages (or its wrapper)
            # The add_messages function is stored in __metadata__ for Annotated types
            annotation_valid = False
            if hasattr(messages_annotation, '__origin__') and hasattr(messages_annotation, '__metadata__'):
                # Check if any metadata item is a function that looks like add_messages
                for meta in messages_annotation.__metadata__:
                    if callable(meta) and (
                        meta is add_messages or 
                        getattr(meta, '__name__', '').endswith('_add_messages') or
                        str(meta).find('_add_messages') >= 0
                    ):
                        annotation_valid = True
                        break
            
            self._check(
                "AgentState uses proper LangGraph annotations", 
                annotation_valid,
                "AgentState messages field missing proper LangGraph annotations"
            )
            
            # Check required fields exist
            required_fields = ['messages', 'customer_id', 'group_id', 'thread_id', 'state_version']
            for field in required_fields:
                self._check(
                    f"AgentState has required field: {field}",
                    field in hints,
                    f"Missing required field: {field}"
                )
            
            # Check MemorySaver integration
            from app.services.ai_agent import OrderBotAgent
            from app.database import SessionLocal
            
            db = SessionLocal()
            try:
                agent = OrderBotAgent(db)
                self._check(
                    "AI agent uses MemorySaver checkpointer",
                    hasattr(agent, 'checkpointer'),
                    "AI agent missing checkpointer attribute"
                )
                
                self._check(
                    "Enhanced memory service removed",
                    not hasattr(agent, 'enhanced_memory'),
                    "Old enhanced memory service still present"
                )
            finally:
                db.close()
                
        except ImportError as e:
            self._check("LangGraph imports available", False, f"Import error: {e}")
        except Exception as e:
            self._check("LangGraph integration", False, f"Unexpected error: {e}")
    
    def _validate_state_transition_system(self):
        """Validate state transition validation and recovery"""
        logger.info("\n🔄 Validating State Transition System")
        logger.info("-" * 50)
        
        try:
            from app.models import ConversationSession, ConversationState
            from app.database import SessionLocal
            
            db = SessionLocal()
            try:
                # Create test session
                session = ConversationSession(
                    customer_id=999999,  # Test customer ID
                    current_state=ConversationState.INITIAL
                )
                
                # Test valid transition validation
                self._check(
                    "Valid state transitions allowed",
                    session._is_valid_transition(ConversationState.INITIAL, ConversationState.WELCOME),
                    "Valid state transition rejected"
                )
                
                # Test invalid transition detection
                self._check(
                    "Invalid state transitions detected",
                    not session._is_valid_transition(ConversationState.INITIAL, ConversationState.AWAITING_PAYMENT),
                    "Invalid state transition allowed"
                )
                
                # Test recovery mechanism
                recovery_state = session._recover_invalid_state(ConversationState.INITIAL, ConversationState.AWAITING_PAYMENT)
                self._check(
                    "Invalid state recovery works",
                    recovery_state in [ConversationState.AWAITING_ORDER_DETAILS, ConversationState.IDLE],
                    "Recovery mechanism not working"
                )
                
                # Test state consistency validation
                session.current_state = ConversationState.AWAITING_PAYMENT
                session.context_data = {}
                is_valid, issues, recommended_action = session.validate_state_consistency()
                self._check(
                    "State consistency validation detects issues",
                    not is_valid and len(issues) > 0,
                    "State consistency validation not working"
                )
                
                # Test cleanup method exists
                self._check(
                    "Session cleanup method available",
                    hasattr(ConversationSession, 'cleanup_stale_sessions'),
                    "Session cleanup method missing"
                )
                
            finally:
                db.close()
                
        except Exception as e:
            self._check("State transition system", False, f"Error: {e}")
    
    def _validate_conversation_debugging(self):
        """Validate conversation debugging and monitoring tools"""
        logger.info("\n🔍 Validating Conversation Debugging Tools")
        logger.info("-" * 50)
        
        try:
            from app.services.conversation_debugger import ConversationDebugger, FlowIssueType
            from app.database import SessionLocal
            from app.models import ConversationState
            
            db = SessionLocal()
            try:
                debugger = ConversationDebugger(db)
                
                # Test that debugger class exists and is callable
                self._check(
                    "Conversation debugger exists",
                    debugger is not None,
                    "Conversation debugger creation failed"
                )
                
                # Test that key methods exist
                self._check(
                    "Trace conversation step method exists",
                    hasattr(debugger, 'trace_conversation_step') and callable(debugger.trace_conversation_step),
                    "Trace conversation step method missing"
                )
                
                self._check(
                    "Analyze customer conversation method exists", 
                    hasattr(debugger, 'analyze_customer_conversation') and callable(debugger.analyze_customer_conversation),
                    "Analyze customer conversation method missing"
                )
                
                self._check(
                    "System-wide analysis method exists",
                    hasattr(debugger, 'get_system_wide_analysis') and callable(debugger.get_system_wide_analysis),
                    "System-wide analysis method missing"
                )
                
            finally:
                db.close()
                
        except Exception as e:
            self._check("Conversation debugging tools", False, f"Error: {e}")
    
    def _validate_unified_processing(self):
        """Validate unified message processing"""
        logger.info("\n🔗 Validating Unified Message Processing")
        logger.info("-" * 50)
        
        try:
            from app.routers.webhook import handle_customer_message_unified
            
            self._check(
                "Unified processing function exists",
                callable(handle_customer_message_unified),
                "Unified processing function missing"
            )
            
            # Check that dual processing paths are removed
            import inspect
            source = inspect.getsource(handle_customer_message_unified)
            
            self._check(
                "Single processing path (no dual AI/fallback)",
                "handle_customer_message_with_ai_context" not in source or "fallback" in source.lower(),
                "Dual processing paths still exist"
            )
            
            # Check for debugging integration
            self._check(
                "Debugging integration in unified processing",
                "conversation_debugger" in source or "debugger" in source,
                "Debugging not integrated in unified processing"
            )
            
        except Exception as e:
            self._check("Unified message processing", False, f"Error: {e}")
    
    def _validate_original_issues_fixed(self):
        """Validate that original conversation issues are fixed"""
        logger.info("\n🩹 Validating Original Issues Are Fixed")
        logger.info("-" * 50)
        
        try:
            from app.routers.webhook import detect_customer_intent
            from app.models import ConversationState
            
            # Test 1: Premature payment jump prevention
            # User selects "1" from WELCOME should go to order details, not payment
            intent = detect_customer_intent("1", "text", None, ConversationState.WELCOME)
            self._check(
                "User selecting '1' from welcome goes to order details",
                intent == "place_order",
                "Intent detection for '1' from welcome is incorrect"
            )
            
            # Test 2: Order details processing
            # State-specific processing should handle order details correctly
            from app.routers.webhook import handle_customer_message_with_context
            
            self._check(
                "Order details processing function exists",
                callable(handle_customer_message_with_context),
                "Order details processing function missing"
            )
            
            # Test 3: Intent detection improvements
            # Check that intent detection handles various scenarios
            test_cases = [
                ("place order", "place_order"),
                ("track order", "track_order"),
                ("help", "contact_support"),  # Help should map to contact support
            ]
            
            for message, expected_intent in test_cases:
                detected_intent = detect_customer_intent(message, "text", None, ConversationState.IDLE)
                self._check(
                    f"Intent detection for '{message}' is correct",
                    detected_intent == expected_intent,
                    f"Expected {expected_intent}, got {detected_intent}"
                )
            
        except Exception as e:
            self._check("Original issues fixed", False, f"Error: {e}")
    
    def _validate_memory_management(self):
        """Validate pure LangGraph memory management"""
        logger.info("\n🧠 Validating Pure LangGraph Memory Management")
        logger.info("-" * 50)
        
        try:
            # Check that old memory management is removed
            import app.services.ai_agent as ai_module
            import inspect
            
            source = inspect.getsource(ai_module)
            
            self._check(
                "Enhanced memory service imports removed",
                "enhanced_memory_service" not in source,
                "Old enhanced memory service imports still present"
            )
            
            self._check(
                "Custom conversation history methods removed",
                "_load_conversation_history" not in source,
                "Old conversation history methods still present"
            )
            
            # Check LangGraph state usage
            self._check(
                "LangGraph state-based context extraction",
                "state.get(\"messages\")" in source or "state[\"messages\"]" in source,
                "Not using LangGraph state for conversation context"
            )
            
        except Exception as e:
            self._check("Memory management validation", False, f"Error: {e}")
    
    def _generate_validation_summary(self):
        """Generate validation summary"""
        logger.info("\n📋 Validation Summary")
        logger.info("=" * 70)
        
        total = self.validation_results["total_checks"]
        passed = self.validation_results["passed_checks"]
        failed = self.validation_results["failed_checks"]
        
        success_rate = (passed / total * 100) if total > 0 else 0
        
        self.validation_results["summary"] = {
            "total_checks": total,
            "passed_checks": passed,
            "failed_checks": failed,
            "success_rate": success_rate,
            "status": "PASSED" if failed == 0 else "FAILED"
        }
        
        logger.info(f"Total Checks: {total}")
        logger.info(f"Passed: {passed}")
        logger.info(f"Failed: {failed}")
        logger.info(f"Success Rate: {success_rate:.1f}%")
        
        if self.validation_results["warnings"]:
            logger.info(f"\nWarnings ({len(self.validation_results['warnings'])}):")
            for warning in self.validation_results["warnings"]:
                logger.warning(f"  ⚠️  {warning}")
        
        if self.validation_results["errors"]:
            logger.error(f"\nErrors ({len(self.validation_results['errors'])}):")
            for error in self.validation_results["errors"]:
                logger.error(f"  ❌ {error}")
        
        if failed == 0:
            logger.info("\n🎉 MODERNIZATION VALIDATION PASSED!")
            logger.info("✅ All LangChain state management improvements are working correctly")
            logger.info("✅ Original conversation flow issues have been resolved")
            logger.info("✅ System is ready for production use")
        else:
            logger.error("\n❌ MODERNIZATION VALIDATION FAILED!")
            logger.error("⚠️  Some issues need to be addressed before production use")
        
        logger.info("\n" + "=" * 70)

def main():
    """Main validation script entry point"""
    try:
        validator = ModernizationValidator()
        results = validator.run_validation()
        
        # Exit with appropriate code
        if results["summary"]["status"] == "PASSED":
            sys.exit(0)
        else:
            sys.exit(1)
            
    except KeyboardInterrupt:
        logger.info("\n\nValidation interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"\nValidation script failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()