"""
Session management service for handling processing sessions.

This module manages in-memory sessions throughout the OFX processing workflow,
including session creation, retrieval, updates, and cleanup.
"""

import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Any
import threading

from api.models.session import SessionData, create_session_id
from api.models.transaction import Transaction


class SessionManagerError(Exception):
    """Exception raised when session management fails."""
    pass


class SessionManager:
    """
    In-memory session manager for OFX processing sessions.
    
    Sessions are stored in memory only and will be lost on server restart.
    """
    
    def __init__(self, default_timeout_minutes: int = 60):
        self.sessions: Dict[str, SessionData] = {}
        self.default_timeout_minutes = default_timeout_minutes
        self._lock = threading.RLock()  # Thread-safe access
    
    def create_session(self, ofx_file_path: str, config_file_path: str, output_file_path: str,
                      training_file_path: Optional[str] = None,
                      account_file_path: Optional[str] = None) -> SessionData:
        """
        Create a new processing session.
        
        Args:
            ofx_file_path: Path to OFX file to process
            config_file_path: Path to YAML configuration file
            training_file_path: Path to training file (optional)
            account_file_path: Path to accounts file (optional)
            output_file_path: Path to output file
            
        Returns:
            Created SessionData object
        """
        with self._lock:
            session_data = SessionData(
                session_id=create_session_id(),
                created_at=datetime.now(),
                ofx_file_path=ofx_file_path,
                config_file_path=config_file_path,
                training_file_path=training_file_path,
                account_file_path=account_file_path,
                output_file_path=output_file_path
            )
            
            self.sessions[session_data.session_id] = session_data
            return session_data
    
    def get_session(self, session_id: str) -> SessionData:
        """
        Retrieve a session by ID.
        
        Args:
            session_id: Session identifier
            
        Returns:
            SessionData object
            
        Raises:
            SessionManagerError: If session not found or expired
        """
        with self._lock:
            if session_id not in self.sessions:
                raise SessionManagerError(f"Session not found: {session_id}")
            
            session = self.sessions[session_id]
            
            if session.is_expired(self.default_timeout_minutes):
                del self.sessions[session_id]
                raise SessionManagerError(f"Session expired: {session_id}")
            
            return session
    
    def update_session(self, session_id: str, **kwargs) -> None:
        """
        Update session data.
        
        Args:
            session_id: Session identifier
            **kwargs: Fields to update
            
        Raises:
            SessionManagerError: If session not found
        """
        with self._lock:
            session = self.get_session(session_id)  # This validates session exists
            
            # Update allowed fields
            allowed_fields = {
                'transactions', 'valid_accounts', 'classifier_model',
                'detected_account', 'detected_currency', 'training_data_count',
                'is_initialized', 'is_categorized'
            }
            
            for field, value in kwargs.items():
                if field in allowed_fields:
                    setattr(session, field, value)
    
    def delete_session(self, session_id: str) -> None:
        """
        Delete a session.
        
        Args:
            session_id: Session identifier to delete
        """
        with self._lock:
            if session_id in self.sessions:
                del self.sessions[session_id]
    
    def cleanup_expired_sessions(self) -> int:
        """
        Remove expired sessions from memory.
        
        Returns:
            Number of sessions cleaned up
        """
        with self._lock:
            expired_sessions = []
            
            for session_id, session in self.sessions.items():
                if session.is_expired(self.default_timeout_minutes):
                    expired_sessions.append(session_id)
            
            for session_id in expired_sessions:
                del self.sessions[session_id]
            
            return len(expired_sessions)
    
    def get_session_count(self) -> int:
        """Get the current number of active sessions."""
        with self._lock:
            return len(self.sessions)
    
    def get_session_stats(self) -> Dict[str, Any]:
        """
        Get statistics about current sessions.
        
        Returns:
            Dictionary with session statistics
        """
        with self._lock:
            stats = {
                'total_sessions': len(self.sessions),
                'initialized_sessions': 0,
                'categorized_sessions': 0,
                'oldest_session_age_minutes': 0
            }
            
            if self.sessions:
                now = datetime.now()
                oldest_age = timedelta(0)
                
                for session in self.sessions.values():
                    if session.is_initialized:
                        stats['initialized_sessions'] += 1
                    if session.is_categorized:
                        stats['categorized_sessions'] += 1
                    
                    age = now - session.created_at
                    if age > oldest_age:
                        oldest_age = age
                
                stats['oldest_session_age_minutes'] = int(oldest_age.total_seconds() / 60)
            
            return stats
    
    def validate_session_state(self, session_id: str, required_state: str) -> None:
        """
        Validate that a session is in the required state.
        
        Args:
            session_id: Session identifier
            required_state: Required state ('initialized' or 'categorized')
            
        Raises:
            SessionManagerError: If session not in required state
        """
        session = self.get_session(session_id)
        
        if required_state == 'initialized' and not session.is_initialized:
            raise SessionManagerError(f"Session {session_id} not initialized")
        
        if required_state == 'categorized' and not session.is_categorized:
            raise SessionManagerError(f"Session {session_id} not categorized")


# Global session manager instance
_session_manager = None
_manager_lock = threading.Lock()


def get_session_manager() -> SessionManager:
    """Get the global session manager instance (singleton)."""
    global _session_manager
    
    with _manager_lock:
        if _session_manager is None:
            _session_manager = SessionManager()
        return _session_manager


def cleanup_sessions_periodically() -> None:
    """
    Cleanup expired sessions periodically.
    This should be called by a background task.
    """
    manager = get_session_manager()
    cleaned_up = manager.cleanup_expired_sessions()
    if cleaned_up > 0:
        print(f"Cleaned up {cleaned_up} expired sessions")