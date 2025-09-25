from fastapi.templating import Jinja2Templates
from fastapi import Request
from pathlib import Path

# Initialize templates
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

def get_flashed_messages(with_categories=False):
    """Dummy function for compatibility with Flask-style templates"""
    return []

# Add functions to template globals
templates.env.globals['get_flashed_messages'] = get_flashed_messages