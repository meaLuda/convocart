"""
DataTables API endpoints for server-side processing
Provides efficient data handling for large datasets
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, asc, func
from fastapi_csrf_protect.flexible import CsrfProtect

from app.database import get_db
from app import models
from app.routers.users import get_current_admin

router = APIRouter(prefix="/api/datatables", tags=["datatables"])
logger = logging.getLogger(__name__)

@router.get("/orders")
async def orders_datatable(
    request: Request,
    draw: int = Query(..., description="Draw counter"),
    start: int = Query(0, description="Paging first record indicator"),
    length: int = Query(10, description="Number of records to display"),
    search_value: str = Query("", alias="search[value]", description="Global search value"),
    order_column: int = Query(0, alias="order[0][column]", description="Column to order data by"),
    order_dir: str = Query("asc", alias="order[0][dir]", description="Order direction"),
    csrf_protect: CsrfProtect = Depends(),
    db: Session = Depends(get_db)
):
    """Server-side processing for Orders DataTable"""
    try:
        # Get current admin user
        current_admin = await get_current_admin(request, db)
        
        # Base query for orders with eager loading to avoid N+1 queries
        from sqlalchemy.orm import joinedload
        query = db.query(models.Order).options(
            joinedload(models.Order.customer),
            joinedload(models.Order.group)
        )
        
        # Filter orders by user's groups if not super admin
        if current_admin.role != models.UserRole.SUPER_ADMIN:
            if not current_admin.groups:
                query = query.filter(False)  # Empty result set
            else:
                group_ids = [group.id for group in current_admin.groups]
                query = query.filter(models.Order.group_id.in_(group_ids))
        
        # Get total count before filtering
        total_records = query.count()
        
        # Apply global search if provided
        if search_value:
            search_filter = or_(
                models.Order.order_number.ilike(f"%{search_value}%"),
                models.Customer.name.ilike(f"%{search_value}%"),
                models.Customer.phone_number.ilike(f"%{search_value}%"),
                models.Order.order_details.ilike(f"%{search_value}%"),
                models.Order.payment_ref.ilike(f"%{search_value}%")
            )
            query = query.filter(search_filter)
        
        # Get filtered count
        filtered_records = query.count()
        
        # Apply ordering - updated for cleaner structure
        if current_admin.role == models.UserRole.SUPER_ADMIN:
            order_columns = [
                models.Order.order_number,      # 0
                models.Customer.name,           # 1  
                None,                           # 2 - Group (not sortable)
                models.Order.status,            # 3
                models.Order.payment_status,    # 4
                models.Order.total_amount,      # 5
                models.Order.created_at,        # 6
                None                            # 7 - Actions (not sortable)
            ]
        else:
            order_columns = [
                models.Order.order_number,      # 0
                models.Customer.name,           # 1
                models.Order.status,            # 2
                models.Order.payment_status,    # 3
                models.Order.total_amount,      # 4
                models.Order.created_at,        # 5
                None                            # 6 - Actions (not sortable)
            ]
        
        if 0 <= order_column < len(order_columns) and order_columns[order_column] is not None:
            column = order_columns[order_column]
            if order_dir == "desc":
                query = query.order_by(desc(column))
            else:
                query = query.order_by(asc(column))
        else:
            # Default ordering by created_at desc
            query = query.order_by(desc(models.Order.created_at))
        
        # Apply pagination
        orders = query.offset(start).limit(length).all()
        
        # Format data for DataTables - Clean and modern design
        data = []
        for order in orders:
            # Clean customer info
            customer_name = order.customer.name if order.customer else f"Customer #{order.customer_id}"
            customer_phone = order.customer.phone_number if order.customer else ""
            customer_initial = customer_name[0].upper() if customer_name and customer_name[0].isalpha() else 'C'
            
            # Clean, minimal customer display
            customer_display = f"""
                <div class="flex items-center space-x-3">
                    <div class="w-8 h-8 bg-indigo-500 rounded-full flex items-center justify-center text-white text-sm font-medium">
                        {customer_initial}
                    </div>
                    <div>
                        <div class="text-sm font-medium text-gray-900">{customer_name[:25]}</div>
                        <div class="text-xs text-gray-500">{customer_phone}</div>
                    </div>
                </div>
            """
            
            # Clean group info (for super admin)
            group_display = ""
            if current_admin.role == models.UserRole.SUPER_ADMIN:
                group_name = order.group.name if order.group else f"Group #{order.group_id}"
                group_display = f"""
                    <div class="text-sm font-medium text-gray-900">{group_name[:20]}</div>
                """
            
            # Clean status badge
            status_colors = {
                'pending': 'bg-yellow-100 text-yellow-800',
                'processing': 'bg-blue-100 text-blue-800',
                'completed': 'bg-green-100 text-green-800',
                'cancelled': 'bg-red-100 text-red-800',
                'refunded': 'bg-purple-100 text-purple-800'
            }
            
            status_class = status_colors.get(order.status.value, status_colors['pending'])
            status_display = f"""
                <span class="px-2 py-1 text-xs font-medium rounded-full {status_class}">
                    {order.status.value.title()}
                </span>
            """
            
            # Clean payment info display
            if order.payment_method:
                payment_method = order.payment_method.value.replace('_', ' ').title()
                payment_status = order.payment_status.value.title() if order.payment_status else 'Unpaid'
                payment_ref = f"#{order.payment_ref}" if order.payment_ref else ""
                
                payment_display = f"""
                    <div>
                        <div class="text-sm font-medium text-gray-900">{payment_method}</div>
                        <div class="text-xs text-gray-500">{payment_status} {payment_ref}</div>
                    </div>
                """
            else:
                payment_display = '<span class="text-sm text-gray-400">Not specified</span>'
            
            # Comprehensive but organized actions form
            order_statuses = ['pending', 'processing', 'completed', 'cancelled', 'refunded']
            payment_statuses = ['unpaid', 'paid', 'verified', 'failed', 'refunded']
            
            # Status dropdown options
            status_options = ""
            for status in order_statuses:
                selected = "selected" if order.status.value == status else ""
                status_options += f'<option value="{status}" {selected}>{status.title()}</option>'
            
            # Payment status dropdown options  
            payment_options = ""
            for p_status in payment_statuses:
                selected = "selected" if order.payment_status and order.payment_status.value == p_status else ""
                payment_options += f'<option value="{p_status}" {selected}>{p_status.title()}</option>'
            
            # Generate CSRF token for this form
            csrf_token, signed_token = csrf_protect.generate_csrf_tokens()
            
            actions = f'''
                <div class="w-48">
                    <form method="POST" action="/admin/orders/{order.id}/status" class="order-update-form space-y-2" data-order-id="{order.id}">
                        <input type="hidden" name="csrf_token" value="{csrf_token}">
                        <!-- Order Status -->
                        <div>
                            <label class="block text-xs font-medium text-gray-700 mb-1">Status</label>
                            <select name="status" class="w-full text-sm border border-gray-300 rounded px-2 py-1 focus:ring-1 focus:ring-indigo-500">
                                {status_options}
                            </select>
                        </div>
                        
                        <!-- Payment Status & Reference -->
                        <div class="grid grid-cols-2 gap-2">
                            <div>
                                <label class="block text-xs font-medium text-gray-700 mb-1">Payment</label>
                                <select name="payment_status" class="w-full text-sm border border-gray-300 rounded px-2 py-1 focus:ring-1 focus:ring-indigo-500">
                                    {payment_options}
                                </select>
                            </div>
                            <div>
                                <label class="block text-xs font-medium text-gray-700 mb-1">Ref</label>
                                <input type="text" name="payment_ref" placeholder="Ref#" 
                                    value="{order.payment_ref or ''}" 
                                    class="w-full text-sm border border-gray-300 rounded px-2 py-1 focus:ring-1 focus:ring-indigo-500">
                            </div>
                        </div>
                        
                        <!-- Amount -->
                        <div>
                            <label class="block text-xs font-medium text-gray-700 mb-1">Amount (KSh)</label>
                            <input type="number" name="total_amount" 
                                value="{order.total_amount or 0}" step="0.01" min="0"
                                class="w-full text-sm border border-gray-300 rounded px-2 py-1 focus:ring-1 focus:ring-indigo-500">
                        </div>
                        
                        <!-- Actions Row -->
                        <div class="flex items-center justify-between pt-1">
                            <label class="inline-flex items-center">
                                <input type="checkbox" name="notify_customer" value="True" 
                                    class="h-3 w-3 text-indigo-600 focus:ring-indigo-500 border-gray-300 rounded">
                                <span class="ml-1 text-xs text-gray-600">Notify</span>
                            </label>
                            <button type="submit" class="update-btn bg-indigo-600 text-white text-sm px-3 py-1 rounded hover:bg-indigo-700 focus:ring-1 focus:ring-indigo-500">
                                Save
                            </button>
                        </div>
                        
                        <!-- Feedback -->
                        <div class="update-feedback hidden mt-2 p-2 text-xs rounded-md"></div>
                    </form>
                </div>
            '''
            
            # Clean, simple displays
            order_number_display = f'<div class="font-mono text-sm font-medium">{order.order_number}</div>'
            
            amount_display = f'<div class="text-sm font-medium">KSh {order.total_amount:.2f}</div>'
            
            date_display = f'''
                <div>
                    <div class="text-sm">{order.created_at.strftime("%b %d, %Y")}</div>
                    <div class="text-xs text-gray-500">{order.created_at.strftime("%H:%M")}</div>
                </div>
            '''
            
            row_data = [
                order_number_display,
                customer_display,
                status_display,
                payment_display,
                amount_display,
                date_display,
                actions
            ]
            
            # Add group column for super admin
            if current_admin.role == models.UserRole.SUPER_ADMIN:
                row_data.insert(2, group_display)
            
            data.append(row_data)
        
        response = {
            "draw": draw,
            "recordsTotal": total_records,
            "recordsFiltered": filtered_records,
            "data": data
        }
        
        return response
        
    except Exception as e:
        logger.error(f"Error in orders_datatable: {str(e)}")
        return {
            "draw": draw,
            "recordsTotal": 0,
            "recordsFiltered": 0,
            "data": [],
            "error": str(e)
        }

@router.get("/orders/status-counts")
async def orders_status_counts(
    request: Request,
    db: Session = Depends(get_db)
):
    """Get order status counts for dashboard"""
    try:
        # Get current admin user
        current_admin = await get_current_admin(request, db)
        
        # Base query for orders
        query = db.query(models.Order)
        
        # Filter orders by user's groups if not super admin
        if current_admin.role != models.UserRole.SUPER_ADMIN:
            if not current_admin.groups:
                # Return empty counts if user has no groups
                return {
                    "total": 0,
                    "pending": 0,
                    "processing": 0,
                    "completed": 0,
                    "cancelled": 0,
                    "refunded": 0
                }
            else:
                group_ids = [group.id for group in current_admin.groups]
                query = query.filter(models.Order.group_id.in_(group_ids))
        
        # Get counts by status
        from sqlalchemy import case
        counts = db.query(
            func.count(models.Order.id).label('total'),
            func.sum(case([(models.Order.status == 'pending', 1)], else_=0)).label('pending'),
            func.sum(case([(models.Order.status == 'processing', 1)], else_=0)).label('processing'),
            func.sum(case([(models.Order.status == 'completed', 1)], else_=0)).label('completed'),
            func.sum(case([(models.Order.status == 'cancelled', 1)], else_=0)).label('cancelled'),
            func.sum(case([(models.Order.status == 'refunded', 1)], else_=0)).label('refunded')
        ).filter(query.whereclause if query.whereclause is not None else True).first()
        
        return {
            "total": int(counts.total or 0),
            "pending": int(counts.pending or 0),
            "processing": int(counts.processing or 0),
            "completed": int(counts.completed or 0),
            "cancelled": int(counts.cancelled or 0),
            "refunded": int(counts.refunded or 0)
        }
        
    except Exception as e:
        logger.error(f"Error in orders_status_counts: {str(e)}")
        return {
            "total": 0,
            "pending": 0,
            "processing": 0,
            "completed": 0,
            "cancelled": 0,
            "refunded": 0
        }

@router.get("/groups")
async def groups_datatable(
    request: Request,
    draw: int = Query(..., description="Draw counter"),
    start: int = Query(0, description="Paging first record indicator"),
    length: int = Query(10, description="Number of records to display"),
    search_value: str = Query("", alias="search[value]", description="Global search value"),
    order_column: int = Query(0, alias="order[0][column]", description="Column to order data by"),
    order_dir: str = Query("asc", alias="order[0][dir]", description="Order direction"),
    db: Session = Depends(get_db)
):
    """Server-side processing for Groups DataTable"""
    try:
        # Get current admin user
        current_admin = await get_current_admin(request, db)
        
        # Base query for groups
        query = db.query(models.Group)
        
        # Filter groups by user's access if not super admin
        if current_admin.role != models.UserRole.SUPER_ADMIN:
            if not current_admin.groups:
                query = query.filter(False)  # Empty result set
            else:
                group_ids = [group.id for group in current_admin.groups]
                query = query.filter(models.Group.id.in_(group_ids))
        
        # Get total count before filtering
        total_records = query.count()
        
        # Apply global search if provided
        if search_value:
            search_filter = or_(
                models.Group.name.ilike(f"%{search_value}%"),
                models.Group.identifier.ilike(f"%{search_value}%"),
                models.Group.description.ilike(f"%{search_value}%")
            )
            query = query.filter(search_filter)
        
        # Get filtered count
        filtered_records = query.count()
        
        # Apply ordering
        order_columns = [
            models.Group.name,              # 0
            models.Group.identifier,        # 1
            models.Group.business_type,     # 2
            models.Group.created_at,        # 3
            None                            # 4 - Actions (not sortable)
        ]
        
        if 0 <= order_column < len(order_columns) and order_columns[order_column] is not None:
            column = order_columns[order_column]
            if order_dir == "desc":
                query = query.order_by(desc(column))
            else:
                query = query.order_by(asc(column))
        else:
            # Default ordering by name asc
            query = query.order_by(asc(models.Group.name))
        
        # Apply pagination
        groups = query.offset(start).limit(length).all()
        
        # Format data for DataTables
        data = []
        for group in groups:
            # Group info
            group_name = f'<div class="font-semibold text-gray-900">{group.name}</div>'
            if group.description:
                group_name += f'<div class="text-xs text-gray-500 mt-1">{group.description[:100]}...</div>'
            
            # Business type
            business_type = group.business_type.value.replace('_', ' ').title() if group.business_type else "Not specified"
            
            # Stats - optimize with subqueries
            from sqlalchemy import func
            stats_query = db.query(
                func.count(models.Order.id).label('order_count'),
                func.count(models.Customer.id).label('customer_count')
            ).select_from(models.Group).outerjoin(
                models.Order, models.Order.group_id == group.id
            ).outerjoin(
                models.Customer, models.Customer.group_id == group.id
            ).filter(models.Group.id == group.id).first()
            
            order_count = stats_query.order_count or 0
            customer_count = stats_query.customer_count or 0
            stats = f"""
                <div class="text-sm">
                    <div>{order_count} orders</div>
                    <div class="text-xs text-gray-500">{customer_count} customers</div>
                </div>
            """
            
            # Actions
            actions = f'''
                <div class="flex space-x-2">
                    <a href="/admin/groups/{group.id}" class="btn btn-sm btn-ghost" title="View Details">
                        <i class="fas fa-eye"></i>
                    </a>
                    <a href="/admin/groups/{group.id}/edit" class="btn btn-sm btn-ghost" title="Edit">
                        <i class="fas fa-edit"></i>
                    </a>
                    <button class="btn btn-sm btn-ghost text-red-600 delete-group-btn" data-group-id="{group.id}" title="Delete">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            '''
            
            row_data = [
                group_name,
                f'<code class="text-sm bg-gray-100 px-2 py-1 rounded">{group.identifier}</code>',
                f'<span class="badge badge-secondary">{business_type}</span>',
                stats,
                f'<div class="text-sm text-gray-900">{group.created_at.strftime("%b %d, %Y")}</div>',
                actions
            ]
            
            data.append(row_data)
        
        response = {
            "draw": draw,
            "recordsTotal": total_records,
            "recordsFiltered": filtered_records,
            "data": data
        }
        
        return response
        
    except Exception as e:
        logger.error(f"Error in groups_datatable: {str(e)}")
        return {
            "draw": draw,
            "recordsTotal": 0,
            "recordsFiltered": 0,
            "data": [],
            "error": str(e)
        }