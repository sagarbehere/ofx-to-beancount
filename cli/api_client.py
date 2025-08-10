"""
API client for communicating with the OFX to Beancount API server.

This module handles all HTTP communication between the CLI and the API server,
including session management and error handling.
"""

import requests
import time
from typing import Dict, List, Any, Optional
from decimal import Decimal
import json


class APIClientError(Exception):
    """Exception raised when API communication fails."""
    pass


class APIClient:
    """Client for communicating with the OFX to Beancount API server."""
    
    def __init__(self, base_url: str = "http://127.0.0.1:8000"):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.timeout = 30  # seconds
    
    def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """
        Make an HTTP request to the API server.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (without base URL)
            **kwargs: Additional arguments for requests
            
        Returns:
            Response JSON data
            
        Raises:
            APIClientError: If request fails or server returns error
        """
        url = f"{self.base_url}{endpoint}"
        
        try:
            response = self.session.request(
                method,
                url,
                timeout=self.timeout,
                **kwargs
            )
            
            # Check for HTTP errors
            if response.status_code >= 400:
                try:
                    error_data = response.json()
                    error_message = error_data.get('detail', f'HTTP {response.status_code}')
                except (ValueError, KeyError):
                    error_message = f'HTTP {response.status_code}: {response.text}'
                
                raise APIClientError(f"API request failed: {error_message}")
            
            # Parse JSON response
            try:
                return response.json()
            except ValueError as e:
                raise APIClientError(f"Invalid JSON response: {e}")
        
        except requests.exceptions.RequestException as e:
            raise APIClientError(f"Network error: {e}")
    
    def wait_for_server(self, max_attempts: int = 30, delay: float = 1.0) -> bool:
        """
        Wait for the API server to become available.
        
        Args:
            max_attempts: Maximum number of attempts
            delay: Delay between attempts in seconds
            
        Returns:
            True if server is available, False if timeout
        """
        for attempt in range(max_attempts):
            try:
                response = self.session.get(f"{self.base_url}/health", timeout=5)
                if response.status_code == 200:
                    return True
            except requests.exceptions.RequestException:
                pass
            
            if attempt < max_attempts - 1:
                time.sleep(delay)
        
        return False
    
    def initialize_session(self, ofx_file_path: str, config_file_path: str,
                          training_file_path: Optional[str] = None,
                          account_file_path: Optional[str] = None,
                          output_file_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Initialize a new processing session.
        
        Args:
            ofx_file_path: Path to OFX file
            config_file_path: Path to YAML configuration file
            training_file_path: Path to training file (optional)
            account_file_path: Path to accounts file (optional)  
            output_file_path: Path to output file (optional)
            
        Returns:
            Session initialization response
        """
        request_data = {
            "ofx_file_path": ofx_file_path,
            "config_file_path": config_file_path
        }
        
        if training_file_path:
            request_data["training_file_path"] = training_file_path
        if account_file_path:
            request_data["account_file_path"] = account_file_path
        if output_file_path:
            request_data["output_file_path"] = output_file_path
        
        return self._make_request("POST", "/session/initialize", json=request_data)
    
    def categorize_transactions(self, session_id: str, confirmed_account: str, 
                               confirmed_currency: str) -> Dict[str, Any]:
        """
        Get categorized transactions for a session.
        
        Args:
            session_id: Session identifier
            confirmed_account: User-confirmed source account
            confirmed_currency: User-confirmed currency
            
        Returns:
            Transaction categorization response
        """
        request_data = {
            "session_id": session_id,
            "confirmed_account": confirmed_account,
            "confirmed_currency": confirmed_currency
        }
        
        return self._make_request("POST", "/transactions/categorize", json=request_data)
    
    def update_transactions_batch(self, session_id: str, updates: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Update multiple transactions based on user input.
        
        Args:
            session_id: Session identifier
            updates: List of transaction updates
            
        Returns:
            Batch update response
        """
        request_data = {
            "session_id": session_id,
            "updates": updates
        }
        
        return self._make_request("POST", "/transactions/update-batch", json=request_data)
    
    def export_beancount(self, session_id: str, output_file_path: str, 
                        output_mode: str = "append") -> Dict[str, Any]:
        """
        Export transactions to Beancount format.
        
        Args:
            session_id: Session identifier
            output_file_path: Path to output file
            output_mode: Export mode ('append' or 'overwrite')
            
        Returns:
            Export response with summary
        """
        request_data = {
            "session_id": session_id,
            "output_file_path": output_file_path,
            "output_mode": output_mode
        }
        
        return self._make_request("POST", "/export/beancount", json=request_data)
    
    def get_session_status(self, session_id: str) -> Dict[str, Any]:
        """
        Get the current status of a session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Session status information
        """
        return self._make_request("GET", f"/session/status/{session_id}")
    
    def get_transaction_summary(self, session_id: str) -> Dict[str, Any]:
        """
        Get summary statistics for session transactions.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Transaction summary statistics
        """
        return self._make_request("GET", f"/transactions/{session_id}/summary")
    
    def preview_export(self, session_id: str, max_transactions: int = 5) -> Dict[str, Any]:
        """
        Preview Beancount export without writing to file.
        
        Args:
            session_id: Session identifier
            max_transactions: Maximum transactions to include in preview
            
        Returns:
            Export preview data
        """
        params = {"max_transactions": max_transactions}
        return self._make_request("GET", f"/export/preview/{session_id}", params=params)
    
    def validate_export_readiness(self, session_id: str) -> Dict[str, Any]:
        """
        Validate that a session is ready for export.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Validation results
        """
        return self._make_request("GET", f"/export/validate/{session_id}")
    
    def get_health_status(self) -> Dict[str, Any]:
        """
        Get API server health status.
        
        Returns:
            Health status information
        """
        return self._make_request("GET", "/health")
    
    def cleanup_expired_sessions(self) -> Dict[str, Any]:
        """
        Cleanup expired sessions (admin function).
        
        Returns:
            Cleanup results
        """
        return self._make_request("DELETE", "/session/cleanup")
    
    def confirm_degraded_functionality(self, session_id: str, confirmation_type: str, user_choice: str) -> Dict[str, Any]:
        """
        Send user confirmation for degraded functionality scenarios.
        
        Args:
            session_id: Session identifier
            confirmation_type: Type of confirmation (training_data_unavailable, accounts_unavailable)
            user_choice: User choice ('continue' or 'abort')
            
        Returns:
            Confirmation response
        """
        request_data = {
            "session_id": session_id,
            "confirmation_type": confirmation_type,
            "user_choice": user_choice
        }
        
        return self._make_request("POST", "/session/confirm", json=request_data)


def create_api_client(base_url: str = "http://127.0.0.1:8000") -> APIClient:
    """
    Create and configure an API client instance.
    
    Args:
        base_url: Base URL for the API server
        
    Returns:
        Configured APIClient instance
    """
    return APIClient(base_url)


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal objects."""
    
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)