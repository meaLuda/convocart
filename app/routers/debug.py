"""
Debug endpoints for conversation flow monitoring and analysis

Provides endpoints to access debugging information and analyze conversation flows
for troubleshooting issues like those described in problematic chat logs.
"""

import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.conversation_debugger import get_conversation_debugger
from app.models import ConversationSession

router = APIRouter(prefix="/debug", tags=["debug"])
logger = logging.getLogger(__name__)

@router.get("/conversation/{customer_id}")
async def analyze_customer_conversation(
    customer_id: int,
    hours_back: int = Query(24, description="Hours to look back for analysis"),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Analyze a specific customer's conversation flow for debugging
    
    Returns detailed analysis including:
    - State transitions
    - Detected issues
    - Conversation flow trace
    - Recommendations for fixes
    """
    try:
        debugger = get_conversation_debugger(db)
        analysis = debugger.analyze_customer_conversation(customer_id, hours_back)
        
        if analysis["total_interactions"] == 0:
            raise HTTPException(
                status_code=404, 
                detail=f"No conversation data found for customer {customer_id} in the last {hours_back} hours"
            )
        
        return {
            "success": True,
            "analysis": analysis,
            "debug_info": {
                "customer_id": customer_id,
                "analysis_period_hours": hours_back,
                "timestamp": "2024-01-01T00:00:00Z"  # Current timestamp would go here
            }
        }
    
    except Exception as e:
        logger.error(f"Error analyzing customer conversation: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")

@router.get("/system-overview")
async def get_system_overview(
    hours_back: int = Query(24, description="Hours to look back for analysis"),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get system-wide conversation flow analysis
    
    Provides overview of conversation patterns, common issues,
    and system-wide recommendations for improvements.
    """
    try:
        debugger = get_conversation_debugger(db)
        analysis = debugger.get_system_wide_analysis(hours_back)
        
        return {
            "success": True,
            "system_analysis": analysis,
            "debug_info": {
                "analysis_period_hours": hours_back,
                "timestamp": "2024-01-01T00:00:00Z"  # Current timestamp would go here
            }
        }
    
    except Exception as e:
        logger.error(f"Error getting system overview: {str(e)}")
        raise HTTPException(status_code=500, detail=f"System analysis failed: {str(e)}")

@router.get("/session-health/{customer_id}")
async def check_session_health(
    customer_id: int,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Check the health of a specific customer's conversation session
    
    Validates state consistency and provides recovery recommendations
    """
    try:
        session = ConversationSession.get_or_create_session(db, customer_id)
        is_valid, issues, recommended_action = session.validate_state_consistency()
        
        return {
            "success": True,
            "session_health": {
                "customer_id": customer_id,
                "session_id": session.id,
                "current_state": session.current_state.value if hasattr(session.current_state, 'value') else str(session.current_state),
                "is_valid": is_valid,
                "issues": issues,
                "recommended_action": recommended_action,
                "context": session.get_context(),
                "last_interaction": session.last_interaction.isoformat() if session.last_interaction else None
            }
        }
    
    except Exception as e:
        logger.error(f"Error checking session health: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Session health check failed: {str(e)}")

@router.post("/cleanup-sessions")
async def cleanup_stale_sessions(
    max_inactive_hours: int = Query(24, description="Maximum hours of inactivity before cleanup"),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Clean up stale conversation sessions and recover invalid states
    
    This is a maintenance endpoint that should be called periodically
    to ensure conversation state consistency across the system.
    """
    try:
        cleanup_summary = ConversationSession.cleanup_stale_sessions(db, max_inactive_hours)
        
        return {
            "success": True,
            "cleanup_summary": cleanup_summary,
            "debug_info": {
                "max_inactive_hours": max_inactive_hours,
                "timestamp": "2024-01-01T00:00:00Z"  # Current timestamp would go here
            }
        }
    
    except Exception as e:
        logger.error(f"Error during session cleanup: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Session cleanup failed: {str(e)}")

@router.get("/conversation-trace/{customer_id}")
async def get_conversation_trace(
    customer_id: int,
    limit: int = Query(50, description="Maximum number of trace entries to return"),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get detailed conversation trace for debugging specific issues
    
    Returns step-by-step conversation flow with detected issues
    for detailed troubleshooting.
    """
    try:
        debugger = get_conversation_debugger(db)
        
        # Filter traces for this customer
        customer_traces = [
            trace for trace in debugger.conversation_traces 
            if trace.customer_id == customer_id
        ][-limit:]  # Get last N traces
        
        if not customer_traces:
            raise HTTPException(
                status_code=404, 
                detail=f"No conversation traces found for customer {customer_id}"
            )
        
        # Format traces for response
        formatted_traces = []
        for trace in customer_traces:
            formatted_traces.append({
                "timestamp": trace.timestamp.isoformat(),
                "from_state": trace.from_state,
                "to_state": trace.to_state,
                "message": trace.message,
                "intent_detected": trace.intent_detected,
                "action_taken": trace.action_taken,
                "context_snapshot": trace.context_snapshot,
                "issues_detected": trace.issues_detected
            })
        
        return {
            "success": True,
            "conversation_trace": {
                "customer_id": customer_id,
                "trace_count": len(formatted_traces),
                "traces": formatted_traces
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting conversation trace: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Trace retrieval failed: {str(e)}")

@router.get("/issue-patterns")
async def get_issue_patterns(
    hours_back: int = Query(24, description="Hours to look back for pattern analysis"),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Analyze patterns in conversation issues to identify systemic problems
    
    Useful for identifying recurring issues like premature payment jumps,
    state loops, and other conversation flow problems.
    """
    try:
        debugger = get_conversation_debugger(db)
        
        # Get recent traces with issues
        from datetime import datetime, timedelta
        cutoff_time = datetime.utcnow() - timedelta(hours=hours_back)
        
        traces_with_issues = [
            trace for trace in debugger.conversation_traces
            if trace.timestamp > cutoff_time and trace.issues_detected
        ]
        
        # Analyze issue patterns
        issue_patterns = {}
        customer_issue_counts = {}
        state_related_issues = {}
        
        for trace in traces_with_issues:
            # Count issues by type
            for issue in trace.issues_detected:
                issue_patterns[issue] = issue_patterns.get(issue, 0) + 1
            
            # Count issues by customer
            customer_issue_counts[trace.customer_id] = customer_issue_counts.get(trace.customer_id, 0) + len(trace.issues_detected)
            
            # Count issues by state
            state_key = f"{trace.from_state} -> {trace.to_state}"
            if state_key not in state_related_issues:
                state_related_issues[state_key] = []
            state_related_issues[state_key].extend(trace.issues_detected)
        
        return {
            "success": True,
            "issue_patterns": {
                "analysis_period_hours": hours_back,
                "total_traces_with_issues": len(traces_with_issues),
                "issue_frequency": sorted(issue_patterns.items(), key=lambda x: x[1], reverse=True),
                "customers_most_affected": sorted(customer_issue_counts.items(), key=lambda x: x[1], reverse=True)[:10],
                "problematic_state_transitions": {
                    state: list(set(issues)) for state, issues in state_related_issues.items() if issues
                }
            }
        }
    
    except Exception as e:
        logger.error(f"Error analyzing issue patterns: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Issue pattern analysis failed: {str(e)}")