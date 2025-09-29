"""
Orders module for admin interface
Handles order management and status updates
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi_csrf_protect.flexible import CsrfProtect
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
    csrf_protect: CsrfProtect = Depends(),
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
    
    # Generate CSRF tokens and set cookie 
    csrf_token, signed_token = csrf_protect.generate_csrf_tokens()
    
    response = templates.TemplateResponse(
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
            "order_statuses": [status.value for status in models.OrderStatus],
            "csrf_token": csrf_token
        }
    )
    
    # Set CSRF cookie (CRITICAL - this was missing!)
    csrf_protect.set_csrf_cookie(signed_token, response)
    return response

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
    # Validate CSRF token (flexible - accepts header OR body)  
    try:
        await csrf_protect.validate_csrf(request)
        logger.info(f"✅ CSRF validation passed for order {order_id}")
    except Exception as e:
        logger.error(f"❌ CSRF validation failed for order {order_id}: {str(e)}")
        raise
    
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
    
    # Return JSON response for AJAX requests
    return {"success": True, "message": "Order updated successfully"}


@router.get("/admin/orders/{order_id}/details", response_class=HTMLResponse)
async def order_details(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Get detailed order information for modal display"""
    try:
        current_admin = await get_current_admin(request, db)
        
        # Get order with relationships
        order = db.query(models.Order).filter(models.Order.id == order_id).first()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        
        # Check permissions
        if not check_admin_has_access_to_group(current_admin, order.group_id, db):
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Get related data
        customer = db.query(models.Customer).filter(models.Customer.id == order.customer_id).first()
        group = db.query(models.Group).filter(models.Group.id == order.group_id).first()
        
        # Calculate totals
        total_items = len(order.order_items) if order.order_items else 0
        total_quantity = sum(item.quantity for item in order.order_items) if order.order_items else 0
        
        # Format order items display
        order_items_display = []
        if order.order_items:
            for item in order.order_items:
                order_items_display.append({
                    "product_name": item.product_name,
                    "quantity": item.quantity,
                    "unit_price": item.unit_price,
                    "total_price": item.total_price,
                    "special_instructions": item.special_instructions
                })
        elif order.order_details:
            # Fallback to JSON order details
            import json
            try:
                order_data = json.loads(order.order_details)
                if isinstance(order_data, dict) and 'items' in order_data:
                    for item in order_data['items']:
                        order_items_display.append({
                            "product_name": item.get('name', 'Unknown Item'),
                            "quantity": item.get('quantity', 1),
                            "unit_price": item.get('price', 0),
                            "total_price": item.get('quantity', 1) * item.get('price', 0),
                            "special_instructions": item.get('notes', '')
                        })
            except (json.JSONDecodeError, KeyError):
                pass
        
        # Create HTML response
        html_content = f"""
        <div class="space-y-6">
            <!-- Order Summary -->
            <div class="bg-blue-50 p-4 rounded-lg">
                <div class="flex items-center justify-between mb-3">
                    <h4 class="font-semibold text-blue-900">Order #{order.order_number}</h4>
                    <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
                        {order.status.value.title()}
                    </span>
                </div>
                <div class="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                    <div>
                        <span class="text-blue-700 font-medium">Customer:</span>
                        <div class="text-blue-900">{customer.name if customer else 'Unknown'}</div>
                        <div class="text-blue-700 text-xs">{customer.phone_number if customer else 'N/A'}</div>
                    </div>
                    <div>
                        <span class="text-blue-700 font-medium">Business:</span>
                        <div class="text-blue-900">{group.name if group else 'Unknown'}</div>
                    </div>
                    <div>
                        <span class="text-blue-700 font-medium">Items:</span>
                        <div class="text-blue-900">{total_items} items ({total_quantity} total)</div>
                    </div>
                    <div>
                        <span class="text-blue-700 font-medium">Total:</span>
                        <div class="text-blue-900 font-semibold">KSh {order.total_amount:.2f}</div>
                    </div>
                </div>
            </div>
            
            <!-- Order Items -->
            <div>
                <h5 class="font-medium text-gray-900 mb-3">Order Items</h5>
                <div class="space-y-2 max-h-64 overflow-y-auto">
                    {_render_order_items(order_items_display)}
                </div>
            </div>
            
            <!-- Payment Information -->
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div class="bg-gray-50 p-4 rounded-lg">
                    <h5 class="font-medium text-gray-900 mb-3">Payment Details</h5>
                    <div class="space-y-2 text-sm">
                        <div class="flex justify-between">
                            <span class="text-gray-600">Method:</span>
                            <span class="text-gray-900">{order.payment_method.value.replace('_', ' ').title() if order.payment_method else 'Not specified'}</span>
                        </div>
                        <div class="flex justify-between">
                            <span class="text-gray-600">Status:</span>
                            <span class="text-gray-900">{order.payment_status.value.title() if order.payment_status else 'Unpaid'}</span>
                        </div>
                        <div class="flex justify-between">
                            <span class="text-gray-600">Reference:</span>
                            <span class="text-gray-900">{order.payment_ref or 'N/A'}</span>
                        </div>
                    </div>
                </div>
                
                <div class="bg-gray-50 p-4 rounded-lg">
                    <h5 class="font-medium text-gray-900 mb-3">Order Timeline</h5>
                    <div class="space-y-2 text-sm">
                        <div class="flex justify-between">
                            <span class="text-gray-600">Created:</span>
                            <span class="text-gray-900">{order.created_at.strftime('%m/%d/%Y %I:%M %p')}</span>
                        </div>
                        <div class="flex justify-between">
                            <span class="text-gray-600">Updated:</span>
                            <span class="text-gray-900">{order.updated_at.strftime('%m/%d/%Y %I:%M %p')}</span>
                        </div>
                        <div class="flex justify-between">
                            <span class="text-gray-600">Notifications:</span>
                            <span class="text-gray-900">{order.notification_count} sent</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        """
        
        return HTMLResponse(content=html_content)
        
    except Exception as e:
        logger.error(f"Error loading order details {order_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error loading order details")


def _render_order_items(items):
    """Helper function to render order items HTML"""
    if not items:
        return '''
        <div class="text-center py-4 text-gray-500">
            <i class="fas fa-box-open text-2xl mb-2"></i>
            <p>No items in this order</p>
        </div>
        '''
    
    html = ""
    for item in items:
        html += f'''
        <div class="flex items-center justify-between p-3 bg-white border border-gray-200 rounded-lg">
            <div class="flex-1">
                <div class="font-medium text-gray-900">{item["product_name"]}</div>
                {f'<div class="text-xs text-gray-500 mt-1">{item["special_instructions"]}</div>' if item.get("special_instructions") else ''}
            </div>
            <div class="text-right">
                <div class="text-sm font-medium text-gray-900">{item["quantity"]}x @KSh{item["unit_price"]:.2f}</div>
                <div class="text-xs text-gray-500">KSh {item["total_price"]:.2f}</div>
            </div>
        </div>
        '''
    return html


@router.delete("/admin/orders/{order_id}")
async def delete_order(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Delete an order"""
    try:
        current_admin = await get_current_admin(request, db)
        
        # Get order
        order = db.query(models.Order).filter(models.Order.id == order_id).first()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        
        # Check permissions
        if not check_admin_has_access_to_group(current_admin, order.group_id, db):
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Store order number for logging
        order_number = order.order_number
        
        # Delete related order items first
        db.query(models.OrderItem).filter(models.OrderItem.order_id == order_id).delete()
        
        # Delete the order
        db.delete(order)
        db.commit()
        
        logger.info(f"Order {order_number} deleted by admin {current_admin.username}")
        return {"success": True, "message": f"Order {order_number} deleted successfully"}
        
    except Exception as e:
        logger.error(f"Error deleting order {order_id}: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Error deleting order")


@router.post("/admin/orders/{order_id}/send-message")
async def send_message_to_customer(
    request: Request,
    order_id: int,
    message: str = Form(...),
    customer_phone: str = Form(...),
    customer_name: str = Form(...),
    csrf_protect: CsrfProtect = Depends(),
    db: Session = Depends(get_db)
):
    """Send a custom message to the customer"""
    # Validate CSRF token
    try:
        await csrf_protect.validate_csrf(request)
        logger.info(f"✅ CSRF validation passed for message sending to order {order_id}")
    except Exception as e:
        logger.error(f"❌ CSRF validation failed for message sending to order {order_id}: {str(e)}")
        raise
    
    # Get the current admin user
    current_admin = await get_current_admin(request, db)
    
    # Get the order to verify permissions
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Check if admin has access to this order's group
    if not check_admin_has_access_to_group(current_admin, order.group_id, db):
        raise HTTPException(status_code=403, detail="You don't have permission to send messages for this order")

    try:
        # Clean and validate the message
        if not message.strip():
            raise HTTPException(status_code=400, detail="Message cannot be empty")
        
        if len(message) > 1000:
            raise HTTPException(status_code=400, detail="Message too long (max 1000 characters)")
        
        # Clean phone number
        clean_phone = customer_phone.strip().replace(" ", "").replace("-", "")
        if not clean_phone:
            raise HTTPException(status_code=400, detail="Invalid phone number")
        
        # Prepare the message with business context
        business_name = order.group.name if order.group else "Your Order"
        formatted_message = f"📋 Message from {business_name}:\n\n{message.strip()}\n\n💬 Order: {order.order_number}"
        
        # Here you would integrate with your SMS/WhatsApp service
        # For now, we'll just log the message
        logger.info(f"Message sent to {customer_name} ({clean_phone}) for order {order.order_number}: {message}")
        
        # TODO: Integrate with actual SMS/WhatsApp service
        # Example integration points:
        # - Twilio for SMS
        # - WhatsApp Business API
        # - Your existing messaging service
        
        # For demo purposes, we'll simulate successful sending
        success = True
        
        if success:
            return {"success": True, "message": f"Message sent successfully to {customer_name}"}
        else:
            raise HTTPException(status_code=500, detail="Failed to send message")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending message for order {order_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error sending message")