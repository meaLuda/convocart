"""
Business Templates for African SMEs
Pre-configured setups for different business types
"""
from app.models_inventory_enhanced import UnitOfMeasure, BusinessTemplate


# Template definitions for different African SME types
AFRICAN_SME_TEMPLATES = {
    "retail": {
        "name": "General Retail Store",
        "description": "General merchandise, clothing, accessories",
        "default_units": [
            UnitOfMeasure.PIECES.value,
            UnitOfMeasure.BOXES.value,
            UnitOfMeasure.PACKETS.value
        ],
        "typical_products": [
            {"name": "T-Shirts", "category": "clothing", "price": 500.0, "threshold": 10},
            {"name": "Shoes", "category": "accessories", "price": 1500.0, "threshold": 5},
            {"name": "Bags", "category": "accessories", "price": 800.0, "threshold": 8}
        ],
        "pricing_structure": {
            "retail": {"markup": 50},
            "wholesale": {"markup": 30, "min_qty": 10},
            "bulk": {"markup": 20, "min_qty": 50}
        },
        "inventory_settings": {
            "low_stock_threshold": 5,
            "track_expiry": False,
            "auto_reorder": True
        }
    },
    
    "grocery": {
        "name": "Grocery Store",
        "description": "Food items, beverages, household goods",
        "default_units": [
            UnitOfMeasure.KILOGRAMS.value,
            UnitOfMeasure.LITERS.value,
            UnitOfMeasure.PIECES.value,
            UnitOfMeasure.PACKETS.value,
            UnitOfMeasure.CRATES.value
        ],
        "typical_products": [
            {"name": "Rice", "category": "food", "price": 120.0, "threshold": 50},
            {"name": "Cooking Oil", "category": "food", "price": 300.0, "threshold": 20},
            {"name": "Bread", "category": "food", "price": 60.0, "threshold": 30},
            {"name": "Milk", "category": "beverages", "price": 80.0, "threshold": 25}
        ],
        "pricing_structure": {
            "retail": {"markup": 25},
            "wholesale": {"markup": 15, "min_qty": 20}
        },
        "inventory_settings": {
            "low_stock_threshold": 10,
            "track_expiry": True,
            "auto_reorder": True
        }
    },
    
    "pharmacy": {
        "name": "Pharmacy/Health Store",
        "description": "Medicines, health products, medical supplies",
        "default_units": [
            UnitOfMeasure.PIECES.value,
            UnitOfMeasure.BOTTLES.value,
            UnitOfMeasure.BOXES.value,
            UnitOfMeasure.MILLILITERS.value
        ],
        "typical_products": [
            {"name": "Paracetamol", "category": "medicines", "price": 50.0, "threshold": 20},
            {"name": "Bandages", "category": "health_products", "price": 80.0, "threshold": 15},
            {"name": "Antiseptic", "category": "medicines", "price": 150.0, "threshold": 10}
        ],
        "pricing_structure": {
            "retail": {"markup": 40}
        },
        "inventory_settings": {
            "low_stock_threshold": 5,
            "track_expiry": True,
            "auto_reorder": True,
            "batch_tracking": True
        }
    },
    
    "restaurant": {
        "name": "Restaurant/Food Service",
        "description": "Food ingredients, beverages, kitchen supplies",
        "default_units": [
            UnitOfMeasure.KILOGRAMS.value,
            UnitOfMeasure.LITERS.value,
            UnitOfMeasure.PIECES.value,
            UnitOfMeasure.BOTTLES.value,
            UnitOfMeasure.CRATES.value
        ],
        "typical_products": [
            {"name": "Chicken", "category": "food", "price": 400.0, "threshold": 5},
            {"name": "Tomatoes", "category": "food", "price": 80.0, "threshold": 10},
            {"name": "Cooking Oil", "category": "food", "price": 300.0, "threshold": 5},
            {"name": "Sodas", "category": "beverages", "price": 50.0, "threshold": 24}
        ],
        "pricing_structure": {
            "menu_pricing": {"food_cost_percentage": 30}
        },
        "inventory_settings": {
            "low_stock_threshold": 3,
            "track_expiry": True,
            "auto_reorder": True,
            "portion_control": True
        }
    },
    
    "agriculture": {
        "name": "Agricultural Business",
        "description": "Farm produce, seeds, fertilizers, tools",
        "default_units": [
            UnitOfMeasure.KILOGRAMS.value,
            UnitOfMeasure.TONNES.value,
            UnitOfMeasure.BAGS.value,
            UnitOfMeasure.SACKS.value,
            UnitOfMeasure.BUNDLES.value,
            UnitOfMeasure.ACRES.value
        ],
        "typical_products": [
            {"name": "Maize", "category": "physical_product", "price": 3000.0, "threshold": 5},
            {"name": "Fertilizer", "category": "physical_product", "price": 2500.0, "threshold": 10},
            {"name": "Seeds", "category": "physical_product", "price": 500.0, "threshold": 20}
        ],
        "pricing_structure": {
            "farm_gate": {"base_price": True},
            "market": {"markup": 20},
            "bulk": {"discount": 10, "min_qty": 100}
        },
        "inventory_settings": {
            "low_stock_threshold": 10,
            "track_expiry": True,
            "seasonal_planning": True
        }
    },
    
    "electronics": {
        "name": "Electronics Store",
        "description": "Phones, computers, accessories, gadgets",
        "default_units": [
            UnitOfMeasure.PIECES.value,
            UnitOfMeasure.BOXES.value,
            UnitOfMeasure.UNITS.value
        ],
        "typical_products": [
            {"name": "Smartphone", "category": "smartphones", "price": 15000.0, "threshold": 3},
            {"name": "Phone Case", "category": "accessories", "price": 300.0, "threshold": 20},
            {"name": "Charger", "category": "accessories", "price": 500.0, "threshold": 15}
        ],
        "pricing_structure": {
            "retail": {"markup": 30},
            "wholesale": {"markup": 15, "min_qty": 5}
        },
        "inventory_settings": {
            "low_stock_threshold": 2,
            "track_expiry": False,
            "warranty_tracking": True
        }
    },
    
    "fashion": {
        "name": "Fashion/Clothing Store",
        "description": "Clothing, shoes, fashion accessories",
        "default_units": [
            UnitOfMeasure.PIECES.value,
            UnitOfMeasure.BOXES.value
        ],
        "typical_products": [
            {"name": "Dress", "category": "clothing", "price": 1200.0, "threshold": 5},
            {"name": "Shoes", "category": "clothing", "price": 2000.0, "threshold": 3},
            {"name": "Handbag", "category": "accessories", "price": 800.0, "threshold": 8}
        ],
        "pricing_structure": {
            "retail": {"markup": 100},
            "wholesale": {"markup": 50, "min_qty": 10}
        },
        "inventory_settings": {
            "low_stock_threshold": 3,
            "track_expiry": False,
            "size_variants": True,
            "color_variants": True
        }
    },
    
    "automotive": {
        "name": "Auto Parts/Service",
        "description": "Car parts, oils, automotive services",
        "default_units": [
            UnitOfMeasure.PIECES.value,
            UnitOfMeasure.LITERS.value,
            UnitOfMeasure.BOTTLES.value
        ],
        "typical_products": [
            {"name": "Engine Oil", "category": "physical_product", "price": 800.0, "threshold": 10},
            {"name": "Brake Pads", "category": "physical_product", "price": 1500.0, "threshold": 5},
            {"name": "Air Filter", "category": "physical_product", "price": 400.0, "threshold": 8}
        ],
        "pricing_structure": {
            "retail": {"markup": 40},
            "wholesale": {"markup": 25, "min_qty": 5}
        },
        "inventory_settings": {
            "low_stock_threshold": 3,
            "track_expiry": False,
            "part_numbers": True
        }
    },
    
    "beauty": {
        "name": "Beauty/Cosmetics Store",
        "description": "Cosmetics, skincare, beauty products",
        "default_units": [
            UnitOfMeasure.PIECES.value,
            UnitOfMeasure.MILLILITERS.value,
            UnitOfMeasure.GRAMS.value
        ],
        "typical_products": [
            {"name": "Lipstick", "category": "health_products", "price": 400.0, "threshold": 10},
            {"name": "Foundation", "category": "health_products", "price": 800.0, "threshold": 8},
            {"name": "Moisturizer", "category": "health_products", "price": 600.0, "threshold": 12}
        ],
        "pricing_structure": {
            "retail": {"markup": 60},
            "wholesale": {"markup": 40, "min_qty": 12}
        },
        "inventory_settings": {
            "low_stock_threshold": 5,
            "track_expiry": True,
            "shade_variants": True
        }
    },
    
    "services": {
        "name": "Service Business",
        "description": "Professional services, consulting, repairs",
        "default_units": [
            UnitOfMeasure.PIECES.value,
            UnitOfMeasure.UNITS.value
        ],
        "typical_products": [
            {"name": "Service Package", "category": "service", "price": 1000.0, "threshold": 0},
            {"name": "Consultation", "category": "service", "price": 500.0, "threshold": 0}
        ],
        "pricing_structure": {
            "hourly": {"rate": 500},
            "package": {"fixed_price": True}
        },
        "inventory_settings": {
            "low_stock_threshold": 0,
            "track_expiry": False,
            "service_based": True
        }
    }
}


def create_business_templates(db):
    """Create all business templates in the database"""
    from sqlalchemy.orm import Session
    
    for business_type, template_data in AFRICAN_SME_TEMPLATES.items():
        existing = db.query(BusinessTemplate).filter(
            BusinessTemplate.business_type == business_type
        ).first()
        
        if not existing:
            template = BusinessTemplate(
                business_type=business_type,
                name=template_data["name"],
                description=template_data["description"],
                default_units=template_data["default_units"],
                typical_products=template_data["typical_products"],
                pricing_structure=template_data["pricing_structure"],
                inventory_settings=template_data["inventory_settings"]
            )
            
            db.add(template)
    
    db.commit()


def get_recommended_units_for_business(business_type: str) -> list:
    """Get recommended units for a business type"""
    return AFRICAN_SME_TEMPLATES.get(business_type, {}).get("default_units", [UnitOfMeasure.PIECES.value])


def get_typical_products_for_business(business_type: str) -> list:
    """Get typical products for a business type"""
    return AFRICAN_SME_TEMPLATES.get(business_type, {}).get("typical_products", [])