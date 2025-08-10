"""
Session data models for managing processing sessions.

This module defines the data structures for managing user sessions
throughout the OFX processing workflow.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from decimal import Decimal
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
import uuid

from .transaction import Transaction, TransactionAPI, SystemMessage


@dataclass
class SessionData:
    """Core session data stored in memory."""
    session_id: str
    created_at: datetime
    ofx_file_path: str
    config_file_path: str
    training_file_path: Optional[str] = None
    account_file_path: Optional[str] = None
    output_file_path: Optional[str] = None
    
    # Processed data
    transactions: List[Transaction] = field(default_factory=list)
    valid_accounts: List[str] = field(default_factory=list)
    classifier_model: Optional[Any] = None
    detected_account: Optional[str] = None
    detected_currency: Optional[str] = None
    training_data_count: int = 0
    
    # Processing state
    is_initialized: bool = False
    is_categorized: bool = False
    
    def is_expired(self, timeout_minutes: int = 60) -> bool:
        """Check if session has expired."""
        return datetime.now() - self.created_at > timedelta(minutes=timeout_minutes)


# API Models for request/response
class SessionInitRequest(BaseModel):
    """Request model for session initialization."""
    ofx_file_path: str = Field(..., description="Path to OFX file to process")
    config_file_path: str = Field(..., description="Path to YAML configuration file")
    training_file_path: Optional[str] = Field(None, description="Path to Beancount training file")
    account_file_path: Optional[str] = Field(None, description="Path to Beancount accounts file")
    output_file_path: Optional[str] = Field(None, description="Path to output Beancount file")


class OFXStats(BaseModel):
    """OFX file statistics."""
    transaction_count: int = Field(..., description="Number of transactions in file")
    date_range: Dict[str, str] = Field(..., description="Start and end dates")
    balance: Decimal = Field(..., description="Account balance")
    currency: str = Field(..., description="Primary currency")
    
    class Config:
        json_encoders = {
            Decimal: lambda v: float(v)
        }


class DetectedAccount(BaseModel):
    """Detected account information."""
    account: str = Field(..., description="Detected Beancount account name")
    currency: str = Field(..., description="Detected currency")
    confidence: float = Field(..., description="Confidence in detection (0.0-1.0)")


class ConfirmationRequired(BaseModel):
    """Response when user confirmation is required to continue."""
    response_type: str = Field(default="confirmation_required", description="Response type indicator")
    confirmation_message: str = Field(..., description="Message to display to user") 
    confirmation_type: str = Field(..., description="Type of confirmation: training_data_unavailable, accounts_unavailable")
    fallback_account: Optional[str] = Field(None, description="Fallback account that will be used")
    system_messages: List[SystemMessage] = Field(default_factory=list, description="Additional system messages")


class SessionInitResponse(BaseModel):
    """Response model for session initialization - may require confirmation."""
    session_id: str = Field(..., description="Unique session identifier")
    ofx_stats: Optional[OFXStats] = Field(None, description="OFX file statistics")
    detected_account: Optional[DetectedAccount] = Field(None, description="Detected account information")
    valid_accounts: List[str] = Field(default_factory=list, description="List of valid account names")
    classifier_trained: bool = Field(False, description="Whether ML classifier was trained")
    training_data_count: int = Field(0, description="Number of training transactions used")
    system_messages: List[SystemMessage] = Field(default_factory=list, description="System warnings and errors")
    
    # New fields for confirmation workflow
    requires_confirmation: bool = Field(False, description="Whether user confirmation is required")
    confirmation_details: Optional[ConfirmationRequired] = Field(None, description="Confirmation details if required")


class TransactionCategorizeRequest(BaseModel):
    """Request model for transaction categorization."""
    session_id: str = Field(..., description="Session identifier")
    confirmed_account: str = Field(..., description="User-confirmed source account")
    confirmed_currency: str = Field(..., description="User-confirmed currency")


class TransactionCategorizeResponse(BaseModel):
    """Response model for transaction categorization."""
    transactions: List[TransactionAPI] = Field(..., description="Categorized transactions")
    total_count: int = Field(..., description="Total number of transactions")
    high_confidence_count: int = Field(..., description="Number of high-confidence categorizations")
    duplicate_count: int = Field(..., description="Number of potential duplicates detected")
    system_messages: List[SystemMessage] = Field(default_factory=list, description="System warnings and errors")


class TransactionUpdateBatchRequest(BaseModel):
    """Request model for batch transaction updates."""
    session_id: str = Field(..., description="Session identifier")
    updates: List[Any] = Field(..., description="List of transaction updates")  # TransactionUpdateAPI


class TransactionUpdateBatchResponse(BaseModel):
    """Response model for batch transaction updates."""
    updated_count: int = Field(..., description="Number of transactions updated")
    skipped_count: int = Field(..., description="Number of transactions skipped")
    split_count: int = Field(..., description="Number of transactions split")
    validation_errors: List[Any] = Field(..., description="List of validation errors")  # ValidationError
    system_messages: List[SystemMessage] = Field(default_factory=list, description="System warnings and errors")


class ExportBeancountRequest(BaseModel):
    """Request model for Beancount export."""
    session_id: str = Field(..., description="Session identifier")
    output_mode: str = Field("append", description="Output mode: 'append' or 'overwrite'")
    output_file_path: str = Field(..., description="Path to output file")


class ExportSummary(BaseModel):
    """Export summary statistics."""
    total_amount: Decimal = Field(..., description="Total transaction amount")
    currency: str = Field(..., description="Primary currency")
    categories: Dict[str, Decimal] = Field(..., description="Amount by category")
    date_range: Dict[str, str] = Field(..., description="Date range of transactions")
    
    class Config:
        json_encoders = {
            Decimal: lambda v: float(v)
        }


class ExportBeancountResponse(BaseModel):
    """Response model for Beancount export."""
    transactions_exported: int = Field(..., description="Number of transactions exported")
    file_path: str = Field(..., description="Path to output file")
    summary: ExportSummary = Field(..., description="Export summary statistics")
    beancount_preview: str = Field(..., description="Preview of generated Beancount content")
    system_messages: List[SystemMessage] = Field(default_factory=list, description="System warnings and errors")


class SessionConfirmRequest(BaseModel):
    """Request model for session confirmation."""
    session_id: str = Field(..., description="Session identifier")
    confirmation_type: str = Field(..., description="Type of confirmation")
    user_choice: str = Field(..., description="User choice: continue or abort")


class SessionConfirmResponse(BaseModel):
    """Response model for session confirmation."""
    session_id: str = Field(..., description="Session identifier")
    processing_continues: bool = Field(..., description="Whether processing can continue")
    system_messages: List[SystemMessage] = Field(default_factory=list, description="System messages")


# Session management helper functions
def create_session_id() -> str:
    """Generate a unique session ID."""
    return str(uuid.uuid4())


def create_session_data(init_request: SessionInitRequest) -> SessionData:
    """Create a new session data object."""
    return SessionData(
        session_id=create_session_id(),
        created_at=datetime.now(),
        ofx_file_path=init_request.ofx_file_path,
        config_file_path=init_request.config_file_path,
        training_file_path=init_request.training_file_path,
        account_file_path=init_request.account_file_path,
        output_file_path=init_request.output_file_path
    )