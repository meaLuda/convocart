"""
Sample Data Generator for Multi-Business Types
Creates realistic sample data for different business types
"""
import sys
import os
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

from app.database import SessionLocal, engine
from app.models import *
from app.services.business_config_service import get_business_config_service
from app.services.data_import_service import get_data_import_service
from app.config import get_settings
from passlib.context import CryptContext
import pandas as pd
from io import BytesIO

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
settings = get_settings()

def get_password_hash(password):
    return pwd_context.hash(password)

def create_sample_businesses():
    """Create sample businesses for different business types"""
    db = SessionLocal()
    
    try:
        # Create sample businesses
        businesses = [
            {
                "name": "Pizza Palace",
                "business_type": BusinessType.RESTAURANT,
                "contact_phone": "+27123456789",
                "description": "Family-owned pizza restaurant with authentic Italian recipes"
            },
            {
                "name": "Fashion Forward",
                "business_type": BusinessType.FASHION,
                "contact_phone": "+27123456790", 
                "description": "Trendy clothing store for young professionals"
            },
            {
                "name": "TechHub Electronics",
                "business_type": BusinessType.ELECTRONICS,
                "contact_phone": "+27123456791",
                "description": "Latest gadgets and electronics for tech enthusiasts"
            },
            {
                "name": "Fresh Market Grocery",
                "business_type": BusinessType.GROCERY,
                "contact_phone": "+27123456792",
                "description": "Fresh produce and everyday essentials"
            },
            {
                "name": "HealthCare Pharmacy",
                "business_type": BusinessType.PHARMACY,
                "contact_phone": "+27123456793",
                "description": "Your trusted neighborhood pharmacy"
            }
        ]
        
        config_service = get_business_config_service(db)
        
        for biz in businesses:
            # Check if business already exists
            existing = db.query(Group).filter(Group.name == biz["name"]).first()
            if existing:
                print(f"Business '{biz['name']}' already exists, skipping...")
                continue
            
            # Create the business group
            group = Group(
                name=biz["name"],
                identifier=biz["name"].lower().replace(" ", "_").replace("'", ""),
                business_type=biz["business_type"],
                contact_phone=biz["contact_phone"],
                description=biz["description"],
                is_active=True
            )
            
            db.add(group)
            db.flush()  # Get the group ID
            
            # Configure the business with appropriate settings
            config_service.configure_business(group.id, biz["business_type"])
            
            print(f"Created business: {biz['name']} ({biz['business_type'].value})")
        
        db.commit()
        print("Sample businesses created successfully!")
        
    except Exception as e:
        print(f"Error creating sample businesses: {str(e)}")
        db.rollback()
    finally:
        db.close()

def populate_sample_products():
    """Populate each business with sample products using CSV templates"""
    db = SessionLocal()
    
    try:
        groups = db.query(Group).filter(Group.is_active == True).all()
        import_service = get_data_import_service(db)
        
        for group in groups:
            print(f"Adding products for {group.name} ({group.business_type.value})...")
            
            # Generate sample CSV for this business type
            csv_data = import_service.generate_sample_csv(group.business_type)
            
            # Convert CSV to DataFrame
            df = pd.read_csv(BytesIO(csv_data))
            
            # Import the products
            import_result = import_service.import_products(
                df=df,
                business_type=group.business_type,
                group_id=group.id,
                user_id=1,  # Default admin user
                update_existing=False
            )
            
            if import_result["success"]:
                print(f"  ✅ Added {import_result['imported']} products")
            else:
                print(f"  ❌ Failed: {import_result.get('error', 'Unknown error')}")
        
        print("Sample products populated successfully!")
        
    except Exception as e:
        print(f"Error populating sample products: {str(e)}")
        db.rollback()
    finally:
        db.close()

def create_sample_customers():
    """Create sample customers and conversation data"""
    db = SessionLocal()
    
    try:
        groups = db.query(Group).filter(Group.is_active == True).all()
        
        sample_customers = [
            {
                "phone": "+27821234567",
                "name": "John Doe",
                "preferred_language": "en"
            },
            {
                "phone": "+27821234568", 
                "name": "Jane Smith",
                "preferred_language": "en"
            },
            {
                "phone": "+27821234569",
                "name": "Mike Johnson", 
                "preferred_language": "en"
            }
        ]
        
        for group in groups:
            for customer_data in sample_customers:
                # Check if customer already exists for this group
                existing = db.query(Customer).filter(
                    Customer.phone_number == customer_data["phone"],
                    Customer.group_id == group.id
                ).first()
                
                if existing:
                    continue
                
                customer = Customer(
                    phone_number=customer_data["phone"],
                    name=customer_data["name"],
                    group_id=group.id,
                    preferred_language=customer_data["preferred_language"],
                    is_active=True
                )
                
                db.add(customer)
        
        db.commit()
        print("Sample customers created successfully!")
        
    except Exception as e:
        print(f"Error creating sample customers: {str(e)}")
        db.rollback()
    finally:
        db.close()

def main():
    """Run the complete sample data generation"""
    print("🚀 Starting sample data generation...")
    
    # Ensure all tables are created
    Base.metadata.create_all(bind=engine)
    
    # Step 1: Create sample businesses
    print("\n📊 Creating sample businesses...")
    create_sample_businesses()
    
    # Step 2: Populate with products
    print("\n🛍️ Populating sample products...")
    populate_sample_products()
    
    # Step 3: Create sample customers
    print("\n👥 Creating sample customers...")
    create_sample_customers()
    
    print("\n✅ Sample data generation completed!")
    print("\nYou can now test the multi-business functionality with:")
    print("- Pizza Palace (Restaurant)")
    print("- Fashion Forward (Fashion)")
    print("- TechHub Electronics (Electronics)")
    print("- Fresh Market Grocery (Grocery)")
    print("- HealthCare Pharmacy (Pharmacy)")

if __name__ == "__main__":
    main()