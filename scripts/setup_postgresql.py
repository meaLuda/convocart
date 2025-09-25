#!/usr/bin/env python3
"""
Setup script for PostgreSQL migration from Turso.
This script helps create initial migrations for the PostgreSQL database.
"""

import os
import sys
import subprocess
from pathlib import Path
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
os.chdir(BASE_DIR)
print(f"📁 Changed working directory to {BASE_DIR}")
load_dotenv(BASE_DIR / ".env")
print("🔄 Loaded environment variables from .env"
      if os.getenv("DATABASE_URL") else "⚠️  No .env file found or DATABASE_URL not set")

def run_command(command, description):
    """Run a command and handle errors."""
    print(f"\n🔄 {description}...")
    print(f"   Running: {command}")
    
    try:
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        print(f"✅ {description} completed successfully")
        if result.stdout:
            print(f"   Output: {result.stdout.strip()}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} failed")
        print(f"   Error: {e.stderr.strip()}")
        return False

def check_database_url():
    """Check if DATABASE_URL is set."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("❌ DATABASE_URL environment variable is not set!")
        print("   Please set it in your .env file or environment")
        print("   Example: DATABASE_URL=postgresql://user:pass@host:port/dbname")
        return False
    
    if not database_url.startswith("postgresql://"):
        print("❌ DATABASE_URL must start with 'postgresql://'")
        return False
    
    print(f"✅ DATABASE_URL is set: {database_url[:50]}...")
    return True

def main():
    """Main setup function."""
    print("🚀 PostgreSQL Migration Setup")
    print("=" * 50)
    
    # Check if we're in the right directory
    if not Path("alembic").exists():
        print("❌ This script must be run from the project root directory")
        print("   (where the 'alembic' folder is located)")
        sys.exit(1)
    
    # Check DATABASE_URL
    if not check_database_url():
        sys.exit(1)
    
    # Step 1: Create initial migration
    if not run_command(
        "uv run alembic revision --autogenerate -m 'Initial PostgreSQL migration'",
        "Creating initial migration"
    ):
        print("\n❌ Failed to create migration. Check your DATABASE_URL and ensure PostgreSQL is accessible.")
        sys.exit(1)
    
    # Step 2: Apply migration (optional - user choice)
    print("\n🤔 Do you want to apply the migration now? (y/n): ", end="")
    apply_now = input().lower().strip()
    
    if apply_now in ['y', 'yes']:
        if run_command(
            "uv run alembic upgrade head",
            "Applying migrations to PostgreSQL"
        ):
            print("\n🎉 PostgreSQL setup completed successfully!")
            print("   Your database schema is now ready.")
        else:
            print("\n❌ Migration failed. Please check your database connection.")
            sys.exit(1)
    else:
        print("\n⏸️  Migration created but not applied.")
        print("   To apply later, run: uv run alembic upgrade head")
    
    print("\n✨ Next steps:")
    print("   1. Verify your PostgreSQL connection")
    print("   2. Test the application: uv run uvicorn app.main:app --reload")
    print("   3. Check that all features work correctly")

if __name__ == "__main__":
    main()