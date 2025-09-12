"""
Update existing groups table with missing columns for multi-business support
"""
import sys
import os
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

from app.database import SessionLocal, engine
from sqlalchemy import text

def update_groups_table():
    """Add missing columns to groups table"""
    db = SessionLocal()
    
    try:
        # Check current columns
        result = db.execute(text('PRAGMA table_info(groups)'))
        existing_columns = {col[1] for col in result.fetchall()}
        
        # Columns to add
        new_columns = {
            'business_type': 'VARCHAR(20) DEFAULT "general"',
            'phone_number': 'VARCHAR(20)',
            'business_settings': 'TEXT DEFAULT "{}"',
            'operating_hours': 'TEXT DEFAULT "{}"',
            'delivery_areas': 'TEXT DEFAULT "[]"',
            'payment_methods': 'TEXT DEFAULT "[]"',
            'ai_personality': 'TEXT DEFAULT "{}"',
            'custom_prompts': 'TEXT DEFAULT "{}"',
            'analytics_enabled': 'BOOLEAN DEFAULT 1',
            'recommendation_engine': 'TEXT DEFAULT "{}"'
        }
        
        for col_name, col_def in new_columns.items():
            if col_name not in existing_columns:
                print(f"Adding column: {col_name}")
                db.execute(text(f'ALTER TABLE groups ADD COLUMN {col_name} {col_def}'))
                db.commit()
        
        print("✅ Groups table updated successfully!")
        
        # Verify the update
        result = db.execute(text('PRAGMA table_info(groups)'))
        columns = result.fetchall()
        print('\nUpdated groups table columns:')
        for col in columns:
            print(f'  {col[1]} {col[2]}')
            
    except Exception as e:
        print(f"Error updating groups table: {str(e)}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    update_groups_table()