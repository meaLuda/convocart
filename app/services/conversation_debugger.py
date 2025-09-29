"""
Conversation Flow Debugging and Monitoring Service

Provides comprehensive tools for debugging conversation flows, monitoring state transitions,
and analyzing conversation patterns to identify issues like those in the problematic chat logs.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from sqlalchemy.orm import Session
from dataclasses import dataclass
from enum import Enum

from app.models import ConversationSession, ConversationState, Customer, Order, OrderStatus

logger = logging.getLogger(__name__)

class FlowIssueType(Enum):
    """Types of conversation flow issues"""
    PREMATURE_PAYMENT_JUMP = "premature_payment_jump"
    STATE_LOOP = "state_loop"
    INVALID_TRANSITION = "invalid_transition"
    CONTEXT_MISMATCH = "context_mismatch"
    STALE_SESSION = "stale_session"
    MISSING_ORDER_CONTEXT = "missing_order_context"
    AMBIGUOUS_INTENT = "ambiguous_intent"

@dataclass
class ConversationTrace:
    """Represents a conversation state trace for debugging"""
    timestamp: datetime
    customer_id: int
    from_state: str
    to_state: str
    message: str
    intent_detected: Optional[str]
    action_taken: str
    context_snapshot: Dict[str, Any]
    issues_detected: List[str]

@dataclass
class FlowIssue:
    """Represents a detected conversation flow issue"""
    issue_type: FlowIssueType
    customer_id: int
    session_id: int
    description: str
    severity: str  # "low", "medium", "high", "critical"
    detected_at: datetime
    context: Dict[str, Any]
    recommended_action: str

class ConversationDebugger:
    """
    Advanced conversation flow debugging and monitoring service
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.conversation_traces: List[ConversationTrace] = []
        self.detected_issues: List[FlowIssue] = []
        
    def trace_conversation_step(self, customer_id: int, message: str, 
                              from_state: str, to_state: str, 
                              intent: Optional[str] = None,
                              action: str = "",
                              context: Dict[str, Any] = None) -> ConversationTrace:
        """
        Record a conversation step for debugging analysis
        """
        issues = self._analyze_step_for_issues(customer_id, message, from_state, to_state, intent, context)
        
        trace = ConversationTrace(
            timestamp=datetime.utcnow(),
            customer_id=customer_id,
            from_state=from_state,
            to_state=to_state,
            message=message,
            intent_detected=intent,
            action_taken=action,
            context_snapshot=context or {},
            issues_detected=issues
        )
        
        self.conversation_traces.append(trace)
        
        # Keep only recent traces to avoid memory bloat
        if len(self.conversation_traces) > 1000:
            self.conversation_traces = self.conversation_traces[-500:]
        
        # Log significant issues
        if issues:
            logger.warning(f"Conversation issues detected for customer {customer_id}: {issues}")
        
        return trace
    
    def _analyze_step_for_issues(self, customer_id: int, message: str, 
                               from_state: str, to_state: str, 
                               intent: Optional[str],
                               context: Dict[str, Any] = None) -> List[str]:
        """
        Analyze a conversation step for potential issues
        """
        issues = []
        
        # Check for premature payment jumps
        if (from_state in [ConversationState.WELCOME.value, ConversationState.IDLE.value] and 
            to_state == ConversationState.AWAITING_PAYMENT.value):
            issues.append("Premature jump to payment without order details")
        
        # Check for state loops
        recent_states = [trace.to_state for trace in self.conversation_traces[-5:] 
                        if trace.customer_id == customer_id]
        if len(recent_states) >= 3 and len(set(recent_states)) == 1:
            issues.append(f"State loop detected: stuck in {to_state}")
        
        # Check for context mismatches
        if context:
            if (to_state == ConversationState.AWAITING_PAYMENT.value and 
                not context.get('pending_order_id') and not context.get('last_order_id')):
                issues.append("In payment state but no order context found")
        
        # Check for ambiguous intent detection
        if intent == "unknown" and len(message.strip()) > 5:
            issues.append(f"Failed to detect intent for meaningful message: '{message[:30]}...'")
        
        # Check for order details being ignored
        if (from_state == ConversationState.AWAITING_ORDER_DETAILS.value and
            to_state in [ConversationState.WELCOME.value, ConversationState.IDLE.value] and
            len(message.strip()) > 10):
            issues.append(f"Order details '{message[:30]}...' may have been ignored")
        
        return issues
    
    def analyze_customer_conversation(self, customer_id: int, 
                                    hours_back: int = 24) -> Dict[str, Any]:
        """
        Comprehensive analysis of a customer's conversation flow
        """
        # Get conversation session
        session = ConversationSession.get_or_create_session(self.db, customer_id)
        
        # Get recent traces for this customer
        cutoff_time = datetime.utcnow() - timedelta(hours=hours_back)
        customer_traces = [
            trace for trace in self.conversation_traces 
            if trace.customer_id == customer_id and trace.timestamp > cutoff_time
        ]
        
        # Analyze conversation patterns
        analysis = {
            "customer_id": customer_id,
            "current_state": session.current_state.value if hasattr(session.current_state, 'value') else str(session.current_state),
            "session_context": session.get_context(),
            "total_interactions": len(customer_traces),
            "conversation_duration_minutes": self._calculate_conversation_duration(customer_traces),
            "state_transitions": self._analyze_state_transitions(customer_traces),
            "detected_issues": self._categorize_issues(customer_traces),
            "conversation_flow": [
                {
                    "timestamp": trace.timestamp.isoformat(),
                    "from_state": trace.from_state,
                    "to_state": trace.to_state,
                    "message_preview": trace.message[:50] + "..." if len(trace.message) > 50 else trace.message,
                    "intent": trace.intent_detected,
                    "action": trace.action_taken,
                    "issues": trace.issues_detected
                }
                for trace in customer_traces[-20:]  # Last 20 interactions
            ],
            "recommendations": self._generate_recommendations(customer_traces, session)
        }
        
        return analysis
    
    def _calculate_conversation_duration(self, traces: List[ConversationTrace]) -> float:
        """Calculate conversation duration in minutes"""
        if len(traces) < 2:
            return 0.0
        
        start_time = traces[0].timestamp
        end_time = traces[-1].timestamp
        duration = end_time - start_time
        return duration.total_seconds() / 60.0
    
    def _analyze_state_transitions(self, traces: List[ConversationTrace]) -> Dict[str, Any]:
        """Analyze patterns in state transitions"""
        if not traces:
            return {}
        
        transitions = {}
        state_counts = {}
        
        for trace in traces:
            # Count state visits
            state_counts[trace.to_state] = state_counts.get(trace.to_state, 0) + 1
            
            # Count transition patterns
            transition = f"{trace.from_state} -> {trace.to_state}"
            transitions[transition] = transitions.get(transition, 0) + 1
        
        return {
            "state_visit_counts": state_counts,
            "transition_patterns": transitions,
            "most_visited_state": max(state_counts.items(), key=lambda x: x[1])[0] if state_counts else None,
            "unique_states_visited": len(state_counts),
            "total_transitions": len(traces)
        }
    
    def _categorize_issues(self, traces: List[ConversationTrace]) -> Dict[str, List[str]]:
        """Categorize detected issues by type"""
        categorized = {
            "critical": [],
            "high": [],
            "medium": [],
            "low": []
        }
        
        all_issues = []
        for trace in traces:
            all_issues.extend(trace.issues_detected)
        
        for issue in all_issues:
            if "premature" in issue.lower() or "loop" in issue.lower():
                categorized["critical"].append(issue)
            elif "ignored" in issue.lower() or "context" in issue.lower():
                categorized["high"].append(issue)
            elif "intent" in issue.lower():
                categorized["medium"].append(issue)
            else:
                categorized["low"].append(issue)
        
        return categorized
    
    def _generate_recommendations(self, traces: List[ConversationTrace], 
                                session: ConversationSession) -> List[str]:
        """Generate recommendations to fix conversation issues"""
        recommendations = []
        
        # Check session state consistency
        is_valid, issues, recommended_action = session.validate_state_consistency()
        if not is_valid:
            recommendations.append(f"Session state issue: {recommended_action}")
        
        # Analyze issue patterns
        all_issues = []
        for trace in traces:
            all_issues.extend(trace.issues_detected)
        
        if any("premature" in issue for issue in all_issues):
            recommendations.append("Fix intent detection logic to prevent premature payment jumps")
        
        if any("loop" in issue for issue in all_issues):
            recommendations.append("Add state transition validation to prevent conversation loops")
        
        if any("ignored" in issue for issue in all_issues):
            recommendations.append("Review message processing to ensure user input is properly handled")
        
        if any("intent" in issue for issue in all_issues):
            recommendations.append("Improve intent detection for better conversation understanding")
        
        # Check for conversation patterns
        if len(traces) > 10:
            state_counts = {}
            for trace in traces:
                state_counts[trace.to_state] = state_counts.get(trace.to_state, 0) + 1
            
            if state_counts.get(ConversationState.IDLE.value, 0) > len(traces) * 0.5:
                recommendations.append("High IDLE state frequency suggests conversation flow issues")
        
        return recommendations
    
    def get_system_wide_analysis(self, hours_back: int = 24) -> Dict[str, Any]:
        """
        Analyze conversation patterns across all customers
        """
        cutoff_time = datetime.utcnow() - timedelta(hours=hours_back)
        recent_traces = [
            trace for trace in self.conversation_traces 
            if trace.timestamp > cutoff_time
        ]
        
        # Aggregate statistics
        customer_issues = {}
        state_distribution = {}
        intent_success_rate = {}
        
        for trace in recent_traces:
            # Track customer-specific issues
            if trace.customer_id not in customer_issues:
                customer_issues[trace.customer_id] = []
            customer_issues[trace.customer_id].extend(trace.issues_detected)
            
            # Track state distribution
            state_distribution[trace.to_state] = state_distribution.get(trace.to_state, 0) + 1
            
            # Track intent detection success
            if trace.intent_detected:
                intent_success_rate[trace.intent_detected] = intent_success_rate.get(trace.intent_detected, 0) + 1
        
        # Calculate metrics
        total_customers = len(customer_issues)
        customers_with_issues = len([cid for cid, issues in customer_issues.items() if issues])
        
        return {
            "analysis_period_hours": hours_back,
            "total_interactions": len(recent_traces),
            "unique_customers": total_customers,
            "customers_with_issues": customers_with_issues,
            "issue_rate": (customers_with_issues / total_customers * 100) if total_customers > 0 else 0,
            "state_distribution": state_distribution,
            "most_problematic_customers": sorted(
                customer_issues.items(), 
                key=lambda x: len(x[1]), 
                reverse=True
            )[:10],
            "common_issues": self._get_most_common_issues(recent_traces),
            "recommendations": self._generate_system_recommendations(recent_traces)
        }
    
    def _get_most_common_issues(self, traces: List[ConversationTrace]) -> List[Tuple[str, int]]:
        """Get most common issues across all conversations"""
        issue_counts = {}
        
        for trace in traces:
            for issue in trace.issues_detected:
                issue_counts[issue] = issue_counts.get(issue, 0) + 1
        
        return sorted(issue_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    
    def _generate_system_recommendations(self, traces: List[ConversationTrace]) -> List[str]:
        """Generate system-wide recommendations"""
        recommendations = []
        
        # Analyze issue frequency
        all_issues = []
        for trace in traces:
            all_issues.extend(trace.issues_detected)
        
        if len(all_issues) > len(traces) * 0.1:  # More than 10% of interactions have issues
            recommendations.append("High issue rate detected - review conversation flow logic")
        
        issue_types = {}
        for issue in all_issues:
            if "premature" in issue.lower():
                issue_types["premature"] = issue_types.get("premature", 0) + 1
            elif "loop" in issue.lower():
                issue_types["loop"] = issue_types.get("loop", 0) + 1
            elif "intent" in issue.lower():
                issue_types["intent"] = issue_types.get("intent", 0) + 1
        
        if issue_types.get("premature", 0) > 5:
            recommendations.append("CRITICAL: Fix premature payment jump issue affecting multiple customers")
        
        if issue_types.get("loop", 0) > 3:
            recommendations.append("HIGH: State loop prevention needed")
        
        if issue_types.get("intent", 0) > 10:
            recommendations.append("MEDIUM: Intent detection accuracy needs improvement")
        
        return recommendations

# Global debugger instance (singleton pattern)
_conversation_debugger = None

def get_conversation_debugger(db: Session) -> ConversationDebugger:
    """Get or create conversation debugger instance"""
    global _conversation_debugger
    if _conversation_debugger is None:
        _conversation_debugger = ConversationDebugger(db)
    return _conversation_debugger