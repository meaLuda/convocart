#!/usr/bin/env python3
"""
Password Reset Script for ConvoCart Admin Users
"""
import sys
from passlib.context import CryptContext
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.config import get_settings
from app.models import User

# Password context (same as in app)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password):
    return pwd_context.hash(password)

def reset_user_password(username: str, new_password: str):
    """Reset password for a specific user"""
    settings = get_settings()
    
    # Create database connection
    engine = create_engine(settings.turso_database_url)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    
    try:
        # Find user
        user = db.query(User).filter(User.username == username).first()
        
        if not user:
            print(f"❌ User '{username}' not found!")
            return False
        
        # Update password
        user.password_hash = get_password_hash(new_password)
        db.commit()
        
        print(f"✅ Password updated successfully for user '{username}'")
        print(f"🔑 New password: {new_password}")
        return True
        
    except Exception as e:
        print(f"❌ Error updating password: {e}")
        db.rollback()
        return False
    finally:
        db.close()

def list_users():
    """List all users in the system"""
    settings = get_settings()
    
    # Create database connection
    engine = create_engine(settings.turso_database_url)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    
    try:
        users = db.query(User).all()
        print("\n📋 Current Users:")
        print("-" * 50)
        for user in users:
            print(f"👤 {user.username} | Role: {user.role.value} | Active: {user.is_active}")
        print()
        
    except Exception as e:
        print(f"❌ Error listing users: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    print("🔐 ConvoCart Password Reset Tool")
    print("=" * 40)
    
    if len(sys.argv) == 1:
        print("\nUsage:")
        print("  python reset_password.py list                    # List all users")
        print("  python reset_password.py <username> <password>   # Reset user password")
        print("\nExample:")
        print("  python reset_password.py ConvoCartAdmin newpass123")
        sys.exit(1)
    
    if sys.argv[1] == "list":
        list_users()
    elif len(sys.argv) == 3:
        username = sys.argv[1]
        new_password = sys.argv[2]
        reset_user_password(username, new_password)
    else:
        print("❌ Invalid arguments. Use 'list' or provide username and password.")