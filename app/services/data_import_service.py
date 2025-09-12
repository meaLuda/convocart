"""
Data Import Service for CSV/Excel Upload
Handles product catalog imports with business-type specific templates
"""
import logging
import pandas as pd
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from io import BytesIO
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models import (
    Product, ProductVariant, Group, BusinessType, ProductCategory,
    InventoryLog, User
)

logger = logging.getLogger(__name__)

class DataImportService:
    """
    Service to handle CSV/Excel data imports for different business types
    """
    
    def __init__(self, db: Session):
        self.db = db
        
        # Define business-specific column templates
        self.business_templates = {
            BusinessType.RESTAURANT: {
                "required_columns": ["name", "category", "price", "description"],
                "optional_columns": ["ingredients", "calories", "spice_level", "dietary_info", "preparation_time"],
                "sample_data": [
                    {"name": "Chicken Tikka Masala", "category": "food", "price": 1200, "description": "Tender chicken in creamy tomato sauce", "ingredients": "chicken, tomatoes, cream, spices", "calories": 450, "spice_level": "medium", "dietary_info": "gluten-free", "preparation_time": "15 mins"},
                    {"name": "Vegetable Biryani", "category": "food", "price": 900, "description": "Fragrant rice with mixed vegetables", "ingredients": "basmati rice, vegetables, spices", "calories": 380, "spice_level": "mild", "dietary_info": "vegan", "preparation_time": "20 mins"},
                    {"name": "Mango Lassi", "category": "beverages", "price": 250, "description": "Refreshing yogurt drink", "ingredients": "mango, yogurt, sugar", "calories": 180, "spice_level": "none", "dietary_info": "vegetarian", "preparation_time": "5 mins"}
                ]
            },
            BusinessType.FASHION: {
                "required_columns": ["name", "category", "price", "description"],
                "optional_columns": ["size", "color", "material", "brand", "season", "gender"],
                "sample_data": [
                    {"name": "Cotton T-Shirt", "category": "clothing", "price": 1500, "description": "Comfortable cotton t-shirt", "size": "S,M,L,XL", "color": "white,black,navy", "material": "100% cotton", "brand": "StyleCo", "season": "all", "gender": "unisex"},
                    {"name": "Denim Jeans", "category": "clothing", "price": 3500, "description": "Classic fit denim jeans", "size": "28,30,32,34,36", "color": "blue,black", "material": "98% cotton, 2% elastane", "brand": "DenimPro", "season": "all", "gender": "unisex"},
                    {"name": "Leather Handbag", "category": "accessories", "price": 4500, "description": "Genuine leather handbag", "size": "medium", "color": "brown,black,tan", "material": "genuine leather", "brand": "LuxBags", "season": "all", "gender": "women"}
                ]
            },
            BusinessType.ELECTRONICS: {
                "required_columns": ["name", "category", "price", "description"],
                "optional_columns": ["brand", "model", "specifications", "warranty", "compatibility"],
                "sample_data": [
                    {"name": "Smartphone Pro X", "category": "smartphones", "price": 45000, "description": "Latest smartphone with advanced features", "brand": "TechBrand", "model": "Pro X", "specifications": "6.1 display, 128GB storage, 12MP camera", "warranty": "2 years", "compatibility": "5G, WiFi 6"},
                    {"name": "Wireless Earbuds", "category": "accessories", "price": 8000, "description": "Noise-cancelling wireless earbuds", "brand": "AudioTech", "model": "Sound Pro", "specifications": "Bluetooth 5.0, 8hr battery", "warranty": "1 year", "compatibility": "iOS, Android"},
                    {"name": "Laptop Stand", "category": "accessories", "price": 2500, "description": "Adjustable aluminum laptop stand", "brand": "ErgoDesk", "model": "Lift Pro", "specifications": "Adjustable height, foldable", "warranty": "6 months", "compatibility": "Universal"}
                ]
            },
            BusinessType.GROCERY: {
                "required_columns": ["name", "category", "price", "description"],
                "optional_columns": ["weight", "unit", "brand", "organic", "expiry_days"],
                "sample_data": [
                    {"name": "Fresh Bananas", "category": "food", "price": 150, "description": "Fresh organic bananas", "weight": "1kg", "unit": "kg", "brand": "FreshFarms", "organic": "yes", "expiry_days": "7"},
                    {"name": "Whole Wheat Bread", "category": "food", "price": 80, "description": "Fresh whole wheat bread", "weight": "400g", "unit": "loaf", "brand": "BakeryFresh", "organic": "no", "expiry_days": "3"},
                    {"name": "Olive Oil", "category": "food", "price": 650, "description": "Extra virgin olive oil", "weight": "500ml", "unit": "bottle", "brand": "Mediterranean", "organic": "yes", "expiry_days": "730"}
                ]
            },
            BusinessType.PHARMACY: {
                "required_columns": ["name", "category", "price", "description"],
                "optional_columns": ["dosage", "active_ingredient", "prescription_required", "manufacturer"],
                "sample_data": [
                    {"name": "Paracetamol 500mg", "category": "medicines", "price": 120, "description": "Pain and fever relief tablets", "dosage": "500mg", "active_ingredient": "Paracetamol", "prescription_required": "no", "manufacturer": "PharmaCorp"},
                    {"name": "Vitamin D3", "category": "health_products", "price": 850, "description": "Vitamin D3 supplement capsules", "dosage": "1000IU", "active_ingredient": "Cholecalciferol", "prescription_required": "no", "manufacturer": "HealthPlus"},
                    {"name": "Blood Pressure Monitor", "category": "health_products", "price": 3500, "description": "Digital blood pressure monitor", "dosage": "N/A", "active_ingredient": "N/A", "prescription_required": "no", "manufacturer": "MediTech"}
                ]
            },
            BusinessType.SERVICES: {
                "required_columns": ["name", "category", "price", "description"],
                "optional_columns": ["duration", "location", "expertise_level", "booking_required"],
                "sample_data": [
                    {"name": "Business Consultation", "category": "consultation", "price": 5000, "description": "1-hour business strategy consultation", "duration": "60 minutes", "location": "office/online", "expertise_level": "expert", "booking_required": "yes"},
                    {"name": "Web Development", "category": "service", "price": 25000, "description": "Custom website development", "duration": "2-4 weeks", "location": "remote", "expertise_level": "professional", "booking_required": "yes"},
                    {"name": "Home Cleaning", "category": "service", "price": 2500, "description": "3-hour home cleaning service", "duration": "3 hours", "location": "customer_location", "expertise_level": "professional", "booking_required": "yes"}
                ]
            },
            BusinessType.GENERAL: {
                "required_columns": ["name", "category", "price", "description"],
                "optional_columns": ["brand", "model", "condition", "warranty", "specifications"],
                "sample_data": [
                    {"name": "Office Chair", "category": "physical_product", "price": 8500, "description": "Ergonomic office chair", "brand": "OfficeMax", "model": "Ergo Pro", "condition": "new", "warranty": "2 years", "specifications": "Height adjustable, lumbar support"},
                    {"name": "Digital Marketing Course", "category": "digital_product", "price": 15000, "description": "Complete digital marketing course", "brand": "LearnOnline", "model": "Advanced", "condition": "new", "warranty": "lifetime access", "specifications": "12 modules, 50 hours content"},
                    {"name": "Event Planning", "category": "service", "price": 45000, "description": "Complete event planning service", "brand": "EventPro", "model": "Premium", "condition": "N/A", "warranty": "satisfaction guarantee", "specifications": "Full event management"}
                ]
            }
        }
    
    def generate_sample_csv(self, business_type: BusinessType) -> bytes:
        """
        Generate sample CSV template for specific business type
        """
        try:
            template = self.business_templates.get(business_type, self.business_templates[BusinessType.GENERAL])
            
            # Create DataFrame with sample data
            df = pd.DataFrame(template["sample_data"])
            
            # Add all possible columns (required + optional)
            all_columns = template["required_columns"] + template["optional_columns"]
            
            # Reorder columns to match template order
            existing_columns = [col for col in all_columns if col in df.columns]
            df = df[existing_columns]
            
            # Convert to CSV bytes
            csv_buffer = BytesIO()
            df.to_csv(csv_buffer, index=False, encoding='utf-8')
            csv_buffer.seek(0)
            
            return csv_buffer.getvalue()
            
        except Exception as e:
            logger.error(f"Error generating sample CSV for {business_type}: {str(e)}")
            raise
    
    def get_template_info(self, business_type: BusinessType) -> Dict[str, Any]:
        """
        Get template information for UI display
        """
        template = self.business_templates.get(business_type, self.business_templates[BusinessType.GENERAL])
        
        return {
            "business_type": business_type.value,
            "required_columns": template["required_columns"],
            "optional_columns": template["optional_columns"],
            "sample_count": len(template["sample_data"]),
            "column_descriptions": self._get_column_descriptions(business_type),
            "validation_rules": self._get_validation_rules(business_type)
        }
    
    def validate_upload_data(self, df: pd.DataFrame, business_type: BusinessType, group_id: int) -> Dict[str, Any]:
        """
        Validate uploaded CSV/Excel data
        """
        template = self.business_templates.get(business_type, self.business_templates[BusinessType.GENERAL])
        validation_result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "summary": {
                "total_rows": len(df),
                "valid_rows": 0,
                "invalid_rows": 0,
                "duplicate_names": []
            }
        }
        
        try:
            # Check required columns
            missing_columns = set(template["required_columns"]) - set(df.columns)
            if missing_columns:
                validation_result["valid"] = False
                validation_result["errors"].append(f"Missing required columns: {', '.join(missing_columns)}")
                return validation_result
            
            # Validate each row
            valid_rows = 0
            duplicate_names = []
            existing_names = set()
            
            for index, row in df.iterrows():
                row_errors = []
                
                # Check required fields
                for col in template["required_columns"]:
                    if pd.isna(row[col]) or str(row[col]).strip() == "":
                        row_errors.append(f"Row {index + 1}: Missing required field '{col}'")
                
                # Validate price
                try:
                    price = float(row.get('price', 0))
                    if price < 0:
                        row_errors.append(f"Row {index + 1}: Price cannot be negative")
                except (ValueError, TypeError):
                    row_errors.append(f"Row {index + 1}: Invalid price format")
                
                # Check for duplicate names in this upload
                name = str(row.get('name', '')).strip().lower()
                if name in existing_names:
                    duplicate_names.append(f"Row {index + 1}: Duplicate product name '{row.get('name')}'")
                else:
                    existing_names.add(name)
                
                # Business-specific validations
                business_errors = self._validate_business_specific_fields(row, business_type, index + 1)
                row_errors.extend(business_errors)
                
                if row_errors:
                    validation_result["errors"].extend(row_errors)
                    validation_result["summary"]["invalid_rows"] += 1
                else:
                    valid_rows += 1
            
            validation_result["summary"]["valid_rows"] = valid_rows
            validation_result["summary"]["duplicate_names"] = duplicate_names
            
            # Check for duplicates with existing products
            existing_products = self._check_existing_products(df, group_id)
            if existing_products:
                validation_result["warnings"].extend([
                    f"Product '{name}' already exists and will be updated" 
                    for name in existing_products
                ])
            
            # Final validation
            if validation_result["errors"]:
                validation_result["valid"] = False
            
            return validation_result
            
        except Exception as e:
            logger.error(f"Error validating upload data: {str(e)}")
            validation_result["valid"] = False
            validation_result["errors"].append(f"Validation error: {str(e)}")
            return validation_result
    
    def import_products(self, df: pd.DataFrame, business_type: BusinessType, 
                       group_id: int, user_id: int, update_existing: bool = True) -> Dict[str, Any]:
        """
        Import products from validated DataFrame
        """
        import_result = {
            "success": True,
            "summary": {
                "total_processed": 0,
                "created": 0,
                "updated": 0,
                "skipped": 0,
                "errors": []
            },
            "details": []
        }
        
        try:
            for index, row in df.iterrows():
                try:
                    product_result = self._import_single_product(
                        row, business_type, group_id, user_id, update_existing
                    )
                    
                    import_result["summary"]["total_processed"] += 1
                    import_result["summary"][product_result["action"]] += 1
                    import_result["details"].append({
                        "row": index + 1,
                        "product_name": row.get('name'),
                        "action": product_result["action"],
                        "message": product_result["message"]
                    })
                    
                except Exception as e:
                    error_msg = f"Row {index + 1} ({row.get('name', 'Unknown')}): {str(e)}"
                    import_result["summary"]["errors"].append(error_msg)
                    import_result["summary"]["skipped"] += 1
                    logger.error(f"Error importing product: {error_msg}")
            
            # Commit all changes
            self.db.commit()
            
            # Check if any products were processed successfully
            if import_result["summary"]["created"] == 0 and import_result["summary"]["updated"] == 0:
                import_result["success"] = False
            
            return import_result
            
        except Exception as e:
            logger.error(f"Error importing products: {str(e)}")
            self.db.rollback()
            import_result["success"] = False
            import_result["summary"]["errors"].append(f"Import failed: {str(e)}")
            return import_result
    
    def export_products_template(self, group_id: int, business_type: BusinessType) -> bytes:
        """
        Export existing products as CSV template
        """
        try:
            # Get existing products
            products = self.db.query(Product).filter(
                Product.group_id == group_id,
                Product.is_active == True
            ).all()
            
            if not products:
                # Return empty template if no products
                return self.generate_sample_csv(business_type)
            
            # Convert products to DataFrame
            product_data = []
            template = self.business_templates.get(business_type, self.business_templates[BusinessType.GENERAL])
            all_columns = template["required_columns"] + template["optional_columns"]
            
            for product in products:
                row_data = {
                    "name": product.name,
                    "category": product.category.value if product.category else "",
                    "price": product.base_price,
                    "description": product.description or "",
                }
                
                # Add business-specific attributes
                if product.attributes:
                    for col in template["optional_columns"]:
                        if col in product.attributes:
                            row_data[col] = product.attributes[col]
                        else:
                            row_data[col] = ""
                
                product_data.append(row_data)
            
            df = pd.DataFrame(product_data)
            
            # Ensure all template columns are present
            for col in all_columns:
                if col not in df.columns:
                    df[col] = ""
            
            # Reorder columns
            df = df[[col for col in all_columns if col in df.columns]]
            
            # Convert to CSV bytes
            csv_buffer = BytesIO()
            df.to_csv(csv_buffer, index=False, encoding='utf-8')
            csv_buffer.seek(0)
            
            return csv_buffer.getvalue()
            
        except Exception as e:
            logger.error(f"Error exporting products template: {str(e)}")
            raise
    
    # Private helper methods
    def _get_column_descriptions(self, business_type: BusinessType) -> Dict[str, str]:
        """Get column descriptions for UI help"""
        descriptions = {
            "name": "Product/service name (required)",
            "category": "Product category (required)",
            "price": "Price in your currency (required)",
            "description": "Product description (required)",
            "brand": "Brand or manufacturer name",
            "model": "Product model or version",
            "size": "Available sizes (comma-separated for variants)",
            "color": "Available colors (comma-separated for variants)",
            "weight": "Product weight",
            "unit": "Unit of measurement",
            "specifications": "Technical specifications",
            "warranty": "Warranty period",
            "ingredients": "Food ingredients",
            "calories": "Caloric content",
            "spice_level": "Spice level (none/mild/medium/hot)",
            "dietary_info": "Dietary information (vegan/vegetarian/gluten-free)",
            "dosage": "Medicine dosage",
            "active_ingredient": "Active pharmaceutical ingredient",
            "prescription_required": "Whether prescription is required (yes/no)",
            "duration": "Service duration",
            "location": "Service location",
            "expertise_level": "Required expertise level"
        }
        return descriptions
    
    def _get_validation_rules(self, business_type: BusinessType) -> Dict[str, str]:
        """Get validation rules for UI display"""
        return {
            "name": "Must be unique within your catalog",
            "price": "Must be a positive number",
            "category": "Must match available categories for your business type",
            "size": "Use comma-separated values for multiple sizes (S,M,L,XL)",
            "color": "Use comma-separated values for multiple colors",
            "spice_level": "Use: none, mild, medium, hot",
            "prescription_required": "Use: yes or no",
            "organic": "Use: yes or no"
        }
    
    def _validate_business_specific_fields(self, row: pd.Series, business_type: BusinessType, row_num: int) -> List[str]:
        """Validate business-specific fields"""
        errors = []
        
        if business_type == BusinessType.RESTAURANT:
            # Validate spice level
            spice_level = str(row.get('spice_level', '')).lower()
            if spice_level and spice_level not in ['none', 'mild', 'medium', 'hot', '']:
                errors.append(f"Row {row_num}: Invalid spice level. Use: none, mild, medium, hot")
        
        elif business_type == BusinessType.PHARMACY:
            # Validate prescription required
            prescription = str(row.get('prescription_required', '')).lower()
            if prescription and prescription not in ['yes', 'no', 'true', 'false', '']:
                errors.append(f"Row {row_num}: prescription_required must be 'yes' or 'no'")
        
        return errors
    
    def _check_existing_products(self, df: pd.DataFrame, group_id: int) -> List[str]:
        """Check for products that already exist"""
        product_names = [str(name).strip().lower() for name in df['name'].tolist()]
        
        existing = self.db.query(Product.name).filter(
            Product.group_id == group_id,
            func.lower(Product.name).in_(product_names)
        ).all()
        
        return [product.name for product in existing]
    
    def _import_single_product(self, row: pd.Series, business_type: BusinessType, 
                              group_id: int, user_id: int, update_existing: bool) -> Dict[str, str]:
        """Import a single product from row data"""
        product_name = str(row['name']).strip()
        
        # Check if product exists
        existing_product = self.db.query(Product).filter(
            Product.group_id == group_id,
            func.lower(Product.name) == product_name.lower()
        ).first()
        
        if existing_product and not update_existing:
            return {"action": "skipped", "message": "Product already exists"}
        
        # Parse category
        category_value = str(row['category']).strip().lower()
        product_category = None
        for cat in ProductCategory:
            if cat.value.lower() == category_value:
                product_category = cat
                break
        
        # Parse price
        price = float(row['price'])
        
        # Build attributes from optional columns
        template = self.business_templates.get(business_type, self.business_templates[BusinessType.GENERAL])
        attributes = {}
        
        for col in template["optional_columns"]:
            if col in row and not pd.isna(row[col]) and str(row[col]).strip():
                attributes[col] = str(row[col]).strip()
        
        if existing_product:
            # Update existing product
            existing_product.name = product_name
            existing_product.description = str(row['description']).strip()
            existing_product.category = product_category
            existing_product.base_price = price
            existing_product.attributes = attributes
            existing_product.updated_at = datetime.utcnow()
            
            action = "updated"
            message = "Product updated successfully"
        else:
            # Create new product
            new_product = Product(
                group_id=group_id,
                name=product_name,
                description=str(row['description']).strip(),
                category=product_category,
                base_price=price,
                attributes=attributes,
                is_active=True
            )
            
            self.db.add(new_product)
            self.db.flush()  # Get the product ID
            
            # Log initial inventory if specified
            if 'stock_quantity' in attributes:
                try:
                    initial_stock = int(attributes['stock_quantity'])
                    if initial_stock > 0:
                        new_product.stock_quantity = initial_stock
                        
                        # Create inventory log
                        inventory_log = InventoryLog(
                            product_id=new_product.id,
                            change_type='initial_stock',
                            quantity_before=0,
                            quantity_change=initial_stock,
                            quantity_after=initial_stock,
                            reason='Initial import',
                            user_id=user_id
                        )
                        self.db.add(inventory_log)
                except ValueError:
                    pass  # Ignore invalid stock quantity
            
            action = "created"
            message = "Product created successfully"
        
        # Handle variants if size/color info provided
        if 'size' in attributes or 'color' in attributes:
            self._create_product_variants(existing_product or new_product, attributes)
        
        return {"action": action, "message": message}
    
    def _create_product_variants(self, product: Product, attributes: Dict[str, str]):
        """Create product variants from size/color information"""
        try:
            sizes = []
            colors = []
            
            if 'size' in attributes and attributes['size']:
                sizes = [s.strip() for s in attributes['size'].split(',') if s.strip()]
            
            if 'color' in attributes and attributes['color']:
                colors = [c.strip() for c in attributes['color'].split(',') if c.strip()]
            
            if sizes or colors:
                product.has_variants = True
                
                # Create variant combinations
                if sizes and colors:
                    # Size + Color combinations
                    for size in sizes:
                        for color in colors:
                            variant = ProductVariant(
                                product_id=product.id,
                                variant_name=f"{product.name} - {size} {color}",
                                variant_options={"size": size, "color": color},
                                stock_quantity=0,
                                is_active=True
                            )
                            self.db.add(variant)
                elif sizes:
                    # Size only
                    for size in sizes:
                        variant = ProductVariant(
                            product_id=product.id,
                            variant_name=f"{product.name} - {size}",
                            variant_options={"size": size},
                            stock_quantity=0,
                            is_active=True
                        )
                        self.db.add(variant)
                elif colors:
                    # Color only
                    for color in colors:
                        variant = ProductVariant(
                            product_id=product.id,
                            variant_name=f"{product.name} - {color}",
                            variant_options={"color": color},
                            stock_quantity=0,
                            is_active=True
                        )
                        self.db.add(variant)
                
        except Exception as e:
            logger.error(f"Error creating variants for {product.name}: {str(e)}")


def get_data_import_service(db: Session) -> DataImportService:
    """Get data import service instance"""
    return DataImportService(db)