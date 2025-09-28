"""
Comprehensive Session Management Service for FastAPI
Implements secure session handling with HTTPOnly, Secure, and SameSite cookies
"""
import json
import logging
import secrets
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Union
from fastapi import Request, Response, HTTPException, Depends
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from app.config import get_settings

logger = logging.getLogger(__name__)

class SessionData:
    """
    Session data container with automatic serialization
    """
    
    def __init__(self, user_id: Optional[int] = None, username: Optional[str] = None, 
                 role: Optional[str] = None, **kwargs):
        self.user_id = user_id
        self.username = username  
        self.role = role
        self.created_at = datetime.utcnow()
        self.last_accessed = datetime.utcnow()
        self.data = kwargs
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert session data to dictionary for serialization"""
        return {
            'user_id': self.user_id,
            'username': self.username,
            'role': self.role,
            'created_at': self.created_at.isoformat(),
            'last_accessed': self.last_accessed.isoformat(),
            'data': self.data
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SessionData':
        """Create SessionData from dictionary"""
        session = cls(
            user_id=data.get('user_id'),
            username=data.get('username'),
            role=data.get('role'),
            **data.get('data', {})
        )
        
        # Parse datetime strings
        if 'created_at' in data:
            session.created_at = datetime.fromisoformat(data['created_at'])
        if 'last_accessed' in data:
            session.last_accessed = datetime.fromisoformat(data['last_accessed'])
            
        return session
    
    def update_access_time(self):
        """Update last accessed time"""
        self.last_accessed = datetime.utcnow()
    
    def is_expired(self, max_age_seconds: int) -> bool:
        """Check if session is expired"""
        expiry_time = self.last_accessed + timedelta(seconds=max_age_seconds)
        return datetime.utcnow() > expiry_time
    
    def should_rotate(self, rotation_interval_seconds: int = 1800) -> bool:
        """Check if session should be rotated (default 30 minutes)"""
        rotation_time = self.created_at + timedelta(seconds=rotation_interval_seconds)
        return datetime.utcnow() > rotation_time

class SessionManager:
    """
    Comprehensive session management with security features
    """
    
    def __init__(self, settings):
        self.settings = settings
        self.serializer = URLSafeTimedSerializer(settings.session_secret_key)
        self.cookie_name = settings.session_cookie_name
        self.max_age = settings.session_cookie_max_age
        self.secure = settings.session_cookie_secure
        self.httponly = settings.session_cookie_httponly
        self.samesite = settings.session_cookie_samesite
        self.domain = settings.session_cookie_domain or None
        
        # In-memory session store (in production, use Redis)
        self._sessions: Dict[str, SessionData] = {}
        
        logger.info(f"Session manager initialized with max_age={self.max_age}s")
    
    def generate_session_id(self) -> str:
        """Generate a cryptographically secure session ID"""
        return secrets.token_urlsafe(32)
    
    def create_session(self, user_id: int, username: str, role: str, **extra_data) -> str:
        """
        Create a new session
        
        Args:
            user_id: User ID
            username: Username
            role: User role
            **extra_data: Additional session data
            
        Returns:
            str: Session ID
        """
        session_id = self.generate_session_id()
        session_data = SessionData(
            user_id=user_id,
            username=username,
            role=role,
            **extra_data
        )
        
        self._sessions[session_id] = session_data
        logger.info(f"Created session {session_id} for user {username}")
        
        return session_id
    
    def get_session(self, session_id: str) -> Optional[SessionData]:
        """
        Get session data by session ID
        
        Args:
            session_id: Session ID
            
        Returns:
            Optional[SessionData]: Session data if valid, None otherwise
        """
        if not session_id or session_id not in self._sessions:
            return None
        
        session_data = self._sessions[session_id]
        
        # Check if session is expired
        if session_data.is_expired(self.max_age):
            logger.info(f"Session {session_id} expired, removing")
            del self._sessions[session_id]
            return None
        
        # Update access time
        session_data.update_access_time()
        
        return session_data
    
    def update_session(self, session_id: str, **update_data) -> bool:
        """
        Update session data
        
        Args:
            session_id: Session ID
            **update_data: Data to update
            
        Returns:
            bool: True if successful, False if session not found
        """
        session_data = self.get_session(session_id)
        if not session_data:
            return False
        
        session_data.data.update(update_data)
        session_data.update_access_time()
        
        return True
    
    def destroy_session(self, session_id: str) -> bool:
        """
        Destroy a session
        
        Args:
            session_id: Session ID
            
        Returns:
            bool: True if session was found and destroyed
        """
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.info(f"Destroyed session {session_id}")
            return True
        return False
    
    def rotate_session(self, old_session_id: str) -> Optional[str]:
        """
        Rotate session ID for security
        
        Args:
            old_session_id: Current session ID
            
        Returns:
            Optional[str]: New session ID if successful
        """
        session_data = self.get_session(old_session_id)
        if not session_data:
            return None
        
        # Create new session with same data
        new_session_id = self.generate_session_id()
        session_data.created_at = datetime.utcnow()  # Reset creation time
        session_data.update_access_time()
        
        self._sessions[new_session_id] = session_data
        del self._sessions[old_session_id]
        
        logger.info(f"Rotated session {old_session_id} to {new_session_id}")
        return new_session_id
    
    def cleanup_expired_sessions(self):
        """Clean up expired sessions"""
        current_time = datetime.utcnow()
        expired_sessions = []
        
        for session_id, session_data in self._sessions.items():
            if session_data.is_expired(self.max_age):
                expired_sessions.append(session_id)
        
        for session_id in expired_sessions:
            del self._sessions[session_id]
        
        if expired_sessions:
            logger.info(f"Cleaned up {len(expired_sessions)} expired sessions")
    
    def set_session_cookie(self, response: Response, session_id: str):
        """
        Set secure session cookie
        
        Args:
            response: FastAPI Response object
            session_id: Session ID to set
        """
        # Sign the session ID for additional security
        signed_session_id = self.serializer.dumps(session_id)
        
        response.set_cookie(
            key=self.cookie_name,
            value=signed_session_id,
            max_age=self.max_age,
            secure=self.secure,
            httponly=self.httponly,
            samesite=self.samesite,
            domain=self.domain,
            path="/"
        )
        
        logger.debug(f"Set session cookie for session {session_id}")
    
    def get_session_from_cookie(self, request: Request) -> Optional[SessionData]:
        """
        Get session data from cookie
        
        Args:
            request: FastAPI Request object
            
        Returns:
            Optional[SessionData]: Session data if valid
        """
        try:
            signed_session_id = request.cookies.get(self.cookie_name)
            if not signed_session_id:
                return None
            
            # Verify and unsign the session ID
            session_id = self.serializer.loads(
                signed_session_id, 
                max_age=self.max_age
            )
            
            return self.get_session(session_id)
            
        except (BadSignature, SignatureExpired) as e:
            logger.warning(f"Invalid session cookie: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error reading session cookie: {str(e)}")
            return None
    
    def clear_session_cookie(self, response: Response):
        """
        Clear session cookie
        
        Args:
            response: FastAPI Response object
        """
        response.delete_cookie(
            key=self.cookie_name,
            domain=self.domain,
            path="/"
        )
    
    def get_session_stats(self) -> Dict[str, Any]:
        """Get session statistics"""
        current_time = datetime.utcnow()
        active_sessions = 0
        expired_sessions = 0
        
        for session_data in self._sessions.values():
            if session_data.is_expired(self.max_age):
                expired_sessions += 1
            else:
                active_sessions += 1
        
        return {
            'total_sessions': len(self._sessions),
            'active_sessions': active_sessions,
            'expired_sessions': expired_sessions,
            'cleanup_needed': expired_sessions > 0
        }

# Global session manager instance
_session_manager: Optional[SessionManager] = None

def get_session_manager() -> SessionManager:
    """
    Get or create session manager instance
    
    Returns:
        SessionManager: Configured session manager
    """
    global _session_manager
    
    if _session_manager is None:
        settings = get_settings()
        _session_manager = SessionManager(settings)
    
    return _session_manager

def get_current_session(
    request: Request,
    session_manager: SessionManager = Depends(get_session_manager)
) -> Optional[SessionData]:
    """
    FastAPI dependency to get current session
    
    Args:
        request: FastAPI Request object
        session_manager: Session manager instance
        
    Returns:
        Optional[SessionData]: Current session data if valid
    """
    return session_manager.get_session_from_cookie(request)

def require_session(
    session_data: Optional[SessionData] = Depends(get_current_session)
) -> SessionData:
    """
    FastAPI dependency that requires a valid session
    
    Args:
        session_data: Session data from get_current_session
        
    Returns:
        SessionData: Valid session data
        
    Raises:
        HTTPException: If no valid session found
    """
    if not session_data:
        raise HTTPException(
            status_code=401,
            detail="Authentication required"
        )
    
    return session_data

def require_admin_session(
    session_data: SessionData = Depends(require_session)
) -> SessionData:
    """
    FastAPI dependency that requires an admin session
    
    Args:
        session_data: Session data from require_session
        
    Returns:
        SessionData: Valid admin session data
        
    Raises:
        HTTPException: If not an admin session
    """
    if not session_data.role or session_data.role not in ['SUPER_ADMIN', 'CLIENT_ADMIN']:
        raise HTTPException(
            status_code=403,
            detail="Admin access required"
        )
    
    return session_data