"""
Duplicate detection service for identifying potential duplicate transactions.

This module compares new transactions against existing ones using
exact matches for date/amount/account and fuzzy matching for payees.
"""

import os
from typing import List, Tuple
from decimal import Decimal
from rapidfuzz import fuzz
from beancount import loader
from beancount.core import data
import re

from api.models.transaction import Transaction, DuplicateMatch


def extract_metadata_from_transaction(transaction_entry) -> dict:
    """
    Extract transaction_id and ofx_id metadata from Beancount transaction entry.
    
    NOTE: This metadata is extracted for reference purposes only.
    It is NOT used for duplicate detection logic.
    Duplicate detection continues to use date/payee/amount/account only.
    
    Args:
        transaction_entry: Beancount transaction entry object
        
    Returns:
        Dictionary with extracted metadata (transaction_id, ofx_id)
    """
    metadata = {}
    
    # Check if transaction has meta attribute
    if hasattr(transaction_entry, 'meta') and transaction_entry.meta:
        # Extract transaction_id (for reference only, not duplicate detection)
        if 'transaction_id' in transaction_entry.meta:
            metadata['transaction_id'] = transaction_entry.meta['transaction_id']
        
        # Extract ofx_id (for reference only, not duplicate detection)  
        if 'ofx_id' in transaction_entry.meta:
            metadata['ofx_id'] = transaction_entry.meta['ofx_id']
    
    return metadata


class DuplicateDetectionError(Exception):
    """Exception raised when duplicate detection fails."""
    pass


def detect_duplicates(new_transactions: List[Transaction], existing_file: str) -> List[DuplicateMatch]:
    """
    Detect potential duplicates between new transactions and existing file.
    
    Two transactions are considered duplicates if they match:
    - Date (exact match)
    - Source account (exact match)
    - Amount (exact match) 
    - Payee (fuzzy match > 90% similarity)
    
    Args:
        new_transactions: List of new transactions to check
        existing_file: Path to existing Beancount file
        
    Returns:
        List of DuplicateMatch objects for potential duplicates
    """
    if not new_transactions:
        return []
    
    if not existing_file or not os.path.exists(existing_file):
        return []  # No existing file to compare against
    
    try:
        existing_transactions = load_existing_transactions(existing_file)
        
        if not existing_transactions:
            return []
        
        duplicates = []
        
        for new_txn in new_transactions:
            for existing_txn in existing_transactions:
                match = _check_duplicate_match(new_txn, existing_txn)
                if match:
                    duplicates.append(match)
        
        return duplicates
    
    except Exception as e:
        raise DuplicateDetectionError(f"Failed to detect duplicates: {e}")


def _check_duplicate_match(new_txn: Transaction, existing_txn: Transaction) -> DuplicateMatch:
    """
    Check if two transactions are potential duplicates.
    
    Returns DuplicateMatch if they match, None otherwise.
    """
    match_criteria = []
    
    # Check date (exact match required)
    if new_txn.date == existing_txn.date:
        match_criteria.append("date")
    else:
        return None  # Date must match exactly
    
    # Check source account (exact match required) 
    if new_txn.account == existing_txn.account:
        match_criteria.append("account")
    else:
        return None  # Account must match exactly
    
    # Check amount (exact match required)
    if new_txn.amount == existing_txn.amount:
        match_criteria.append("amount")
    else:
        return None  # Amount must match exactly
    
    # Check payee similarity (fuzzy match > 90% required)
    payee_similarity = calculate_payee_similarity(new_txn.payee, existing_txn.payee)
    if payee_similarity > 0.9:
        match_criteria.append("payee")
        
        # All criteria met - this is a potential duplicate
        return DuplicateMatch(
            existing_transaction_id=existing_txn.transaction_id,
            similarity_score=payee_similarity,
            match_criteria=match_criteria,
            existing_transaction_date=existing_txn.date,
            existing_transaction_payee=existing_txn.payee,
            existing_transaction_amount=existing_txn.amount,
            # Add new transaction information
            new_transaction_date=new_txn.date,
            new_transaction_payee=new_txn.payee,
            new_transaction_amount=new_txn.amount
        )
    
    return None  # Not a duplicate


def calculate_payee_similarity(payee1: str, payee2: str) -> float:
    """
    Calculate similarity between two payee names using fuzzy matching.
    
    Args:
        payee1: First payee name
        payee2: Second payee name
        
    Returns:
        Similarity score between 0.0 and 1.0
    """
    if not payee1 or not payee2:
        return 0.0
    
    if payee1 == payee2:
        return 1.0
    
    # Use rapidfuzz for fuzzy string matching
    # Try multiple algorithms and take the best score
    ratio_score = fuzz.ratio(payee1.lower(), payee2.lower()) / 100.0
    partial_ratio_score = fuzz.partial_ratio(payee1.lower(), payee2.lower()) / 100.0
    token_sort_score = fuzz.token_sort_ratio(payee1.lower(), payee2.lower()) / 100.0
    token_set_score = fuzz.token_set_ratio(payee1.lower(), payee2.lower()) / 100.0
    
    # Return the highest score
    return max(ratio_score, partial_ratio_score, token_sort_score, token_set_score)


def load_existing_transactions(file_path: str) -> List[Transaction]:
    """
    Load existing transactions from a Beancount file.
    
    Args:
        file_path: Path to Beancount file
        
    Returns:
        List of Transaction objects
        
    Raises:
        FileNotFoundError: If file doesn't exist
        DuplicateDetectionError: If file cannot be parsed
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    
    try:
        entries, errors, options_map = loader.load_file(file_path)
        
        if errors:
            print(f"Warning: {len(errors)} parsing errors in existing file")
        
        transactions = []
        
        for entry in entries:
            if hasattr(entry, 'postings') and hasattr(entry, 'date'):
                # This is a transaction directive
                txn_date = entry.date.strftime('%Y-%m-%d')
                payee = getattr(entry, 'payee', '') or ''
                narration = getattr(entry, 'narration', '') or ''
                
                # Find the source account (typically asset or liability)
                source_account = ""
                transaction_amount = Decimal('0')
                currency = "USD"
                
                for posting in entry.postings:
                    if posting.units and posting.units.number:
                        # Look for asset or liability account as source
                        if posting.account.startswith(('Assets:', 'Liabilities:')):
                            source_account = posting.account
                            transaction_amount = posting.units.number  # Keep the actual sign
                            currency = posting.units.currency
                            break
                
                # Skip if no source account found
                if not source_account:
                    continue
                
                # Extract metadata for reference purposes only (NOT used for duplicate detection)
                metadata = extract_metadata_from_transaction(entry)
                
                # Create transaction for duplicate detection
                transaction = Transaction(
                    date=txn_date,
                    payee=payee,
                    memo=narration,
                    amount=transaction_amount,
                    currency=currency,
                    account=source_account,
                    categorized_accounts=[],
                    narration=narration,
                    is_split=len(entry.postings) > 2,
                    transaction_id=metadata.get('transaction_id', f"existing_{hash(f'{txn_date}_{payee}_{transaction_amount}')}"),
                    ofx_id=metadata.get('ofx_id'),
                    original_ofx_id=metadata.get('ofx_id', f"existing_{hash(f'{txn_date}_{payee}_{transaction_amount}')}")  # Keep for backwards compatibility
                )
                
                transactions.append(transaction)
        
        return transactions
    
    except Exception as e:
        raise DuplicateDetectionError(f"Failed to load existing transactions: {e}")


def filter_duplicates_by_confidence(duplicates: List[DuplicateMatch], min_confidence: float = 0.95) -> List[DuplicateMatch]:
    """
    Filter duplicate matches by confidence threshold.
    
    Args:
        duplicates: List of potential duplicates
        min_confidence: Minimum confidence threshold (0.0-1.0)
        
    Returns:
        Filtered list of high-confidence duplicates
    """
    return [dup for dup in duplicates if dup.similarity_score >= min_confidence]


def group_duplicates_by_transaction(duplicates: List[DuplicateMatch]) -> dict:
    """
    Group duplicate matches by new transaction for easier processing.
    
    Args:
        duplicates: List of duplicate matches
        
    Returns:
        Dictionary mapping transaction IDs to their duplicate matches
    """
    grouped = {}
    
    for duplicate in duplicates:
        # Note: This assumes we can identify the new transaction ID
        # In practice, this would need to be passed in or derived
        new_txn_id = duplicate.existing_transaction_id  # Placeholder
        
        if new_txn_id not in grouped:
            grouped[new_txn_id] = []
        
        grouped[new_txn_id].append(duplicate)
    
    return grouped


def get_duplicate_summary(duplicates: List[DuplicateMatch]) -> dict:
    """
    Generate a summary of duplicate detection results.
    
    Args:
        duplicates: List of duplicate matches
        
    Returns:
        Dictionary with duplicate summary statistics
    """
    if not duplicates:
        return {
            'total_duplicates': 0,
            'high_confidence_duplicates': 0,
            'average_similarity': 0.0
        }
    
    high_confidence_count = len(filter_duplicates_by_confidence(duplicates, 0.95))
    average_similarity = sum(dup.similarity_score for dup in duplicates) / len(duplicates)
    
    return {
        'total_duplicates': len(duplicates),
        'high_confidence_duplicates': high_confidence_count,
        'average_similarity': round(average_similarity, 3)
    }