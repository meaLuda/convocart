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
            joinedload(models.Order.group),
            joinedload(models.Order.order_items)
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
            from app.utils.sql_security import escape_sql_pattern
            safe_search = escape_sql_pattern(search_value)
            search_filter = or_(
                models.Order.order_number.ilike(f"%{safe_search}%", escape='\\'),
                models.Customer.name.ilike(f"%{safe_search}%", escape='\\'),
                models.Customer.phone_number.ilike(f"%{safe_search}%", escape='\\'),
                models.Order.order_details.ilike(f"%{safe_search}%", escape='\\'),
                models.Order.payment_ref.ilike(f"%{safe_search}%", escape='\\')
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
                None,                           # 3 - Products (not sortable)
                models.Order.status,            # 4
                models.Order.payment_status,    # 5
                models.Order.total_amount,      # 6
                models.Order.created_at,        # 7
                None                            # 8 - Actions (not sortable)
            ]
        else:
            order_columns = [
                models.Order.order_number,      # 0
                models.Customer.name,           # 1
                None,                           # 2 - Products (not sortable)
                models.Order.status,            # 3
                models.Order.payment_status,    # 4
                models.Order.total_amount,      # 5
                models.Order.created_at,        # 6
                None                            # 7 - Actions (not sortable)
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
            
            # Products display with proper counting
            products_display = ""
            total_items = 0
            total_quantity = 0
            
            if order.order_items:
                # Count total items and quantity
                total_items = len(order.order_items)
                total_quantity = sum(item.quantity for item in order.order_items)
                
                # Show up to 3 products, then show count if more
                items_to_show = order.order_items[:3]
                product_list = []
                for item in items_to_show:
                    quantity = item.quantity
                    name = item.product_name[:20] + ("..." if len(item.product_name) > 20 else "")
                    unit_price = item.unit_price or 0
                    product_list.append(f"{quantity}x {name} @KSh{unit_price:.0f}")
                
                products_text = "<br>".join(product_list)
                
                if total_items > 3:
                    additional_count = total_items - 3
                    products_text += f"<br><span class='text-xs text-gray-500'>+{additional_count} more items</span>"
                
                products_display = f"""
                    <div class="text-sm">
                        <div class="font-medium text-gray-900 mb-1">
                            <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-800">
                                {total_items} items ({total_quantity} total)
                            </span>
                        </div>
                        <div class="text-gray-700 text-xs leading-relaxed">
                            {products_text}
                        </div>
                    </div>
                """
            else:
                # Fallback to order_details if no order_items
                import json
                try:
                    if order.order_details:
                        order_data = json.loads(order.order_details)
                        if isinstance(order_data, dict) and 'items' in order_data:
                            items = order_data['items'][:3]  # Show first 3
                            total_items = len(order_data.get('items', []))
                            total_quantity = sum(item.get('quantity', 1) for item in order_data.get('items', []))
                            
                            product_list = []
                            for item in items:
                                if isinstance(item, dict):
                                    name = item.get('name', 'Unknown Item')[:20]
                                    quantity = item.get('quantity', 1)
                                    price = item.get('price', 0)
                                    product_list.append(f"{quantity}x {name} @KSh{price:.0f}")
                            
                            products_text = "<br>".join(product_list)
                            if total_items > 3:
                                additional_count = total_items - 3
                                products_text += f"<br><span class='text-xs text-gray-500'>+{additional_count} more items</span>"
                            
                            products_display = f"""
                                <div class="text-sm">
                                    <div class="font-medium text-gray-900 mb-1">
                                        <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-800">
                                            {total_items} items ({total_quantity} total)
                                        </span>
                                    </div>
                                    <div class="text-gray-700 text-xs leading-relaxed">
                                        {products_text}
                                    </div>
                                </div>
                            """
                        else:
                            products_display = '''
                                <div class="text-sm">
                                    <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-yellow-100 text-yellow-800">
                                        <i class="fas fa-info-circle mr-1"></i>
                                        Details in JSON
                                    </span>
                                </div>
                            '''
                    else:
                        products_display = '''
                            <div class="text-sm">
                                <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-600">
                                    <i class="fas fa-minus-circle mr-1"></i>
                                    No items
                                </span>
                            </div>
                        '''
                except (json.JSONDecodeError, KeyError):
                    products_display = '''
                        <div class="text-sm">
                            <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-red-100 text-red-800">
                                <i class="fas fa-exclamation-triangle mr-1"></i>
                                Invalid data
                            </span>
                        </div>
                    '''
            
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
            
            # Enhanced Alpine.js modal action buttons (restored popup approach)
            actions = f'''
                <div class="flex items-center space-x-1">
                    <!-- View Order Details -->
                    <button @click="openDetailsModal({order.id})" 
                            class="table-action-btn bg-blue-50 hover:bg-blue-100 text-blue-600 p-1.5 rounded" 
                            title="View Details">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path>
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"></path>
                        </svg>
                    </button>
                    
                    <!-- Quick Actions Modal -->
                    <button @click="openQuickActionsModal({order.id}, '{order.status.value}', '{order.payment_status.value if order.payment_status else 'unpaid'}')" 
                            class="table-action-btn bg-green-50 hover:bg-green-100 text-green-600 p-1.5 rounded" 
                            title="Quick Actions">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path>
                        </svg>
                    </button>
                    
                    <!-- Send Message -->
                    <button @click="openMessageModal({order.id}, '{customer_name.replace("'", "\\'")}', '{customer_phone}')" 
                            class="table-action-btn bg-purple-50 hover:bg-purple-100 text-purple-600 p-1.5 rounded" 
                            title="Send Message">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"></path>
                        </svg>
                    </button>
                    
                    <!-- Delete Order -->
                    <button @click="openDeleteModal({order.id}, '{order.order_number}')" 
                            class="table-action-btn bg-red-50 hover:bg-red-100 text-red-600 p-1.5 rounded" 
                            title="Delete Order">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
                        </svg>
                    </button>
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
                products_display,
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
        
        # Get counts by status - use enum values, not strings
        from sqlalchemy import case
        counts = db.query(
            func.count(models.Order.id).label('total'),
            func.sum(case((models.Order.status == models.OrderStatus.PENDING, 1), else_=0)).label('pending'),
            func.sum(case((models.Order.status == models.OrderStatus.PROCESSING, 1), else_=0)).label('processing'),
            func.sum(case((models.Order.status == models.OrderStatus.COMPLETED, 1), else_=0)).label('completed'),
            func.sum(case((models.Order.status == models.OrderStatus.CANCELLED, 1), else_=0)).label('cancelled'),
            func.sum(case((models.Order.status == models.OrderStatus.REFUNDED, 1), else_=0)).label('refunded')
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
            from app.utils.sql_security import escape_sql_pattern
            safe_search = escape_sql_pattern(search_value)
            search_filter = or_(
                models.Group.name.ilike(f"%{safe_search}%", escape='\\'),
                models.Group.identifier.ilike(f"%{safe_search}%", escape='\\'),
                models.Group.description.ilike(f"%{safe_search}%", escape='\\')
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


@router.get("/products")
async def products_datatable(
    request: Request,
    draw: int = Query(..., description="Draw counter"),
    start: int = Query(0, description="Paging first record indicator"),
    length: int = Query(10, description="Number of records to display"),
    search_value: str = Query("", alias="search[value]", description="Global search value"),
    order_column: int = Query(0, alias="order[0][column]", description="Column to order data by"),
    order_dir: str = Query("asc", alias="order[0][dir]", description="Order direction"),
    group_id: Optional[int] = Query(None, description="Filter by group ID"),
    csrf_protect: CsrfProtect = Depends(),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    """DataTables endpoint for products inventory"""
    try:
        # Base query for active products
        query = db.query(models.Product).filter(models.Product.is_active == True)
        
        # Filter by group if specified
        if group_id:
            query = query.filter(models.Product.group_id == group_id)
        
        # Apply search filter
        if search_value:
            from app.utils.sql_security import escape_sql_pattern
            safe_search = escape_sql_pattern(search_value)
            search_pattern = f"%{safe_search}%"
            query = query.filter(
                or_(
                    models.Product.name.ilike(search_pattern, escape='\\'),
                    models.Product.description.ilike(search_pattern, escape='\\'),
                    models.Product.sku.ilike(search_pattern, escape='\\')
                )
            )
        
        # Get total records count
        total_records = db.query(models.Product).filter(models.Product.is_active == True).count()
        filtered_records = query.count()
        
        # Apply ordering
        column_mapping = {
            0: models.Product.name,
            1: models.Product.group_id,
            2: models.Product.stock_quantity,
            3: models.Product.base_price,
            4: models.Product.updated_at
        }
        
        order_col = column_mapping.get(order_column, models.Product.name)
        if order_dir == "desc":
            query = query.order_by(desc(order_col))
        else:
            query = query.order_by(asc(order_col))
        
        # Apply pagination
        products = query.offset(start).limit(length).all()
        
        # Format data for DataTables
        data = []
        for product in products:
            # Get stock status
            stock_count = product.stock_quantity or 0
            threshold = product.low_stock_threshold or 0
            
            if stock_count <= 0:
                stock_status = '<span class="badge badge-danger">Out of Stock</span>'
            elif stock_count <= threshold:
                stock_status = '<span class="badge badge-warning">Low Stock</span>'
            else:
                stock_status = '<span class="badge badge-success">In Stock</span>'
            
            # Product info with icon
            product_display = f'''
                <div class="flex items-center">
                    <div class="w-10 h-10 bg-primary-100 rounded-lg flex items-center justify-center">
                        <i class="fas fa-box text-primary-600"></i>
                    </div>
                    <div class="ml-4">
                        <div class="text-sm font-medium text-gray-900">{product.name}</div>
                        <div class="text-sm text-gray-500">SKU: {product.sku or 'N/A'}</div>
                    </div>
                </div>
            '''
            
            # Group info
            group_display = f'''
                <div class="text-sm text-gray-900">{product.group.name if product.group else 'N/A'}</div>
                <div class="text-sm text-gray-500">{product.category.value if product.category else 'Uncategorized'}</div>
            '''
            
            # Stock info
            stock_display = f'''
                <div class="text-sm font-medium text-gray-900">{stock_count}</div>
                <div class="text-sm text-gray-500">Threshold: {threshold}</div>
            '''
            
            # Price info
            price_display = f'''
                <div class="text-sm font-medium text-gray-900">KSh {product.get_current_price():.2f}</div>
            '''
            
            # Action buttons with Alpine.js
            actions = f'''
                <div class="flex space-x-2">
                    <a href="/admin/inventory/product/{product.id}/edit" 
                       class="text-primary-600 hover:text-primary-900" 
                       title="Edit Product">
                        <i class="fas fa-edit"></i>
                    </a>
                    <button class="text-green-600 hover:text-green-900" 
                            onclick="window.inventoryActions.openStockModal({product.id})"
                            title="Update Stock">
                        <i class="fas fa-plus-circle"></i>
                    </button>
                    <button class="text-blue-600 hover:text-blue-900" 
                            onclick="window.inventoryActions.openDetailsModal({product.id})"
                            title="View Details">
                        <i class="fas fa-eye"></i>
                    </button>
                    <button class="text-red-600 hover:text-red-900" 
                            onclick="window.inventoryActions.openDeleteModal({product.id}, '{product.name.replace("'", "\\'")}')"
                            title="Delete Product">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            '''
            
            data.append([
                product_display,
                group_display, 
                stock_status,
                stock_display,
                price_display,
                product.updated_at.strftime('%m/%d/%Y'),
                actions
            ])
        
        return {
            "draw": draw,
            "recordsTotal": total_records,
            "recordsFiltered": filtered_records,
            "data": data
        }
    
    except Exception as e:
        logger.error(f"Error in products_datatable: {str(e)}")
        return {
            "draw": draw,
            "recordsTotal": 0,
            "recordsFiltered": 0,
            "data": [],
            "error": str(e)
        }