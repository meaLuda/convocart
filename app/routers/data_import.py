"""
Data Import/Export API Routes
Handles CSV/Excel upload and template download functionality
"""
import logging
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import pandas as pd
from io import BytesIO

from app.database import get_db
from app.models import BusinessType, User, Group
from app.services.data_import_service import get_data_import_service
from app.services.business_config_service import get_business_config_service

router = APIRouter(prefix="/api/data", tags=["data-import"])
logger = logging.getLogger(__name__)

# HTMX-specific endpoints
from fastapi.responses import HTMLResponse
from fastapi import Request
from app.templates_config import templates

@router.get("/template/{business_type}")
async def download_template(
    business_type: str,
    group_id: int = Query(..., description="Group ID"),
    format: str = Query("csv", description="Format: csv or xlsx"),
    sample_data: bool = Query(True, description="Include sample data"),
    db: Session = Depends(get_db)
):
    """
    Download CSV/Excel template for product import
    """
    try:
        # Validate business type
        try:
            btype = BusinessType(business_type)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid business type")
        
        # Validate group exists
        group = db.query(Group).filter(Group.id == group_id).first()
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")
        
        import_service = get_data_import_service(db)
        
        if sample_data:
            # Generate sample template
            template_data = import_service.generate_sample_csv(btype)
            filename = f"{business_type}_template_sample.csv"
        else:
            # Export existing products as template
            template_data = import_service.export_products_template(group_id, btype)
            filename = f"{group.name}_products_export.csv"
        
        if format.lower() == "xlsx":
            # Convert CSV to Excel
            df = pd.read_csv(BytesIO(template_data))
            excel_buffer = BytesIO()
            df.to_excel(excel_buffer, index=False)
            excel_buffer.seek(0)
            template_data = excel_buffer.getvalue()
            filename = filename.replace('.csv', '.xlsx')
            media_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        else:
            media_type = 'text/csv'
        
        return Response(
            content=template_data,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except Exception as e:
        logger.error(f"Error downloading template: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/template-info/{business_type}")
async def get_template_info(
    business_type: str,
    db: Session = Depends(get_db)
):
    """
    Get template information for UI display
    """
    try:
        # Validate business type
        try:
            btype = BusinessType(business_type)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid business type")
        
        import_service = get_data_import_service(db)
        template_info = import_service.get_template_info(btype)
        
        return {
            "success": True,
            "data": template_info
        }
        
    except Exception as e:
        logger.error(f"Error getting template info: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/validate")
async def validate_upload(
    group_id: int = Query(..., description="Group ID"),
    business_type: str = Query(..., description="Business type"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Validate uploaded CSV/Excel file without importing
    """
    try:
        # Validate business type
        try:
            btype = BusinessType(business_type)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid business type")
        
        # Validate group exists
        group = db.query(Group).filter(Group.id == group_id).first()
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")
        
        # Check file type
        if not file.filename.lower().endswith(('.csv', '.xlsx', '.xls')):
            raise HTTPException(
                status_code=400, 
                detail="Invalid file type. Please upload CSV or Excel file."
            )
        
        # Read file
        content = await file.read()
        
        if file.filename.lower().endswith('.csv'):
            df = pd.read_csv(BytesIO(content))
        else:
            df = pd.read_excel(BytesIO(content))
        
        # Validate data
        import_service = get_data_import_service(db)
        validation_result = import_service.validate_upload_data(df, btype, group_id)
        
        return {
            "success": True,
            "validation": validation_result,
            "filename": file.filename,
            "file_size": len(content),
            "rows_analyzed": len(df)
        }
        
    except Exception as e:
        logger.error(f"Error validating upload: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/import")
async def import_data(
    group_id: int = Query(..., description="Group ID"),
    business_type: str = Query(..., description="Business type"),
    update_existing: bool = Query(True, description="Update existing products"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    # current_user: User = Depends(get_current_user)  # Implement auth
):
    """
    Import products from CSV/Excel file
    """
    try:
        # Validate business type
        try:
            btype = BusinessType(business_type)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid business type")
        
        # Validate group exists
        group = db.query(Group).filter(Group.id == group_id).first()
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")
        
        # Check file type
        if not file.filename.lower().endswith(('.csv', '.xlsx', '.xls')):
            raise HTTPException(
                status_code=400, 
                detail="Invalid file type. Please upload CSV or Excel file."
            )
        
        # Read file
        content = await file.read()
        
        if file.filename.lower().endswith('.csv'):
            df = pd.read_csv(BytesIO(content))
        else:
            df = pd.read_excel(BytesIO(content))
        
        import_service = get_data_import_service(db)
        
        # First validate the data
        validation_result = import_service.validate_upload_data(df, btype, group_id)
        
        if not validation_result["valid"]:
            return {
                "success": False,
                "error": "Data validation failed",
                "validation": validation_result
            }
        
        # Import the data (using user_id = 1 as placeholder - implement proper auth)
        user_id = 1  # Replace with current_user.id
        import_result = import_service.import_products(
            df, btype, group_id, user_id, update_existing
        )
        
        return {
            "success": import_result["success"],
            "import_result": import_result,
            "filename": file.filename,
            "imported_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error importing data: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/business-types")
async def get_business_types():
    """
    Get all available business types for templates
    """
    try:
        business_types = []
        
        for btype in BusinessType:
            config_service = get_business_config_service(None)  # No DB needed for templates
            template = config_service.get_business_template(btype)
            
            business_types.append({
                "value": btype.value,
                "display_name": template["display_name"],
                "features": template["features"],
                "recommended_categories": template["recommended_categories"],
                "sample_products": len(template["sample_products"])
            })
        
        return {
            "success": True,
            "business_types": business_types
        }
        
    except Exception as e:
        logger.error(f"Error getting business types: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/bulk-update-inventory")
async def bulk_update_inventory(
    group_id: int = Query(..., description="Group ID"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Bulk update inventory levels from CSV
    Expected columns: product_name, stock_quantity
    """
    try:
        # Validate group exists
        group = db.query(Group).filter(Group.id == group_id).first()
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")
        
        # Check file type
        if not file.filename.lower().endswith(('.csv', '.xlsx', '.xls')):
            raise HTTPException(
                status_code=400, 
                detail="Invalid file type. Please upload CSV or Excel file."
            )
        
        # Read file
        content = await file.read()
        
        if file.filename.lower().endswith('.csv'):
            df = pd.read_csv(BytesIO(content))
        else:
            df = pd.read_excel(BytesIO(content))
        
        # Validate required columns
        required_columns = ['product_name', 'stock_quantity']
        missing_columns = set(required_columns) - set(df.columns)
        
        if missing_columns:
            raise HTTPException(
                status_code=400,
                detail=f"Missing required columns: {', '.join(missing_columns)}"
            )
        
        from app.services.inventory_service import get_inventory_service
        inventory_service = get_inventory_service(db)
        
        update_results = {
            "total_processed": 0,
            "updated": 0,
            "not_found": 0,
            "errors": []
        }
        
        for index, row in df.iterrows():
            try:
                product_name = str(row['product_name']).strip()
                stock_quantity = int(row['stock_quantity'])
                
                # Find product
                from app.models import Product
                from sqlalchemy import func
                
                product = db.query(Product).filter(
                    Product.group_id == group_id,
                    func.lower(Product.name) == product_name.lower()
                ).first()
                
                if product:
                    # Update stock
                    quantity_change = stock_quantity - product.stock_quantity
                    
                    success = inventory_service.update_stock(
                        product_id=product.id,
                        quantity_change=quantity_change,
                        change_type='adjustment',
                        reason='Bulk inventory update',
                        user_id=1  # Replace with current_user.id
                    )
                    
                    if success:
                        update_results["updated"] += 1
                    else:
                        update_results["errors"].append(f"Failed to update {product_name}")
                else:
                    update_results["not_found"] += 1
                    update_results["errors"].append(f"Product not found: {product_name}")
                
                update_results["total_processed"] += 1
                
            except Exception as e:
                update_results["errors"].append(f"Row {index + 1}: {str(e)}")
        
        return {
            "success": True,
            "results": update_results
        }
        
    except Exception as e:
        logger.error(f"Error bulk updating inventory: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/export-inventory/{group_id}")
async def export_inventory(
    group_id: int,
    format: str = Query("csv", description="Format: csv or xlsx"),
    db: Session = Depends(get_db)
):
    """
    Export current inventory levels as CSV/Excel
    """
    try:
        # Validate group exists
        group = db.query(Group).filter(Group.id == group_id).first()
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")
        
        from app.models import Product
        
        # Get all products with current inventory
        products = db.query(Product).filter(
            Product.group_id == group_id,
            Product.is_active == True
        ).all()
        
        if not products:
            raise HTTPException(status_code=404, detail="No products found")
        
        # Prepare data
        inventory_data = []
        for product in products:
            inventory_data.append({
                "product_id": product.id,
                "product_name": product.name,
                "sku": product.sku or "",
                "category": product.category.value if product.category else "",
                "current_stock": product.stock_quantity,
                "low_stock_threshold": product.low_stock_threshold,
                "is_low_stock": product.is_low_stock(),
                "base_price": product.base_price,
                "updated_at": product.updated_at.isoformat() if product.updated_at else ""
            })
        
        df = pd.DataFrame(inventory_data)
        
        if format.lower() == "xlsx":
            # Export as Excel
            excel_buffer = BytesIO()
            df.to_excel(excel_buffer, index=False)
            excel_buffer.seek(0)
            content = excel_buffer.getvalue()
            filename = f"{group.name}_inventory_{datetime.now().strftime('%Y%m%d')}.xlsx"
            media_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        else:
            # Export as CSV
            csv_buffer = BytesIO()
            df.to_csv(csv_buffer, index=False, encoding='utf-8')
            csv_buffer.seek(0)
            content = csv_buffer.getvalue()
            filename = f"{group.name}_inventory_{datetime.now().strftime('%Y%m%d')}.csv"
            media_type = 'text/csv'
        
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except Exception as e:
        logger.error(f"Error exporting inventory: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# HTMX Endpoints
@router.get("/htmx/business-list", response_class=HTMLResponse)
async def htmx_business_list(request: Request, db: Session = Depends(get_db)):
    """
    HTMX endpoint to load business list
    """
    try:
        groups = db.query(Group).filter(Group.is_active == True).all()
        
        return templates.TemplateResponse(
            "partials/business_list.html",
            {"request": request, "groups": groups}
        )
        
    except Exception as e:
        logger.error(f"Error loading business list: {str(e)}")
        return '<div class="text-red-500">Error loading businesses</div>'

@router.get("/htmx/select-business/{business_id}", response_class=HTMLResponse)
async def htmx_select_business(request: Request, business_id: int, db: Session = Depends(get_db)):
    """
    HTMX endpoint when business is selected
    """
    try:
        business = db.query(Group).filter(Group.id == business_id).first()
        if not business:
            return '<div class="text-red-500">Business not found</div>'
        
        return templates.TemplateResponse(
            "partials/upload_form.html",
            {"request": request, "business": business}
        )
        
    except Exception as e:
        logger.error(f"Error selecting business: {str(e)}")
        return '<div class="text-red-500">Error selecting business</div>'

@router.post("/htmx/upload-file", response_class=HTMLResponse)
async def htmx_upload_file(
    request: Request,
    group_id: int = Query(...),
    business_type: str = Query(...),
    file: UploadFile = File(...),
    update_existing: bool = False,
    validate_only: bool = False,
    db: Session = Depends(get_db)
):
    """
    HTMX endpoint for file upload with real-time progress
    """
    try:
        # Validate business type
        try:
            btype = BusinessType(business_type)
        except ValueError:
            return templates.TemplateResponse(
                "partials/upload_results.html",
                {"request": request, "result": {"success": False, "error": "Invalid business type"}}
            )
        
        # Validate group exists
        group = db.query(Group).filter(Group.id == group_id).first()
        if not group:
            return templates.TemplateResponse(
                "partials/upload_results.html",
                {"request": request, "result": {"success": False, "error": "Business not found"}}
            )
        
        # Check file type
        if not file.filename.lower().endswith(('.csv', '.xlsx', '.xls')):
            return templates.TemplateResponse(
                "partials/upload_results.html",
                {"request": request, "result": {"success": False, "error": "Invalid file type. Please upload CSV or Excel file."}}
            )
        
        # Read file
        content = await file.read()
        
        if file.filename.lower().endswith('.csv'):
            df = pd.read_csv(BytesIO(content))
        else:
            df = pd.read_excel(BytesIO(content))
        
        import_service = get_data_import_service(db)
        
        context = {
            "request": request,
            "rows_analyzed": len(df),
            "filename": file.filename,
            "is_validation": validate_only
        }
        
        if validate_only:
            # Validation only
            validation_result = import_service.validate_upload_data(df, btype, group_id)
            context["result"] = {
                "success": True,
                "validation": validation_result
            }
        else:
            # Import data
            validation_result = import_service.validate_upload_data(df, btype, group_id)
            
            if not validation_result["valid"]:
                context["result"] = {
                    "success": False,
                    "validation": validation_result,
                    "error": "Data validation failed"
                }
            else:
                # Proceed with import
                user_id = 1  # Replace with current_user.id
                import_result = import_service.import_products(
                    df, btype, group_id, user_id, update_existing
                )
                
                context["result"] = {
                    "success": True,
                    "import_result": import_result
                }
        
        return templates.TemplateResponse("partials/upload_results.html", context)
        
    except Exception as e:
        logger.error(f"Error in HTMX upload: {str(e)}")
        return templates.TemplateResponse(
            "partials/upload_results.html",
            {"request": request, "result": {"success": False, "error": str(e)}}
        )

@router.get("/htmx/clear-upload", response_class=HTMLResponse)
async def htmx_clear_upload(request: Request):
    """
    HTMX endpoint to clear upload form
    """
    return templates.TemplateResponse(
        "partials/upload_section_empty.html",
        {"request": request}
    )

@router.get("/htmx/template-grid", response_class=HTMLResponse)
async def htmx_template_grid(request: Request):
    """
    HTMX endpoint to load business type templates
    """
    try:
        business_types = []
        
        for btype in BusinessType:
            config_service = get_business_config_service(None)
            template = config_service.get_business_template(btype)
            
            business_types.append({
                "value": btype.value,
                "display_name": template["display_name"],
                "features": template["features"],
                "sample_products": len(template["sample_products"])
            })
        
        return templates.TemplateResponse(
            "partials/template_grid.html",
            {"request": request, "business_types": business_types}
        )
        
    except Exception as e:
        logger.error(f"Error loading template grid: {str(e)}")
        return '<div class="text-red-500">Error loading templates</div>'