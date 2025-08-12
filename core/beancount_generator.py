"""
Beancount output generation service.

This module handles generating valid Beancount transaction format from
processed transactions, including validation and file output.
"""

import os
from decimal import Decimal
from typing import List, Dict, Any
from datetime import datetime

from api.models.transaction import Transaction, Posting


def _combine_payee_and_memo(payee: str, memo: str) -> str:
    """
    Simply combine payee and memo into a single payee field.
    
    Args:
        payee: Original payee field from OFX
        memo: Original memo field from OFX
        
    Returns:
        Combined payee string: "payee memo"
    """
    if not payee and not memo:
        return "Unknown"
    
    if not payee:
        return memo.strip()
    
    if not memo:
        return payee.strip()
    
    # Simply combine payee + memo with a space
    return f"{payee.strip()} {memo.strip()}"


class BeancountGenerationError(Exception):
    """Exception raised when Beancount generation fails."""
    pass


class ValidationError(Exception):
    """Exception raised when transaction validation fails."""
    pass


def generate_beancount_transaction(transaction: Transaction) -> str:
    """
    Generate a single Beancount transaction from Transaction object.
    
    Args:
        transaction: Transaction to convert to Beancount format
        
    Returns:
        String containing properly formatted Beancount transaction
        
    Raises:
        BeancountGenerationError: If transaction cannot be converted
    """
    try:
        # Validate transaction first
        validation_errors = validate_transaction(transaction)
        if validation_errors:
            raise BeancountGenerationError(f"Transaction validation failed: {validation_errors}")
        
        lines = []
        
        # Determine transaction flag
        flag = "*"  # Default to cleared
        if len(set(posting.currency for posting in transaction.categorized_accounts)) > 1:
            flag = "!"  # Multi-currency transaction
        
        # Build transaction header with improved payee/narration logic
        # Combine payee and memo into payee field for better merchant identification
        combined_payee = _combine_payee_and_memo(transaction.payee, transaction.memo)
        header = f'{transaction.date} {flag} "{combined_payee}"'
        
        # Use narration field only for user-entered notes (clean, no ID embedding)
        if transaction.narration and transaction.narration.strip():
            # User provided a custom note - use it clean
            header += f' "{transaction.narration}"'
        else:
            # No user note - use empty narration
            header += ' ""'
        
        lines.append(header)
        
        # Add dual metadata (transaction_id always, ofx_id conditionally)
        lines.append(f'  transaction_id: "{transaction.transaction_id}"')
        
        # Add ofx_id metadata only if available and valid
        if transaction.ofx_id:
            lines.append(f'  ofx_id: "{transaction.ofx_id}"')
        
        # Add postings
        if transaction.is_split and transaction.categorized_accounts:
            # Multi-posting transaction
            for posting in transaction.categorized_accounts:
                amount_str = f"{posting.amount:0.2f} {posting.currency}"
                lines.append(f"  {posting.account:<50} {amount_str}")
            
            # Add balancing posting for source account
            source_amount = -sum(posting.amount for posting in transaction.categorized_accounts)
            amount_str = f"{source_amount:0.2f} {transaction.currency}"
            lines.append(f"  {transaction.account:<50} {amount_str}")
        
        else:
            # Simple two-posting transaction
            target_account = "Expenses:Unknown"
            if transaction.categorized_accounts:
                target_account = transaction.categorized_accounts[0].account
            
            # Preserve original OFX transaction signs
            # The target account gets the negation of the original amount
            target_amount = -transaction.amount
            source_amount = transaction.amount
            
            # Add target posting
            amount_str = f"{target_amount:0.2f} {transaction.currency}"
            lines.append(f"  {target_account:<50} {amount_str}")
            
            # Add source posting
            amount_str = f"{source_amount:0.2f} {transaction.currency}"
            lines.append(f"  {transaction.account:<50} {amount_str}")
        
        return "\n".join(lines) + "\n"
    
    except Exception as e:
        raise BeancountGenerationError(f"Failed to generate Beancount transaction: {e}")


def validate_postings_balance(postings: List[Posting]) -> bool:
    """
    Validate that postings balance to zero.
    
    Args:
        postings: List of postings to validate
        
    Returns:
        True if postings balance, False otherwise
    """
    if not postings:
        return False
    
    # Group by currency
    currency_totals = {}
    for posting in postings:
        currency = posting.currency
        if currency not in currency_totals:
            currency_totals[currency] = Decimal('0')
        currency_totals[currency] += posting.amount
    
    # Check if each currency balances (within tolerance)
    tolerance = Decimal('0.01')  # 1 cent tolerance
    for currency, total in currency_totals.items():
        if abs(total) > tolerance:
            return False
    
    return True


def validate_transaction(transaction: Transaction) -> List[str]:
    """
    Validate a transaction for Beancount compatibility.
    
    Args:
        transaction: Transaction to validate
        
    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []
    
    # Validate date format
    try:
        datetime.strptime(transaction.date, '%Y-%m-%d')
    except ValueError:
        errors.append(f"Invalid date format: {transaction.date}")
    
    # Validate required fields
    if not transaction.payee:
        errors.append("Transaction missing payee")
    
    if not transaction.account:
        errors.append("Transaction missing source account")
    
    if not transaction.currency:
        errors.append("Transaction missing currency")
    
    # Validate account names
    if not _is_valid_account_name(transaction.account):
        errors.append(f"Invalid source account name: {transaction.account}")
    
    for posting in transaction.categorized_accounts:
        if not _is_valid_account_name(posting.account):
            errors.append(f"Invalid posting account name: {posting.account}")
    
    # Validate posting balance for split transactions
    if transaction.is_split and transaction.categorized_accounts:
        all_postings = transaction.categorized_accounts.copy()
        
        # Add source account posting
        source_amount = -sum(p.amount for p in transaction.categorized_accounts)
        source_posting = Posting(
            account=transaction.account,
            amount=source_amount,
            currency=transaction.currency
        )
        all_postings.append(source_posting)
        
        if not validate_postings_balance(all_postings):
            errors.append("Split transaction postings do not balance")
    
    return errors


def _is_valid_account_name(account_name: str) -> bool:
    """Validate Beancount account name format."""
    if not account_name:
        return False
    
    parts = account_name.split(':')
    if len(parts) < 2:
        return False
    
    valid_root_types = ['Assets', 'Liabilities', 'Equity', 'Income', 'Expenses']
    if parts[0] not in valid_root_types:
        return False
    
    # Check that all parts are valid identifiers
    for part in parts:
        if not part or not part.replace('-', '').replace('_', '').isalnum():
            return False
    
    return True


def format_beancount_output(transactions: List[Transaction]) -> str:
    """
    Format multiple transactions into Beancount output.
    
    Args:
        transactions: List of transactions to format
        
    Returns:
        Complete Beancount-formatted string
        
    Raises:
        BeancountGenerationError: If any transaction cannot be formatted
    """
    if not transactions:
        return ""
    
    lines = []
    lines.append(f"; Generated by OFX to Beancount converter on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    
    # Sort transactions by date
    sorted_transactions = sorted(transactions, key=lambda t: t.date)
    
    for transaction in sorted_transactions:
        transaction_text = generate_beancount_transaction(transaction)
        lines.append(transaction_text)
    
    return "\n".join(lines)


def append_to_beancount_file(content: str, file_path: str) -> None:
    """
    Append content to a Beancount file.
    
    Args:
        content: Beancount-formatted content to append
        file_path: Path to output file
        
    Raises:
        BeancountGenerationError: If file cannot be written
    """
    try:
        # Create directory if it doesn't exist
        directory = os.path.dirname(file_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)
        
        # Append to file
        with open(file_path, 'a', encoding='utf-8') as f:
            if os.path.getsize(file_path) > 0:
                f.write("\n")  # Add separator if file not empty
            f.write(content)
    
    except Exception as e:
        raise BeancountGenerationError(f"Failed to write to file {file_path}: {e}")


def write_to_beancount_file(content: str, file_path: str) -> None:
    """
    Write content to a Beancount file (overwrite mode).
    
    Args:
        content: Beancount-formatted content to write
        file_path: Path to output file
        
    Raises:
        BeancountGenerationError: If file cannot be written
    """
    try:
        # Create directory if it doesn't exist
        directory = os.path.dirname(file_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)
        
        # Write to file
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
    
    except Exception as e:
        raise BeancountGenerationError(f"Failed to write to file {file_path}: {e}")


def generate_export_summary(transactions: List[Transaction]) -> Dict[str, Any]:
    """
    Generate summary statistics for exported transactions.
    
    Args:
        transactions: List of transactions being exported
        
    Returns:
        Dictionary with export summary statistics
    """
    if not transactions:
        return {
            'total_amount': Decimal('0'),
            'currency': 'USD',
            'categories': {},
            'date_range': {'start': '', 'end': ''}
        }
    
    # Calculate totals by category
    category_totals = {}
    total_amount = Decimal('0')
    currencies = set()
    dates = []
    
    for transaction in transactions:
        currencies.add(transaction.currency)
        dates.append(transaction.date)
        
        if transaction.categorized_accounts:
            for posting in transaction.categorized_accounts:
                category = posting.account
                if category not in category_totals:
                    category_totals[category] = Decimal('0')
                category_totals[category] += abs(posting.amount)
                total_amount += abs(posting.amount)
        else:
            total_amount += abs(transaction.amount)
    
    # Get date range
    dates.sort()
    start_date = dates[0] if dates else ''
    end_date = dates[-1] if dates else ''
    
    # Primary currency (most common)
    primary_currency = max(currencies, key=lambda c: sum(1 for t in transactions if t.currency == c)) if currencies else 'USD'
    
    return {
        'total_amount': total_amount,
        'currency': primary_currency,
        'categories': category_totals,
        'date_range': {'start': start_date, 'end': end_date}
    }


def preview_beancount_output(transactions: List[Transaction], max_transactions: int = 3) -> str:
    """
    Generate a preview of Beancount output (first few transactions).
    
    Args:
        transactions: List of transactions to preview
        max_transactions: Maximum number of transactions to include
        
    Returns:
        Preview string of formatted Beancount content with dual metadata
    """
    if not transactions:
        return ""
    
    preview_transactions = transactions[:max_transactions]
    preview_content = format_beancount_output(preview_transactions)
    
    if len(transactions) > max_transactions:
        preview_content += f"\n; ... and {len(transactions) - max_transactions} more transactions"
    
    return preview_content