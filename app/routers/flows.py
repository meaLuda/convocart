"""
Flow management router for the admin interface
"""
import json
import logging
from typing import Optional, List
from fastapi import APIRouter, Request, Depends, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.routers.users import get_current_admin
from app import models
from app.models import Flow, FlowState, FlowTransition, FlowAction, Group, ActionName, TriggerType, StateType

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)


@router.get("/admin/flows", response_class=HTMLResponse)
async def list_flows(
    request: Request, 
    db: Session = Depends(get_db),
    group_id: Optional[int] = Query(None)
):
    """Display all flows with optional group filtering"""
    
    # Get the current admin user
    admin = await get_current_admin(request, db)
    if isinstance(admin, RedirectResponse):
        return admin
    
    # Base query
    query = db.query(Flow).options(
        joinedload(Flow.group),
        joinedload(Flow.states)
    )
    
    # Filter by group if specified
    if group_id:
        query = query.filter(Flow.group_id == group_id)
    
    # For non-super-admin users, only show flows for their groups
    if admin.role != models.UserRole.SUPER_ADMIN:
        user_group_ids = [group.id for group in admin.groups]
        query = query.filter(Flow.group_id.in_(user_group_ids))
    
    flows = query.order_by(Flow.created_at.desc()).all()
    
    # Get all groups for the filter dropdown
    groups_query = db.query(Group).filter(Group.is_active == True)
    if admin.role != models.UserRole.SUPER_ADMIN:
        user_group_ids = [group.id for group in admin.groups]
        groups_query = groups_query.filter(Group.id.in_(user_group_ids))
    groups = groups_query.order_by(Group.name).all()
    
    return templates.TemplateResponse("flows.html", {
        "request": request,
        "admin": admin,
        "flows": flows,
        "groups": groups,
        "selected_group_id": group_id
    })


@router.post("/admin/flows/create")
async def create_flow(
    request: Request,
    name: str = Form(...),
    group_id: int = Form(...),
    description: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Create a new flow"""
    
    # Get the current admin user
    admin = await get_current_admin(request, db)
    if isinstance(admin, RedirectResponse):
        return admin
    
    # Verify user has access to the group
    if admin.role != models.UserRole.SUPER_ADMIN:
        user_group_ids = [group.id for group in admin.groups]
        if group_id not in user_group_ids:
            raise HTTPException(status_code=403, detail="Access denied to this group")
    
    # Check if group exists
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    
    # Create the flow
    flow = Flow(
        name=name,
        group_id=group_id,
        description=description,
        is_active=False  # Start as inactive
    )
    db.add(flow)
    db.commit()
    db.refresh(flow)
    
    # Redirect to flow editor
    return JSONResponse({"success": True, "redirect": f"/admin/flows/{flow.id}/edit"})


@router.get("/admin/flows/{flow_id}/edit", response_class=HTMLResponse)
async def edit_flow(
    request: Request,
    flow_id: int,
    db: Session = Depends(get_db),
):
    """Display the flow editor"""
    
    # Get the current admin user
    admin = await get_current_admin(request, db)
    if isinstance(admin, RedirectResponse):
        return admin
    
    # Get flow with all related data
    flow = db.query(Flow).options(
        joinedload(Flow.group),
        joinedload(Flow.states).joinedload(FlowState.outgoing_transitions).joinedload(FlowTransition.action),
        joinedload(Flow.states).joinedload(FlowState.outgoing_transitions).joinedload(FlowTransition.target_state),
    ).filter(Flow.id == flow_id).first()
    
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    
    # Check access permissions
    if admin.role != models.UserRole.SUPER_ADMIN:
        user_group_ids = [group.id for group in admin.groups]
        if flow.group_id not in user_group_ids:
            raise HTTPException(status_code=403, detail="Access denied")
    
    # Get all available actions
    actions = db.query(FlowAction).filter(FlowAction.is_active == True).order_by(FlowAction.display_name).all()
    
    return templates.TemplateResponse("flow_editor.html", {
        "request": request,
        "admin": admin,
        "flow": flow,
        "actions": actions
    })


@router.post("/admin/flows/{flow_id}/activate")
async def activate_flow(
    request: Request,
    flow_id: int,
    db: Session = Depends(get_db),
):
    """Activate a flow (deactivates others in the same group)"""
    
    # Get the current admin user
    admin = await get_current_admin(request, db)
    if isinstance(admin, RedirectResponse):
        return admin
    
    flow = db.query(Flow).filter(Flow.id == flow_id).first()
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    
    # Check access permissions
    if admin.role != models.UserRole.SUPER_ADMIN:
        user_group_ids = [group.id for group in admin.groups]
        if flow.group_id not in user_group_ids:
            raise HTTPException(status_code=403, detail="Access denied")
    
    # Deactivate all other flows for this group
    db.query(Flow).filter(
        Flow.group_id == flow.group_id,
        Flow.id != flow_id
    ).update({"is_active": False})
    
    # Activate this flow
    flow.is_active = True
    db.commit()
    
    return JSONResponse({"success": True})


@router.post("/admin/flows/{flow_id}/deactivate")
async def deactivate_flow(
    request: Request,
    flow_id: int,
    db: Session = Depends(get_db),
):
    """Deactivate a flow"""
    
    # Get the current admin user
    admin = await get_current_admin(request, db)
    if isinstance(admin, RedirectResponse):
        return admin
    
    flow = db.query(Flow).filter(Flow.id == flow_id).first()
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    
    # Check access permissions
    if admin.role != models.UserRole.SUPER_ADMIN:
        user_group_ids = [group.id for group in admin.groups]
        if flow.group_id not in user_group_ids:
            raise HTTPException(status_code=403, detail="Access denied")
    
    flow.is_active = False
    db.commit()
    
    return JSONResponse({"success": True})


@router.delete("/admin/flows/{flow_id}")
async def delete_flow(
    request: Request,
    flow_id: int,
    db: Session = Depends(get_db),
):
    """Delete a flow"""
    
    # Get the current admin user
    admin = await get_current_admin(request, db)
    if isinstance(admin, RedirectResponse):
        return admin
    
    flow = db.query(Flow).filter(Flow.id == flow_id).first()
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    
    # Check access permissions
    if admin.role != models.UserRole.SUPER_ADMIN:
        user_group_ids = [group.id for group in admin.groups]
        if flow.group_id not in user_group_ids:
            raise HTTPException(status_code=403, detail="Access denied")
    
    # Delete the flow (cascade will handle states and transitions)
    db.delete(flow)
    db.commit()
    
    return JSONResponse({"success": True})


@router.post("/admin/flows/{flow_id}/save")
async def save_flow(
    request: Request,
    flow_id: int,
    db: Session = Depends(get_db),
):
    """Save flow changes"""
    
    # Get the current admin user
    admin = await get_current_admin(request, db)
    if isinstance(admin, RedirectResponse):
        return admin
    
    flow = db.query(Flow).options(
        joinedload(Flow.states).joinedload(FlowState.outgoing_transitions)
    ).filter(Flow.id == flow_id).first()
    
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    
    # Check access permissions
    if admin.role != models.UserRole.SUPER_ADMIN:
        user_group_ids = [group.id for group in admin.groups]
        if flow.group_id not in user_group_ids:
            raise HTTPException(status_code=403, detail="Access denied")
    
    try:
        # Get JSON data from request
        data = await request.json()
        
        # Update flow basic information
        flow.name = data.get("name", flow.name)
        flow.description = data.get("description", flow.description)
        
        # Handle activation carefully
        if "is_active" in data and data["is_active"] and not flow.is_active:
            db.query(Flow).filter(
                Flow.group_id == flow.group_id,
                Flow.id != flow_id
            ).update({"is_active": False})
            flow.is_active = True
        elif "is_active" in data and not data["is_active"]:
            flow.is_active = False
        
        # --- State and Transition Management ---
        
        # Get existing state and transition IDs from the database
        existing_state_ids = {state.id for state in flow.states}
        existing_transition_ids = {
            transition.id 
            for state in flow.states 
            for transition in state.outgoing_transitions
        }
        
        # Get incoming state and transition IDs from the request
        incoming_state_ids = {
            state_data['id'] 
            for state_data in data.get('states', []) 
            if isinstance(state_data.get('id'), int)
        }
        
        # Process states
        temp_id_map = {}
        for state_data in data.get('states', []):
            state_id = state_data.get('id')
            
            if isinstance(state_id, str) and state_id.startswith('temp-'):
                # Create new state
                new_state = FlowState(
                    flow_id=flow.id,
                    name=state_data.get('name', 'New State'),
                    state_type=models.StateType(state_data.get('state_type', 'SEND_MESSAGE')),
                    message_body=state_data.get('message_body'),
                    is_start_state=state_data.get('is_start_state', False),
                    state_config=state_data.get('state_config')
                )
                db.add(new_state)
                db.flush()  # Flush to get the new ID
                temp_id_map[state_id] = new_state.id
                
            elif isinstance(state_id, int):
                # Update existing state
                state_to_update = next((s for s in flow.states if s.id == state_id), None)
                if state_to_update:
                    state_to_update.name = state_data.get('name', state_to_update.name)
                    state_to_update.state_type = models.StateType(state_data.get('state_type', state_to_update.state_type))
                    state_to_update.message_body = state_data.get('message_body', state_to_update.message_body)
                    state_to_update.is_start_state = state_data.get('is_start_state', state_to_update.is_start_state)
                    state_to_update.state_config = state_data.get('state_config', state_to_update.state_config)

        # Delete states that are not in the incoming data
        states_to_delete = existing_state_ids - incoming_state_ids
        if states_to_delete:
            db.query(FlowState).filter(
                FlowState.id.in_(states_to_delete)
            ).delete(synchronize_session=False)

        db.flush() # Ensure all state changes are processed before handling transitions

        # Process transitions
        for state_data in data.get('states', []):
            source_state_id = temp_id_map.get(state_data.get('id'), state_data.get('id'))
            if not source_state_id:
                continue

            incoming_transition_ids = {
                t['id'] for t in state_data.get('outgoing_transitions', []) if isinstance(t.get('id'), int)
            }

            # Update existing transitions and create new ones
            for transition_data in state_data.get('outgoing_transitions', []):
                target_state_id = temp_id_map.get(transition_data.get('target_state_id'), transition_data.get('target_state_id'))
                
                if not target_state_id:
                    continue # Skip if target state is not resolved

                transition_id = transition_data.get('id')
                
                if isinstance(transition_id, str) and transition_id.startswith('temp-'):
                    # Create new transition
                    new_transition = FlowTransition(
                        source_state_id=source_state_id,
                        target_state_id=target_state_id,
                        trigger_type=models.TriggerType(transition_data.get('trigger_type')),
                        trigger_value=transition_data.get('trigger_value'),
                        action_id=transition_data.get('action_id')
                    )
                    db.add(new_transition)
                elif isinstance(transition_id, int):
                    # Update existing transition
                    transition_to_update = db.query(FlowTransition).filter(FlowTransition.id == transition_id).first()
                    if transition_to_update:
                        transition_to_update.target_state_id = target_state_id
                        transition_to_update.trigger_type = models.TriggerType(transition_data.get('trigger_type'))
                        transition_to_update.trigger_value = transition_data.get('trigger_value')
                        transition_to_update.action_id = transition_data.get('action_id')
            
            # Delete transitions that are not in the incoming data for this state
            source_state = next((s for s in flow.states if s.id == source_state_id), None)
            if source_state:
                state_existing_transition_ids = {t.id for t in source_state.outgoing_transitions}
                transitions_to_delete = state_existing_transition_ids - incoming_transition_ids
                if transitions_to_delete:
                    db.query(FlowTransition).filter(
                        FlowTransition.id.in_(transitions_to_delete)
                    ).delete(synchronize_session=False)

        # Set start state ID
        start_state_id = None
        for state_data in data.get('states', []):
            if state_data.get('is_start_state'):
                start_state_id = temp_id_map.get(state_data.get('id'), state_data.get('id'))
                break
        flow.start_state_id = start_state_id

        db.commit()
        
        return JSONResponse({"success": True, "message": "Flow saved successfully"})
        
    except Exception as e:
        logger.error(f"Error saving flow {flow_id}: {str(e)}")
        db.rollback()
        return JSONResponse({"success": False, "error": str(e)})


