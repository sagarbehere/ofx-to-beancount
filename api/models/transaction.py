"""
Transaction data models for the OFX to Beancount converter.

This module defines the core data structures for handling financial transactions,
postings, and related metadata throughout the processing pipeline.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, Field, validator
from datetime import date


@dataclass
class Posting:
    """Represents a single posting within a transaction."""
    account: str
    amount: Decimal
    currency: str
    
    def __post_init__(self):
        """Ensure amount is a Decimal type."""
        if not isinstance(self.amount, Decimal):
            self.amount = Decimal(str(self.amount))


@dataclass  
class Transaction:
    """Represents a financial transaction with all associated data."""
    date: str  # ISO format YYYY-MM-DD
    payee: str
    memo: str
    amount: Decimal
    currency: str
    account: str  # Source account (from OFX)
    categorized_accounts: List[Posting]  # Target accounts
    narration: str  # User-entered note (clean, without ID)
    transaction_id: str  # SHA256 hash of immutable fields
    ofx_id: Optional[str]  # Original OFX transaction ID (when available)
    is_split: bool
    # DEPRECATED: Use ofx_id instead
    original_ofx_id: str
    
    def __post_init__(self):
        """Ensure amount is a Decimal type."""
        if not isinstance(self.amount, Decimal):
            self.amount = Decimal(str(self.amount))


# Pydantic models for API serialization
class PostingAPI(BaseModel):
    """API model for transaction postings."""
    account: str = Field(..., description="Beancount account name")
    amount: Decimal = Field(..., description="Posting amount")
    currency: str = Field(..., description="Currency code")
    
    class Config:
        json_encoders = {
            Decimal: lambda v: float(v)
        }


class TransactionAPI(BaseModel):
    """API model for transactions."""
    id: str = Field(..., description="Unique transaction identifier")
    date: str = Field(..., description="Transaction date in YYYY-MM-DD format")
    payee: str = Field(..., description="Transaction payee/merchant")
    memo: str = Field(..., description="Transaction memo/description")
    amount: Decimal = Field(..., description="Transaction amount")
    currency: str = Field(..., description="Currency code")
    suggested_category: Optional[str] = Field(None, description="ML suggested account category")
    confidence: Optional[float] = Field(None, description="ML confidence score (0.0-1.0)")
    is_potential_duplicate: bool = Field(False, description="Whether transaction might be a duplicate")
    duplicate_details: Optional['DuplicateMatch'] = Field(None, description="Details about potential duplicate match")
    narration: Optional[str] = Field("", description="User-entered narration (clean, without ID)")
    transaction_id: str = Field(..., description="SHA256 hash of immutable fields")
    ofx_id: Optional[str] = Field(None, description="Original OFX transaction ID (when available)")
    splits: Optional[List[PostingAPI]] = Field(None, description="Split postings if transaction is split")
    
    @validator('date')
    def validate_date_format(cls, v):
        """Validate date is in correct ISO format."""
        try:
            date.fromisoformat(v)
            return v
        except ValueError:
            raise ValueError('Date must be in YYYY-MM-DD format')
    
    @validator('confidence')
    def validate_confidence(cls, v):
        """Validate confidence is between 0 and 1."""
        if v is not None and (v < 0.0 or v > 1.0):
            raise ValueError('Confidence must be between 0.0 and 1.0')
        return v
    
    class Config:
        json_encoders = {
            Decimal: lambda v: float(v)
        }


class TransactionUpdateAPI(BaseModel):
    """API model for transaction updates from user interaction."""
    transaction_id: str = Field(..., description="Transaction ID to update")
    confirmed_category: Optional[str] = Field(None, description="User-confirmed account category")
    narration: Optional[str] = Field("", description="User-entered narration (clean, without ID)")
    ofx_id: Optional[str] = Field(None, description="Preserve original OFX ID (read-only)")
    splits: Optional[List[PostingAPI]] = Field(None, description="Split postings for multi-category transactions")
    action: Optional[str] = Field(None, description="Special action: 'skip' for duplicates")
    reason: Optional[str] = Field(None, description="Reason for action (e.g., 'duplicate')")


class DuplicateMatch(BaseModel):
    """Information about potential duplicate transactions."""
    existing_transaction_id: str = Field(..., description="ID of existing transaction")
    similarity_score: float = Field(..., description="Similarity score (0.0-1.0)")
    match_criteria: List[str] = Field(..., description="Which criteria matched (date, amount, account, payee)")
    existing_transaction_date: str = Field(..., description="Date of existing transaction")
    existing_transaction_payee: str = Field(..., description="Payee of existing transaction")
    existing_transaction_amount: Decimal = Field(..., description="Amount of existing transaction")
    # New fields to identify the matching new transaction
    new_transaction_date: str = Field(..., description="Date of new transaction that matched")
    new_transaction_payee: str = Field(..., description="Payee of new transaction that matched")
    new_transaction_amount: Decimal = Field(..., description="Amount of new transaction that matched")
    
    class Config:
        json_encoders = {
            Decimal: lambda v: float(v)
        }


class SystemMessage(BaseModel):
    """System message for warnings and errors."""
    level: str = Field(..., description="Message level: info, warning, error")
    message: str = Field(..., description="Human-readable message")


class ValidationError(BaseModel):
    """Represents a transaction validation error."""
    transaction_id: str = Field(..., description="Transaction ID with error")
    error: str = Field(..., description="Error message")
    details: Optional[str] = Field(None, description="Additional error details")


# Update forward references
TransactionAPI.model_rebuild()