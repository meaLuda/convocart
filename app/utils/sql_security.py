"""
SQL Security utilities for protecting against injection attacks
"""
import re
import logging
from typing import Any

logger = logging.getLogger(__name__)

def escape_sql_pattern(pattern: str) -> str:
    """
    Escape special characters in SQL LIKE patterns to prevent injection
    
    Args:
        pattern: The pattern string to escape
        
    Returns:
        str: Escaped pattern safe for use in SQL LIKE queries
    """
    if not pattern:
        return ""
    
    # Escape special SQL characters
    # % and _ are SQL LIKE wildcards that need escaping
    # \ is the escape character itself
    pattern = pattern.replace('\\', '\\\\')  # Escape backslashes first
    pattern = pattern.replace('%', '\\%')     # Escape % wildcard
    pattern = pattern.replace('_', '\\_')     # Escape _ wildcard
    
    return pattern

def sanitize_search_input(search_input: str, max_length: int = 100) -> str:
    """
    Sanitize user search input to prevent SQL injection and other attacks
    
    Args:
        search_input: Raw search input from user
        max_length: Maximum allowed length for the input
        
    Returns:
        str: Sanitized search input
    """
    if not search_input:
        return ""
    
    # Remove potential SQL injection patterns
    dangerous_patterns = [
        r"'", r'"', r';', r'--', r'/\*', r'\*/', 
        r'\bUNION\b', r'\bSELECT\b', r'\bINSERT\b', 
        r'\bUPDATE\b', r'\bDELETE\b', r'\bDROP\b',
        r'\bALTER\b', r'\bCREATE\b', r'\bEXEC\b'
    ]
    
    sanitized = search_input
    
    # Remove dangerous patterns (case insensitive)
    for pattern in dangerous_patterns:
        sanitized = re.sub(pattern, '', sanitized, flags=re.IGNORECASE)
    
    # Trim whitespace
    sanitized = sanitized.strip()
    
    # Limit length
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length]
        logger.warning(f"Search input truncated from {len(search_input)} to {max_length} characters")
    
    return sanitized

def validate_column_name(column_name: str) -> bool:
    """
    Validate that a column name is safe (alphanumeric + underscore only)
    
    Args:
        column_name: Column name to validate
        
    Returns:
        bool: True if safe, False otherwise
    """
    if not column_name:
        return False
    
    # Only allow alphanumeric characters and underscores
    return bool(re.match(r'^[a-zA-Z][a-zA-Z0-9_]*$', column_name))

def safe_like_query(query, column, search_term: str, escape_char: str = '\\'):
    """
    Create a safe LIKE query with proper escaping
    
    Args:
        query: SQLAlchemy query object
        column: SQLAlchemy column object
        search_term: The term to search for
        escape_char: Character to use for escaping (default: backslash)
        
    Returns:
        Modified query with safe LIKE clause
    """
    if not search_term:
        return query
    
    # Escape the search term
    escaped_term = escape_sql_pattern(search_term)
    
    # Create the LIKE pattern with wildcards
    like_pattern = f"%{escaped_term}%"
    
    # Use SQLAlchemy's built-in protection
    return query.filter(column.ilike(like_pattern, escape=escape_char))

class SQLInjectionDetector:
    """Detector for potential SQL injection attempts"""
    
    def __init__(self):
        self.suspicious_patterns = [
            r"'[^']*'(\s*)?(;|\||\||&)",  # Quoted strings followed by operators
            r"(union|select|insert|update|delete|drop|create|alter|exec)\s+",  # SQL keywords
            r"(--|#|/\*)",  # SQL comments
            r"(\bor\b|\band\b)\s+\d+\s*=\s*\d+",  # OR/AND conditions with numbers
            r"(char|varchar|nvarchar)\s*\(",  # SQL cast functions
            r"(waitfor|delay)\s+",  # Time-based attacks
            r"(sp_|xp_)\w+",  # Stored procedures
            r"(@@|@@version|@@servername)",  # System variables
        ]
    
    def is_suspicious(self, user_input: str) -> bool:
        """
        Check if user input contains suspicious patterns
        
        Args:
            user_input: Input to check
            
        Returns:
            bool: True if suspicious patterns detected
        """
        if not user_input:
            return False
        
        input_lower = user_input.lower()
        
        for pattern in self.suspicious_patterns:
            if re.search(pattern, input_lower, re.IGNORECASE):
                logger.warning(f"Suspicious SQL pattern detected: {pattern}")
                return True
        
        return False
    
    def log_attempt(self, user_input: str, client_ip: str = None):
        """Log potential SQL injection attempt"""
        logger.error(f"Potential SQL injection attempt from {client_ip}: {user_input[:100]}...")

# Global detector instance
sql_detector = SQLInjectionDetector()