#!/usr/bin/env python3
"""
Quick fix script to update LangGraph dependencies for the modernized state management system
"""

import subprocess
import sys
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_command(command):
    """Run a shell command and return the result"""
    try:
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        logger.info(f"✅ Command succeeded: {command}")
        return result.stdout
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Command failed: {command}")
        logger.error(f"Error: {e.stderr}")
        return None

def main():
    """Update dependencies to fix import issues"""
    logger.info("🔧 Fixing LangGraph dependencies...")
    
    # Update to correct LangGraph version
    logger.info("📦 Installing correct LangGraph version...")
    result = run_command("uv add 'langgraph>=0.2.14'")
    
    if result is not None:
        logger.info("✅ Dependencies updated successfully!")
        logger.info("🚀 You can now run: make run_app")
    else:
        logger.error("❌ Failed to update dependencies")
        logger.info("💡 Please try manually: uv add 'langgraph>=0.2.14'")
        sys.exit(1)

if __name__ == "__main__":
    main()