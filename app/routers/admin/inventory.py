"""
Admin Inventory Management Router
Following existing admin patterns and UI/UX best practices
"""
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi_csrf_protect.flexible import CsrfProtect
from app.templates_config import templates
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, func

from app.database import get_db
from app import models
from app.models_inventory_enhanced import (
    BusinessTemplate, InventoryLocation, ProductStock, 
    UnitOfMeasure, SupplierInfo, PricingTier
)
from app.routers.users import get_current_admin
from app.services.enhanced_inventory_service import get_enhanced_inventory_service
from app.services.business_templates import AFRICAN_SME_TEMPLATES

router = APIRouter(prefix="/admin/inventory")
logger = logging.getLogger(__name__)


@router.get("/dashboard", response_class=HTMLResponse)
async def inventory_dashboard(
    request: Request,
    admin=Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Main inventory dashboard following UI/UX best practices"""
    try:
        inventory_service = get_enhanced_inventory_service(db)
        
        # Get overall inventory statistics
        total_products = db.query(models.Product).filter(models.Product.is_active == True).count()
        total_locations = db.query(InventoryLocation).count()
        
        # Get low stock alerts
        low_stock_alerts = []
        products = db.query(models.Product).filter(
            models.Product.is_active == True,
            models.Product.track_inventory == True
        ).all()
        
        for product in products:
            total_stock = inventory_service.get_total_stock(product.id)
            if total_stock <= product.low_stock_threshold:
                low_stock_alerts.append({
                    "product": product,
                    "current_stock": total_stock,
                    "threshold": product.low_stock_threshold,
                    "status": "out_of_stock" if total_stock <= 0 else "low_stock"
                })
        
        # Get recent inventory activities
        recent_activities = db.query(models.InventoryLog).order_by(
            desc(models.InventoryLog.created_at)
        ).limit(10).all()
        
        # Get inventory health by business group
        groups_summary = []
        groups = db.query(models.Group).all()
        for group in groups:
            group_summary = inventory_service.get_business_inventory_summary_for_ai(group.id)
            groups_summary.append({
                "group": group,
                "summary": group_summary
            })
        
        context = {
            "request": request,
            "admin": admin,
            "total_products": total_products,
            "total_locations": total_locations,
            "low_stock_count": len(low_stock_alerts),
            "low_stock_alerts": low_stock_alerts[:5],  # Top 5 for dashboard
            "recent_activities": recent_activities,
            "groups_summary": groups_summary,
            "page_title": "Inventory Dashboard"
        }
        
        return templates.TemplateResponse("admin/inventory/dashboard.html", context)
        
    except Exception as e:
        logger.error(f"Error loading inventory dashboard: {str(e)}")
        raise HTTPException(status_code=500, detail="Error loading inventory dashboard")


@router.get("/products", response_class=HTMLResponse)
async def inventory_products(
    request: Request,
    group_id: Optional[int] = None,
    admin=Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Products inventory management with multi-UoM support"""
    try:
        # Get products with stock information
        query = db.query(models.Product).filter(models.Product.is_active == True)
        
        if group_id:
            query = query.filter(models.Product.group_id == group_id)
        
        products = query.all()
        
        # Enhance products with stock info
        inventory_service = get_enhanced_inventory_service(db)
        enhanced_products = []
        
        for product in products:
            total_stock = inventory_service.get_total_stock(product.id)
            availability = inventory_service.get_product_availability_for_ai(product.id)
            
            enhanced_products.append({
                "product": product,
                "total_stock": total_stock,
                "availability": availability,
                "is_low_stock": total_stock <= product.low_stock_threshold,
                "stock_status": "out_of_stock" if total_stock <= 0 else 
                              "low_stock" if total_stock <= product.low_stock_threshold else "in_stock"
            })
        
        # Get groups for filtering
        groups = db.query(models.Group).all()
        
        # Get available units for new products
        available_units = [unit.value for unit in UnitOfMeasure]
        
        context = {
            "request": request,
            "admin": admin,
            "enhanced_products": enhanced_products,
            "groups": groups,
            "selected_group_id": group_id,
            "available_units": available_units,
            "page_title": "Products Inventory"
        }
        
        return templates.TemplateResponse("admin/inventory/products.html", context)
        
    except Exception as e:
        logger.error(f"Error loading products inventory: {str(e)}")
        raise HTTPException(status_code=500, detail="Error loading products inventory")


@router.get("/products-enhanced", response_class=HTMLResponse)
async def enhanced_products_inventory(
    request: Request,
    group_id: Optional[int] = None,
    admin=Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Enhanced products inventory with modal system"""
    try:
        # Get products with stock information
        query = db.query(models.Product).filter(models.Product.is_active == True)
        
        if group_id:
            query = query.filter(models.Product.group_id == group_id)
        
        products = query.all()
        
        # Enhance products with stock info
        inventory_service = get_enhanced_inventory_service(db)
        enhanced_products = []
        
        for product in products:
            total_stock = inventory_service.get_total_stock(product.id)
            availability = inventory_service.get_product_availability_for_ai(product.id)
            
            enhanced_products.append({
                "product": product,
                "total_stock": total_stock,
                "availability": availability,
                "is_low_stock": total_stock <= product.low_stock_threshold,
                "stock_status": "out_of_stock" if total_stock <= 0 else 
                              "low_stock" if total_stock <= product.low_stock_threshold else "in_stock"
            })
        
        # Get groups for filtering
        groups = db.query(models.Group).all()
        
        context = {
            "request": request,
            "admin": admin,
            "enhanced_products": enhanced_products,
            "groups": groups,
            "selected_group_id": group_id,
            "page_title": "Enhanced Products Inventory"
        }
        
        return templates.TemplateResponse("admin/inventory/products_enhanced.html", context)
        
    except Exception as e:
        logger.error(f"Error loading enhanced products inventory: {str(e)}")
        raise HTTPException(status_code=500, detail="Error loading enhanced products inventory")


@router.get("/locations", response_class=HTMLResponse)
async def inventory_locations(
    request: Request,
    admin=Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Inventory locations management"""
    try:
        locations = db.query(InventoryLocation).filter(
            InventoryLocation.is_active == True
        ).all()
        
        # Enhance locations with stock summary
        enhanced_locations = []
        for location in locations:
            stock_records = db.query(ProductStock).filter(
                ProductStock.location_id == location.id
            ).all()
            
            total_products = len(stock_records)
            total_value = sum(
                (record.current_stock * (record.average_cost or 0)) 
                for record in stock_records
            )
            
            enhanced_locations.append({
                "location": location,
                "total_products": total_products,
                "total_value": total_value,
                "stock_records": stock_records
            })
        
        groups = db.query(models.Group).all()
        
        context = {
            "request": request,
            "admin": admin,
            "enhanced_locations": enhanced_locations,
            "groups": groups,
            "page_title": "Inventory Locations"
        }
        
        return templates.TemplateResponse("admin/inventory/locations.html", context)
        
    except Exception as e:
        logger.error(f"Error loading inventory locations: {str(e)}")
        raise HTTPException(status_code=500, detail="Error loading inventory locations")


@router.get("/suppliers", response_class=HTMLResponse)
async def inventory_suppliers(
    request: Request,
    admin=Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Supplier management for African SMEs"""
    try:
        suppliers = db.query(SupplierInfo).filter(
            SupplierInfo.is_active == True
        ).all()
        
        groups = db.query(models.Group).all()
        
        context = {
            "request": request,
            "admin": admin,
            "suppliers": suppliers,
            "groups": groups,
            "page_title": "Suppliers Management"
        }
        
        return templates.TemplateResponse("admin/inventory/suppliers.html", context)
        
    except Exception as e:
        logger.error(f"Error loading suppliers: {str(e)}")
        raise HTTPException(status_code=500, detail="Error loading suppliers")


@router.get("/business-setup", response_class=HTMLResponse)
async def business_setup(
    request: Request,
    admin=Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Business template setup for new SMEs"""
    try:
        # Get available business templates
        templates_data = AFRICAN_SME_TEMPLATES
        
        # Get existing business configurations
        existing_businesses = db.query(models.Group).all()
        
        context = {
            "request": request,
            "admin": admin,
            "business_templates": templates_data,
            "existing_businesses": existing_businesses,
            "page_title": "Business Setup"
        }
        
        return templates.TemplateResponse("admin/inventory/business_setup.html", context)
        
    except Exception as e:
        logger.error(f"Error loading business setup: {str(e)}")
        raise HTTPException(status_code=500, detail="Error loading business setup")


@router.post("/setup-business")
async def setup_new_business(
    group_id: int = Form(...),
    business_type: str = Form(...),
    admin=Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Set up inventory for new business using templates"""
    try:
        from app.services.inventory_migration import setup_business_inventory
        
        success = setup_business_inventory(db, group_id, business_type)
        
        if success:
            logger.info(f"Successfully set up {business_type} business for group {group_id}")
            return {"success": True, "message": f"Business setup completed for {business_type}"}
        else:
            raise HTTPException(status_code=400, detail="Failed to set up business")
            
    except Exception as e:
        logger.error(f"Error setting up business: {str(e)}")
        raise HTTPException(status_code=500, detail="Error setting up business")


@router.get("/reorder-suggestions", response_class=HTMLResponse)
async def reorder_suggestions(
    request: Request,
    group_id: Optional[int] = None,
    admin=Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """AI-powered reorder suggestions"""
    try:
        inventory_service = get_enhanced_inventory_service(db)
        
        if group_id:
            suggestions = inventory_service.get_reorder_suggestions(group_id)
            group = db.query(models.Group).filter(models.Group.id == group_id).first()
        else:
            # Get suggestions for all groups
            suggestions = []
            groups = db.query(models.Group).all()
            for group in groups:
                group_suggestions = inventory_service.get_reorder_suggestions(group.id)
                for suggestion in group_suggestions:
                    suggestion["group"] = group
                suggestions.extend(group_suggestions)
            group = None
        
        groups = db.query(models.Group).all()
        
        context = {
            "request": request,
            "admin": admin,
            "suggestions": suggestions,
            "groups": groups,
            "selected_group": group,
            "page_title": "Reorder Suggestions"
        }
        
        return templates.TemplateResponse("admin/inventory/reorder_suggestions.html", context)
        
    except Exception as e:
        logger.error(f"Error loading reorder suggestions: {str(e)}")
        raise HTTPException(status_code=500, detail="Error loading reorder suggestions")


@router.get("/product/{product_id}", response_class=HTMLResponse)
async def view_product(
    product_id: int,
    request: Request,
    admin=Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """View individual product details"""
    try:
        product = db.query(models.Product).filter(
            models.Product.id == product_id,
            models.Product.is_active == True
        ).first()
        
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        
        inventory_service = get_enhanced_inventory_service(db)
        
        # Get stock information
        total_stock = inventory_service.get_total_stock(product_id)
        availability = inventory_service.get_product_availability_for_ai(product_id)
        
        # Get stock records by location
        stock_records = db.query(ProductStock).filter(
            ProductStock.product_id == product_id
        ).join(InventoryLocation).all()
        
        context = {
            "request": request,
            "admin": admin,
            "product": product,
            "total_stock": total_stock,
            "availability": availability,
            "stock_records": stock_records,
            "page_title": f"Product: {product.name}"
        }
        
        return templates.TemplateResponse("admin/inventory/product_detail.html", context)
        
    except Exception as e:
        logger.error(f"Error viewing product {product_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error loading product")


@router.get("/products/add", response_class=HTMLResponse)
async def add_product_form(
    request: Request,
    admin=Depends(get_current_admin),
    csrf_protect: CsrfProtect = Depends(),
    db: Session = Depends(get_db)
):
    """Add new product form"""
    try:
        # Get available units and categories
        available_units = [unit.value for unit in UnitOfMeasure]
        available_categories = [cat.value for cat in models.ProductCategory]
        
        # Get groups for dropdown
        groups = db.query(models.Group).all()
        
        # Generate CSRF tokens
        csrf_token, signed_token = csrf_protect.generate_csrf_tokens()
        
        context = {
            "request": request,
            "admin": admin,
            "available_units": available_units,
            "available_categories": available_categories,
            "groups": groups,
            "page_title": "Add New Product",
            "csrf_token": csrf_token
        }
        
        response = templates.TemplateResponse("admin/inventory/product_add.html", context)
        csrf_protect.set_csrf_cookie(signed_token, response)
        return response
        
    except Exception as e:
        logger.error(f"Error loading add product form: {str(e)}")
        raise HTTPException(status_code=500, detail="Error loading add product form")


@router.post("/products/add")
async def create_product(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    base_price: float = Form(...),
    cost_price: Optional[float] = Form(None),
    low_stock_threshold: int = Form(5),
    category: Optional[str] = Form(None),
    group_id: int = Form(...),
    admin=Depends(get_current_admin),
    csrf_protect: CsrfProtect = Depends(),
    db: Session = Depends(get_db)
):
    """Create new product"""
    try:
        # Validate CSRF token
        await csrf_protect.validate_csrf(request)
        # Generate SKU
        import uuid
        sku = f"PRD-{str(uuid.uuid4())[:8].upper()}"
        
        # Create new product
        new_product = models.Product(
            name=name,
            description=description,
            sku=sku,
            base_price=base_price,
            cost_price=cost_price,
            low_stock_threshold=low_stock_threshold,
            group_id=group_id,
            is_active=True,
            track_inventory=True
        )
        
        if category:
            try:
                new_product.category = models.ProductCategory(category)
            except ValueError:
                logger.warning(f"Invalid category '{category}' for new product")
        
        db.add(new_product)
        db.commit()
        db.refresh(new_product)
        
        logger.info(f"New product created: {new_product.id} by admin {admin.id}")
        return {"success": True, "message": "Product created successfully", "product_id": new_product.id}
        
    except Exception as e:
        logger.error(f"Error creating product: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Error creating product")


@router.get("/product/{product_id}/edit", response_class=HTMLResponse)
async def edit_product(
    product_id: int,
    request: Request,
    admin=Depends(get_current_admin),
    csrf_protect: CsrfProtect = Depends(),
    db: Session = Depends(get_db)
):
    """Edit product form"""
    try:
        product = db.query(models.Product).filter(
            models.Product.id == product_id,
            models.Product.is_active == True
        ).first()
        
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        
        # Get available units and categories
        available_units = [unit.value for unit in UnitOfMeasure]
        available_categories = [cat.value for cat in models.ProductCategory]
        
        # Get groups for dropdown
        groups = db.query(models.Group).all()
        
        # Generate CSRF tokens
        csrf_token, signed_token = csrf_protect.generate_csrf_tokens()
        
        context = {
            "request": request,
            "admin": admin,
            "product": product,
            "available_units": available_units,
            "available_categories": available_categories,
            "groups": groups,
            "page_title": f"Edit Product: {product.name}",
            "csrf_token": csrf_token
        }
        
        response = templates.TemplateResponse("admin/inventory/product_edit.html", context)
        csrf_protect.set_csrf_cookie(signed_token, response)
        return response
        
    except Exception as e:
        logger.error(f"Error loading product edit form {product_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error loading product edit form")


@router.post("/product/{product_id}/edit")
async def update_product(
    product_id: int,
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    base_price: float = Form(...),
    cost_price: Optional[float] = Form(None),
    low_stock_threshold: int = Form(5),
    category: Optional[str] = Form(None),
    admin=Depends(get_current_admin),
    csrf_protect: CsrfProtect = Depends(),
    db: Session = Depends(get_db)
):
    """Update product"""
    try:
        # Validate CSRF token
        await csrf_protect.validate_csrf(request)
        product = db.query(models.Product).filter(
            models.Product.id == product_id,
            models.Product.is_active == True
        ).first()
        
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        
        # Update product fields
        product.name = name
        product.description = description
        product.base_price = base_price
        product.cost_price = cost_price
        product.low_stock_threshold = low_stock_threshold
        
        if category:
            try:
                product.category = models.ProductCategory(category)
            except ValueError:
                logger.warning(f"Invalid category '{category}' for product {product_id}")
        
        db.commit()
        
        return {"success": True, "message": "Product updated successfully"}
        
    except Exception as e:
        logger.error(f"Error updating product {product_id}: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Error updating product")


@router.post("/update-stock")
async def update_product_stock(
    product_id: int = Form(...),
    change_type: str = Form(...),
    quantity: float = Form(...),
    reason: str = Form(""),
    location_id: Optional[int] = Form(None),
    admin=Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Update product stock - supports both basic and enhanced inventory"""
    try:
        # Get the product
        product = db.query(models.Product).filter(models.Product.id == product_id).first()
        if not product:
            return {"success": False, "message": "Product not found"}
        
        # Calculate new stock quantity
        current_stock = product.stock_quantity or 0
        
        if change_type == "stock_in":
            new_stock = current_stock + quantity
        elif change_type == "stock_out":
            new_stock = max(0, current_stock - quantity)  # Don't allow negative stock
        elif change_type == "adjustment":
            new_stock = quantity  # Set to absolute quantity
        else:
            return {"success": False, "message": "Invalid change type"}
        
        # Update the product stock
        product.stock_quantity = int(new_stock)
        
        # Create inventory log entry
        quantity_change_val = quantity if change_type == "stock_in" else -quantity if change_type == "stock_out" else (new_stock - current_stock)
        
        inventory_log = models.InventoryLog(
            product_id=product_id,
            change_type=change_type,
            quantity_before=int(current_stock),
            quantity_change=int(quantity_change_val),
            quantity_after=int(new_stock),
            reason=reason or f"Manual {change_type}",
            user_id=admin.id
        )
        
        db.add(inventory_log)
        db.commit()
        db.refresh(product)
        
        logger.info(f"Stock updated for product {product_id}: {change_type} {quantity} by admin {admin.id}")
        return {"success": True, "message": f"Stock updated successfully. New quantity: {new_stock}"}
            
    except Exception as e:
        logger.error(f"Error updating stock: {str(e)}")
        db.rollback()
        return {"success": False, "message": f"Error updating stock: {str(e)}"}


@router.get("/product/{product_id}/stock-history", response_class=HTMLResponse)
async def get_product_stock_history(
    product_id: int,
    request: Request,
    admin=Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Get stock history for a product"""
    try:
        product = db.query(models.Product).filter(models.Product.id == product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        
        # Get stock movements from inventory logs
        stock_history = db.query(models.InventoryLog).filter(
            models.InventoryLog.product_id == product_id
        ).order_by(desc(models.InventoryLog.created_at)).limit(50).all()
        
        # Create HTML response for the modal
        history_html = f"""
        <div class="space-y-4">
            <div class="bg-blue-50 p-4 rounded-lg">
                <h4 class="font-medium text-blue-900 mb-2">Stock History for {product.name}</h4>
                <p class="text-sm text-blue-700">Last 50 stock movements</p>
            </div>
            
            <div class="max-h-96 overflow-y-auto">
                <div class="space-y-2">
        """
        
        for log in stock_history:
            movement_color = "green" if log.quantity_change > 0 else "red" if log.quantity_change < 0 else "gray"
            movement_icon = "plus" if log.quantity_change > 0 else "minus" if log.quantity_change < 0 else "equals"
            
            history_html += f"""
                <div class="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                    <div class="flex items-center space-x-3">
                        <div class="w-8 h-8 bg-{movement_color}-100 text-{movement_color}-600 rounded-full flex items-center justify-center">
                            <i class="fas fa-{movement_icon} text-xs"></i>
                        </div>
                        <div>
                            <div class="text-sm font-medium text-gray-900">
                                {log.change_type.replace('_', ' ').title()}
                            </div>
                            <div class="text-xs text-gray-500">
                                {log.reason or 'No reason provided'}
                            </div>
                        </div>
                    </div>
                    <div class="text-right">
                        <div class="text-sm font-medium text-{movement_color}-600">
                            {'+' if log.quantity_change > 0 else ''}{log.quantity_change}
                        </div>
                        <div class="text-xs text-gray-500">
                            {log.created_at.strftime('%m/%d/%Y %I:%M %p')}
                        </div>
                    </div>
                </div>
            """
        
        if not stock_history:
            history_html += """
                <div class="text-center py-8 text-gray-500">
                    <i class="fas fa-history text-3xl mb-2"></i>
                    <p>No stock movements recorded yet</p>
                </div>
            """
        
        history_html += """
                </div>
            </div>
        </div>
        """
        
        return HTMLResponse(content=history_html)
        
    except Exception as e:
        logger.error(f"Error loading stock history for product {product_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error loading stock history")


@router.get("/product/{product_id}/details")
async def get_product_details_api(
    product_id: int,
    admin=Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Get detailed product information for API/modal display"""
    try:
        product = db.query(models.Product).filter(models.Product.id == product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        
        inventory_service = get_enhanced_inventory_service(db)
        
        # Get comprehensive product details
        total_stock = inventory_service.get_total_stock(product_id)
        availability = inventory_service.get_product_availability_for_ai(product_id)
        
        # Get stock by location
        locations = db.query(InventoryLocation).filter(
            InventoryLocation.group_id == product.group_id,
            InventoryLocation.is_active == True
        ).all()
        
        location_stock = []
        for location in locations:
            stock = inventory_service.get_stock_at_location(product_id, location.id)
            if stock > 0:  # Only include locations with stock
                location_stock.append({
                    "location": location.name,
                    "stock": stock,
                    "location_type": location.location_type
                })
        
        return {
            "success": True,
            "product": {
                "id": product.id,
                "name": product.name,
                "sku": product.sku,
                "description": product.description,
                "category": product.category.value if product.category else None,
                "base_price": float(product.base_price),
                "sale_price": float(product.sale_price) if product.sale_price else None,
                "cost_price": float(product.cost_price) if product.cost_price else None,
                "low_stock_threshold": product.low_stock_threshold,
                "total_stock": total_stock,
                "location_stock": location_stock,
                "availability": availability,
                "created_at": product.created_at.isoformat(),
                "updated_at": product.updated_at.isoformat()
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting product details {product_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error getting product details")


@router.get("/product/{product_id}/details/modal", response_class=HTMLResponse)
async def get_product_details_modal(
    product_id: int,
    request: Request,
    admin=Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Get product details as HTML for modal display"""
    try:
        product = db.query(models.Product).filter(models.Product.id == product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        
        inventory_service = get_enhanced_inventory_service(db)
        
        # Get comprehensive product details
        total_stock = inventory_service.get_total_stock(product_id)
        availability = inventory_service.get_product_availability_for_ai(product_id)
        
        # Get stock by location
        locations = db.query(InventoryLocation).filter(
            InventoryLocation.group_id == product.group_id,
            InventoryLocation.is_active == True
        ).all()
        
        location_stock = []
        for location in locations:
            stock = inventory_service.get_stock_at_location(product_id, location.id)
            if stock > 0:  # Only include locations with stock
                location_stock.append({
                    "location": location.name,
                    "stock": stock,
                    "location_type": location.location_type
                })
        
        # Create HTML content for modal
        profit_margin = 0
        if product.cost_price and product.base_price and product.cost_price > 0:
            profit = product.base_price - product.cost_price
            profit_margin = (profit / product.base_price) * 100
        
        html_content = f"""
        <div class="space-y-6">
            <!-- Product Header -->
            <div class="bg-blue-50 p-4 rounded-lg">
                <div class="flex items-center justify-between mb-3">
                    <h4 class="font-semibold text-blue-900">{product.name}</h4>
                    <span class="text-sm font-mono text-blue-700">SKU: {product.sku or 'N/A'}</span>
                </div>
                <div class="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                    <div>
                        <span class="text-blue-700 font-medium">Category:</span>
                        <div class="text-blue-900">{product.category.value if product.category else 'Uncategorized'}</div>
                    </div>
                    <div>
                        <span class="text-blue-700 font-medium">Total Stock:</span>
                        <div class="text-blue-900 font-semibold">{total_stock} units</div>
                    </div>
                    <div>
                        <span class="text-blue-700 font-medium">Base Price:</span>
                        <div class="text-blue-900 font-semibold">KSh {product.base_price:.2f}</div>
                    </div>
                    <div>
                        <span class="text-blue-700 font-medium">Status:</span>
                        <div class="text-blue-900">{'Active' if product.is_active else 'Inactive'}</div>
                    </div>
                </div>
            </div>
            
            <!-- Description -->
            {f'<div class="bg-gray-50 p-4 rounded-lg"><h5 class="font-medium text-gray-900 mb-2">Description</h5><p class="text-gray-700">{product.description}</p></div>' if product.description else ''}
            
            <!-- Pricing Information -->
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div class="bg-green-50 p-4 rounded-lg">
                    <h5 class="font-medium text-green-900 mb-3">Pricing Details</h5>
                    <div class="space-y-2 text-sm">
                        <div class="flex justify-between">
                            <span class="text-green-700">Base Price:</span>
                            <span class="text-green-900 font-semibold">KSh {product.base_price:.2f}</span>
                        </div>
                        {f'<div class="flex justify-between"><span class="text-green-700">Sale Price:</span><span class="text-green-900 font-semibold">KSh {product.sale_price:.2f}</span></div>' if product.sale_price else ''}
                        {f'<div class="flex justify-between"><span class="text-green-700">Cost Price:</span><span class="text-green-900">KSh {product.cost_price:.2f}</span></div>' if product.cost_price else ''}
                        {f'<div class="flex justify-between"><span class="text-green-700">Profit Margin:</span><span class="text-green-900 font-semibold">{profit_margin:.1f}%</span></div>' if profit_margin > 0 else ''}
                    </div>
                </div>
                
                <div class="bg-gray-50 p-4 rounded-lg">
                    <h5 class="font-medium text-gray-900 mb-3">Inventory Settings</h5>
                    <div class="space-y-2 text-sm">
                        <div class="flex justify-between">
                            <span class="text-gray-600">Low Stock Alert:</span>
                            <span class="text-gray-900">{product.low_stock_threshold} units</span>
                        </div>
                        <div class="flex justify-between">
                            <span class="text-gray-600">Track Inventory:</span>
                            <span class="text-gray-900">{'Yes' if product.track_inventory else 'No'}</span>
                        </div>
                        <div class="flex justify-between">
                            <span class="text-gray-600">Group:</span>
                            <span class="text-gray-900">{product.group.name if product.group else 'N/A'}</span>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- Stock by Location -->
            {f'''
            <div>
                <h5 class="font-medium text-gray-900 mb-3">Stock by Location</h5>
                <div class="space-y-2">
                    {''.join([f'<div class="flex justify-between py-2 px-3 bg-white border border-gray-200 rounded"><span class="text-gray-700">{loc["location"]} ({loc["location_type"]})</span><span class="font-medium text-gray-900">{loc["stock"]} units</span></div>' for loc in location_stock])}
                </div>
            </div>
            ''' if location_stock else '<div class="text-center py-4 text-gray-500"><i class="fas fa-box-open text-2xl mb-2"></i><p>No stock available at any location</p></div>'}
            
            <!-- Timestamps -->
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs text-gray-500">
                <div>Created: {product.created_at.strftime('%m/%d/%Y %I:%M %p')}</div>
                <div>Updated: {product.updated_at.strftime('%m/%d/%Y %I:%M %p')}</div>
            </div>
        </div>
        """
        
        return HTMLResponse(content=html_content)
        
    except Exception as e:
        logger.error(f"Error loading product details modal {product_id}: {str(e)}")
        return HTMLResponse(content=f'<div class="text-center py-4 text-red-500"><i class="fas fa-exclamation-triangle text-2xl mb-2"></i><p>Error loading product details</p></div>', status_code=500)


@router.delete("/product/{product_id}")
async def delete_product(
    product_id: int,
    admin=Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Delete a product (soft delete)"""
    try:
        product = db.query(models.Product).filter(models.Product.id == product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        
        # Soft delete by setting is_active to False
        product.is_active = False
        db.commit()
        
        logger.info(f"Product {product_id} deleted by admin {admin.id}")
        return {"success": True, "message": "Product deleted successfully"}
        
    except Exception as e:
        logger.error(f"Error deleting product {product_id}: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Error deleting product")


# Legacy compatibility routes - redirect old admin/products paths to new inventory structure
legacy_router = APIRouter(prefix="/admin")

@legacy_router.get("/products")
async def legacy_products_redirect():
    """Legacy route redirect to new inventory structure"""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/admin/inventory/products", status_code=301)

@legacy_router.get("/products/{product_id}")
async def legacy_product_view_redirect(product_id: int):
    """Legacy route redirect to new inventory structure"""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"/admin/inventory/product/{product_id}", status_code=301)

@legacy_router.get("/products/{product_id}/edit")
async def legacy_product_edit_redirect(product_id: int):
    """Legacy route redirect to new inventory structure"""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"/admin/inventory/product/{product_id}/edit", status_code=301)