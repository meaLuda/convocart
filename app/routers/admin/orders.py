"""
Orders module for admin interface
Handles order management and status updates
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi_csrf_protect import CsrfProtect
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.templates_config import templates
from app.routers.users import get_current_admin

router = APIRouter()
logger = logging.getLogger(__name__)

def check_admin_has_access_to_group(admin, group_id, db):
    """Check if an admin has access to a specific group"""
    if admin.role == models.UserRole.SUPER_ADMIN:
        return True
    
    # Check if admin is a member of this group
    return any(group.id == group_id for group in admin.groups)

@router.get("/admin/orders", response_class=HTMLResponse)
async def view_orders(
    request: Request,
    status: Optional[str] = None,
    page: int = 1,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """View and manage orders"""
    # Get the current admin user from the cookie
    current_admin = await get_current_admin(request, db)
    
    # Add debugging logs
    logger.info(f"Orders view: User {current_admin.username}, role: {current_admin.role}")
    group_ids = [group.id for group in current_admin.groups]
    logger.info(f"User groups: {group_ids}")
    
    # Base query for orders - initialize FIRST
    query = db.query(models.Order)
    
    # Filter orders by user's groups if not super admin
    if current_admin.role != models.UserRole.SUPER_ADMIN:
        if not current_admin.groups:
            logger.info(f"User {current_admin.username} has no groups, showing no orders")
            query = query.filter(False)
        else:
            group_ids = [group.id for group in current_admin.groups]
            logger.info(f"Filtering orders for groups: {group_ids}")
            # Apply the filter BEFORE any execution
            query = query.filter(models.Order.group_id.in_(group_ids))
            logger.info(f"SQL Query: {str(query.statement.compile(dialect=db.bind.dialect))}")
    
    # Apply additional filters (status filter)
    if status:
        try:
            order_status = models.OrderStatus(status)
            query = query.filter(models.Order.status == order_status)
        except ValueError:
            # Invalid status, ignore filter
            pass

    # Apply date range filter
    if start_date and end_date:
        try:
            start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
            end_date_obj = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(models.Order.created_at >= start_date_obj, models.Order.created_at < end_date_obj)
        except ValueError:
            # Invalid date format, ignore filter
            pass
    
    # Get total count for pagination
    total_orders = query.count()
    logger.info(f"Total filtered orders: {total_orders}")
    
    page_size = 20  # Number of orders per page
    # Get paginated orders
    orders = query.order_by(models.Order.created_at.desc()) \
        .offset((page - 1) * page_size) \
        .limit(page_size) \
        .all()
    
    # Optimize: Get customer information in bulk to avoid N+1 queries
    customer_ids = [order.customer_id for order in orders]
    customers = db.query(models.Customer).filter(models.Customer.id.in_(customer_ids)).all()
    customer_info = {customer.id: customer for customer in customers}
    
    # Map customers to orders
    order_customer_info = {}
    for order in orders:
        if order.customer_id in customer_info:
            order_customer_info[order.id] = customer_info[order.customer_id]
    
    # Calculate pagination info
    total_pages = (total_orders + page_size - 1) // page_size
    
    return templates.TemplateResponse(
        "orders.html",
        {
            "request": request,
            "admin": current_admin,
            "orders": orders,
            "customer_info": order_customer_info,
            "current_page": page,
            "total_pages": total_pages,
            "total_orders": total_orders,
            "status_filter": status,
            "order_statuses": [status.value for status in models.OrderStatus]
        }
    )

@router.post("/admin/orders/{order_id}/status")
async def update_order_status(
    request: Request,
    order_id: int,
    status: str = Form(...),
    payment_status: Optional[str] = Form(None),
    payment_ref: Optional[str] = Form(None),
    total_amount: Optional[float] = Form(None),
    notify_customer: bool = Form(False),
    csrf_protect: CsrfProtect = Depends(),
    db: Session = Depends(get_db)
):
    """Update order status and optionally notify customer"""
    # Log incoming CSRF token for debugging
    csrf_header = request.headers.get("X-CSRF-Token", "None")
    logger.info(f"Received CSRF token: {csrf_header[:20] if csrf_header != 'None' else 'None'}... (truncated)")
    
    # Validate CSRF token
    await csrf_protect.validate_csrf(request)
    
    # Get the current admin user
    current_admin = await get_current_admin(request, db)
    
    # Get the order
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Check if admin has access to this order's group
    if not check_admin_has_access_to_group(current_admin, order.group_id, db):
        raise HTTPException(status_code=403, detail="You don't have permission to update this order")

    # Get previous status for change detection
    previous_status = order.status
    previous_payment_status = order.payment_status
    
    try:
        # Update the order status using enum
        order.status = models.OrderStatus(status)
        
        # Update payment status if provided
        if payment_status:
            order.payment_status = models.PaymentStatus(payment_status)
        
        # Update payment reference if provided
        if payment_ref:
            if len(payment_ref) > 50:
                raise HTTPException(status_code=400, detail="Payment reference too long (max 50 characters)")
            order.payment_ref = payment_ref
        
        # Update total amount if provided
        if total_amount is not None:
            try:
                order.total_amount = float(total_amount)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid amount value")
        
        # Add a timestamp for the update
        order.updated_at = datetime.utcnow()
        db.commit()
        
        logger.info(f"Order {order.order_number} updated by {current_admin.username}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid status value: {str(e)}")
    
    # Notify customer if requested
    if notify_customer:
        # Check if we can send a notification (prevent duplicates)
        if not hasattr(order, 'can_send_notification') or order.can_send_notification():
            try:
                # Get customer information
                customer = db.query(models.Customer).filter(models.Customer.id == order.customer_id).first()
                if customer:
                    # Import the WhatsApp service directly and initialize with DB session
                    from app.services.whatsapp import WhatsAppService
                    whatsapp_service = WhatsAppService(db)
                    
                    # Get group name for personalized messages
                    group_name = order.group.name if order.group else "Our store"
                    
                    # Determine if we should use order update or payment update notification
                    if previous_payment_status != order.payment_status and order.payment_method:
                        # Payment status has changed, so send a payment update notification
                        payment_data = {
                            "order_number": order.order_number,
                            "payment_status": order.payment_status.value,
                            "payment_method": order.payment_method.value.replace('_', ' ').title(),
                            "payment_ref": order.payment_ref or "",
                            "amount": order.total_amount
                        }
                        
                        # Send payment status update notification
                        whatsapp_service.send_payment_status_update(
                            customer.phone_number,
                            payment_data
                        )
                    else:
                        # Send a comprehensive order status update
                        order_data = {
                            "order_number": order.order_number,
                            "status": order.status.value,
                            "group_name": group_name,
                            "total_amount": order.total_amount,
                            "created_at": order.created_at.strftime('%Y-%m-%d %H:%M'),
                            "order_details": order.order_details
                        }
                        
                        # Add payment information if available
                        if order.payment_method:
                            order_data["payment_method"] = order.payment_method.value.replace('_', ' ').title()
                            
                            if order.payment_status:
                                order_data["payment_status"] = order.payment_status.value.title()
                            
                            if order.payment_ref:
                                order_data["payment_ref"] = order.payment_ref
        
                        # Send order status update notification
                        whatsapp_service.send_order_status_update(
                            customer.phone_number,
                            order_data
                        )
                    
                    # Record that we sent a notification
                    if hasattr(order, 'record_notification'):
                        order.record_notification()
                        db.commit()
                    else:
                        # Fallback for existing orders without the notification tracking fields
                        # Store the last notification time in session to prevent duplicates
                        session_key = f"last_notification_{order.id}"
                        request.session[session_key] = datetime.utcnow().isoformat()
                    
                    # If order is completed, ask for feedback
                    if order.status == models.OrderStatus.COMPLETED and previous_status != models.OrderStatus.COMPLETED:
                        buttons = [
                            {"id": "feedback_good", "title": "👍 Great!"},
                            {"id": "feedback_ok", "title": "👌 It was OK"},
                            {"id": "feedback_bad", "title": "👎 Had issues"}
                        ]
                        whatsapp_service.send_quick_reply_buttons(
                            customer.phone_number, 
                            "How was your experience with this order? We'd love your feedback!",
                            buttons
                        )
            except Exception as e:
                logger.error(f"Error sending notification: {str(e)}")
                # Continue with redirect even if notification fails
        else:
            logger.info(f"Skipping duplicate notification for order {order.order_number}")
    
    # Redirect back to the orders page
    return RedirectResponse(url="/admin/orders", status_code=303)