"""
OFX file parsing service.

This module handles parsing OFX files to extract transaction data,
account information, and file statistics.
"""

import os
from decimal import Decimal
from typing import List, Tuple, Dict, Any
from datetime import datetime
import ofxparse

from api.models.transaction import Transaction, Posting


class OFXParsingError(Exception):
    """Exception raised when OFX file cannot be parsed."""
    pass


class AccountInfo:
    """Container for OFX account information."""
    
    def __init__(self, institution: str, account_type: str, account_id: str, 
                 routing_number: str = "", currency: str = "USD"):
        self.institution = institution
        self.account_type = account_type
        self.account_id = account_id
        self.routing_number = routing_number
        self.currency = currency


class FileStats:
    """Container for OFX file statistics."""
    
    def __init__(self, transaction_count: int, start_date: str, end_date: str, 
                 balance: Decimal, currency: str):
        self.transaction_count = transaction_count
        self.start_date = start_date
        self.end_date = end_date
        self.balance = balance
        self.currency = currency


def parse_ofx_file(file_path: str) -> Tuple[List[Transaction], AccountInfo, FileStats]:
    """
    Parse an OFX file and extract transactions, account info, and statistics.
    
    Args:
        file_path: Path to the OFX file to parse
        
    Returns:
        Tuple of (transactions, account_info, file_stats)
        
    Raises:
        OFXParsingError: If file cannot be parsed or is invalid
        FileNotFoundError: If file doesn't exist
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"OFX file not found: {file_path}")
    
    try:
        with open(file_path, 'rb') as f:
            ofx_data = ofxparse.OfxParser.parse(f)
    except Exception as e:
        raise OFXParsingError(f"Failed to parse OFX file: {e}")
    
    if not ofx_data.accounts:
        raise OFXParsingError("No accounts found in OFX file")
    
    # Get the first (and typically only) account
    ofx_account = ofx_data.accounts[0]
    
    # Extract transactions
    transactions = extract_transactions(ofx_account)
    
    # Extract account information
    account_info = extract_account_info(ofx_account)
    
    # Calculate file statistics
    file_stats = calculate_file_stats(transactions, ofx_account)
    
    # Warn about large files
    if len(transactions) > 1000:
        print(f"Warning: Large OFX file detected with {len(transactions)} transactions")
    
    return transactions, account_info, file_stats


def extract_transactions(ofx_account) -> List[Transaction]:
    """
    Extract transaction data from an OFX account.
    
    Args:
        ofx_account: Parsed OFX account object
        
    Returns:
        List of Transaction objects
    """
    transactions = []
    
    if not hasattr(ofx_account, 'statement') or not ofx_account.statement:
        print("Debug: No statement found in OFX account")
        return transactions
    
    if not hasattr(ofx_account.statement, 'transactions'):
        print("Debug: No transactions attribute in statement")
        return transactions
    
    print(f"Debug: Found {len(ofx_account.statement.transactions)} transactions in OFX file")
    
    for ofx_transaction in ofx_account.statement.transactions:
        
        # Extract transaction data
        date_str = ofx_transaction.date.strftime('%Y-%m-%d') if ofx_transaction.date else ""
        payee = getattr(ofx_transaction, 'payee', '') or getattr(ofx_transaction, 'name', '') or 'Unknown'
        memo = getattr(ofx_transaction, 'memo', '') or ''
        amount = Decimal(str(ofx_transaction.amount)) if ofx_transaction.amount else Decimal('0')
        
        # Create unique transaction ID
        transaction_id = f"ofx_{hash(f'{date_str}_{payee}_{amount}_{memo}')}"
        
        # Create transaction with initial "Unknown" categorization
        transaction = Transaction(
            date=date_str,
            payee=payee.strip(),
            memo=memo.strip(),
            amount=amount,
            currency="USD",  # Default, will be updated from account info
            account="",  # Will be set from account mapping
            categorized_accounts=[],  # Will be populated during categorization
            narration="",  # User will add during review
            is_split=False,
            original_ofx_id=getattr(ofx_transaction, 'id', transaction_id)
        )
        
        transactions.append(transaction)
    
    return transactions


def extract_account_info(ofx_account) -> AccountInfo:
    """
    Extract account information from an OFX account.
    
    Args:
        ofx_account: Parsed OFX account object
        
    Returns:
        AccountInfo object
    """
    # Extract institution name
    institution = ""
    if hasattr(ofx_account, 'institution') and ofx_account.institution:
        institution = ofx_account.institution.organization or ""
    
    # Extract account details
    account_id = ""
    account_type = ""
    routing_number = ""
    
    if hasattr(ofx_account, 'account_id'):
        account_id = ofx_account.account_id or ""
    
    if hasattr(ofx_account, 'account_type'):
        account_type = ofx_account.account_type or ""
    
    if hasattr(ofx_account, 'routing_number'):
        routing_number = ofx_account.routing_number or ""
    
    # Default currency (OFX doesn't always specify)
    currency = "USD"
    if hasattr(ofx_account, 'statement') and ofx_account.statement:
        if hasattr(ofx_account.statement, 'currency'):
            currency = ofx_account.statement.currency or "USD"
    
    return AccountInfo(
        institution=institution.upper(),
        account_type=account_type.upper(),
        account_id=account_id,
        routing_number=routing_number,
        currency=currency.upper()
    )


def calculate_file_stats(transactions: List[Transaction], ofx_account) -> FileStats:
    """
    Calculate statistics for the OFX file.
    
    Args:
        transactions: List of parsed transactions
        ofx_account: Parsed OFX account object
        
    Returns:
        FileStats object
    """
    if not transactions:
        return FileStats(0, "", "", Decimal('0'), "USD")
    
    # Find date range
    dates = [t.date for t in transactions if t.date]
    start_date = min(dates) if dates else ""
    end_date = max(dates) if dates else ""
    
    # Get balance from account statement
    balance = Decimal('0')
    currency = "USD"
    
    if hasattr(ofx_account, 'statement') and ofx_account.statement:
        if hasattr(ofx_account.statement, 'balance'):
            balance = Decimal(str(ofx_account.statement.balance)) if ofx_account.statement.balance else Decimal('0')
        if hasattr(ofx_account.statement, 'currency'):
            currency = ofx_account.statement.currency or "USD"
    
    return FileStats(
        transaction_count=len(transactions),
        start_date=start_date,
        end_date=end_date,
        balance=balance,
        currency=currency.upper()
    )


def validate_ofx_file(file_path: str) -> List[str]:
    """
    Validate an OFX file and return list of validation errors.
    
    Args:
        file_path: Path to OFX file
        
    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []
    
    if not os.path.exists(file_path):
        errors.append(f"File not found: {file_path}")
        return errors
    
    try:
        with open(file_path, 'rb') as f:
            ofx_data = ofxparse.OfxParser.parse(f)
        
        if not ofx_data.accounts:
            errors.append("No accounts found in OFX file")
        
        # Check for transactions
        for account in ofx_data.accounts:
            if not hasattr(account, 'statement') or not account.statement:
                errors.append("Account has no statement data")
            elif not account.statement.transactions:
                errors.append("No transactions found in account statement")
    
    except Exception as e:
        errors.append(f"Failed to parse OFX file: {e}")
    
    return errors