"""
Conversion functions between API models and Beancount objects.

This module provides the bridge between the generic JSON-based API models
and the standard Beancount transaction objects. This ensures that all
transaction_id generation happens with consistent Beancount objects while
keeping the API layer framework-agnostic.
"""

from typing import List
from decimal import Decimal
from datetime import datetime

# Import Beancount data structures
from beancount.core.data import Transaction as BeancountTransaction, Posting as BeancountPosting, Amount
from beancount.core.number import D

# Import API models
from api.models.transaction import Transaction, Posting


def api_transaction_to_beancount(api_txn: Transaction, source_account: str) -> BeancountTransaction:
    """
    Convert API Transaction object to standard Beancount Transaction object.
    
    This function creates a proper Beancount transaction that can be used
    with transaction_id generation and other Beancount processing.
    
    Args:
        api_txn: API Transaction object (from OFX parser or user input)
        source_account: The source account name (e.g., "Liabilities:CreditCard")
        
    Returns:
        beancount.core.data.Transaction object
        
    Example:
        >>> api_txn = Transaction(date="2024-01-15", payee="STORE", ...)
        >>> bc_txn = api_transaction_to_beancount(api_txn, "Liabilities:CreditCard")
        >>> print(bc_txn.meta['transaction_id'])
    """
    # Parse date
    if isinstance(api_txn.date, str):
        date_obj = datetime.strptime(api_txn.date, '%Y-%m-%d').date()
    else:
        date_obj = api_txn.date
    
    # Create postings from categorized accounts or default structure
    postings = []
    
    if api_txn.categorized_accounts and not api_txn.is_split:
        # Single categorization
        target_account = api_txn.categorized_accounts[0].account
        target_amount = api_txn.categorized_accounts[0].amount
        target_currency = api_txn.categorized_accounts[0].currency
        
        # Target posting (expense/income account)
        postings.append(BeancountPosting(
            account=target_account,
            units=Amount(D(str(target_amount)), target_currency),
            cost=None,
            price=None,
            flag=None,
            meta=None
        ))
        
        # Source posting (balancing entry)
        source_amount = -target_amount
        postings.append(BeancountPosting(
            account=source_account,
            units=Amount(D(str(source_amount)), target_currency),
            cost=None,
            price=None,
            flag=None,
            meta=None
        ))
        
    elif api_txn.categorized_accounts and api_txn.is_split:
        # Split transaction - multiple target accounts
        total_target_amount = D('0')
        
        for posting in api_txn.categorized_accounts:
            postings.append(BeancountPosting(
                account=posting.account,
                units=Amount(D(str(posting.amount)), posting.currency),
                cost=None,
                price=None,
                flag=None,
                meta=None
            ))
            total_target_amount += D(str(posting.amount))
        
        # Add balancing source posting
        postings.append(BeancountPosting(
            account=source_account,
            units=Amount(-total_target_amount, api_txn.currency),
            cost=None,
            price=None,
            flag=None,
            meta=None
        ))
        
    else:
        # Uncategorized transaction - create default structure
        # For uncategorized, we create a simple two-posting structure
        amount = D(str(api_txn.amount))
        
        if amount > 0:
            # Positive amount (income or deposit)
            target_account = "Income:Unknown"
            target_amount = amount
            source_amount = -amount
        else:
            # Negative amount (expense or withdrawal)
            target_account = "Expenses:Unknown" 
            target_amount = -amount  # Make expense positive
            source_amount = amount   # Keep source negative
        
        postings.append(BeancountPosting(
            account=target_account,
            units=Amount(target_amount, api_txn.currency),
            cost=None,
            price=None,
            flag=None,
            meta=None
        ))
        
        postings.append(BeancountPosting(
            account=source_account,
            units=Amount(source_amount, api_txn.currency),
            cost=None,
            price=None,
            flag=None,
            meta=None
        ))
    
    # Prepare metadata
    meta = {}
    
    # Add source_account metadata for transaction_id consistency
    if source_account:
        meta['source_account'] = source_account
    
    # Add existing transaction_id if present
    if api_txn.transaction_id:
        meta['transaction_id'] = api_txn.transaction_id
    
    # Add OFX ID if present
    if api_txn.ofx_id:
        meta['ofx_id'] = api_txn.ofx_id
    
    # Add processing metadata (will be cleaned up before final output)
    meta.update({
        'api_memo': api_txn.memo,           # Original memo from OFX
        'api_amount': str(api_txn.amount),  # Original amount for reference
        'is_categorized': bool(api_txn.categorized_accounts),
        'is_split': api_txn.is_split
    })
    
    # Create Beancount transaction
    return BeancountTransaction(
        meta=meta,
        date=date_obj,
        flag='*',  # Default flag for completed transactions
        payee=api_txn.payee,
        narration=api_txn.narration,
        tags=frozenset(),
        links=frozenset(),
        postings=postings
    )


def beancount_to_api_transaction(bc_txn: BeancountTransaction) -> Transaction:
    """
    Convert Beancount Transaction object back to API Transaction object.
    
    This is used when we need to send transaction data back to the API layer
    after processing with Beancount objects.
    
    Args:
        bc_txn: beancount.core.data.Transaction object
        
    Returns:
        API Transaction object
    """
    # Extract metadata
    meta = bc_txn.meta or {}
    
    # Extract source account and original amount
    source_account = meta.get('source_account', '')
    original_amount_str = meta.get('api_amount', '0')
    original_amount = Decimal(original_amount_str)
    
    # Find categorized accounts (exclude the source account)
    categorized_accounts = []
    for posting in bc_txn.postings:
        if posting.account != source_account and posting.units:
            categorized_accounts.append(Posting(
                account=posting.account,
                amount=posting.units.number,
                currency=posting.units.currency
            ))
    
    # Determine if this is a split transaction
    is_split = len(categorized_accounts) > 1
    
    return Transaction(
        date=bc_txn.date.strftime('%Y-%m-%d'),
        payee=bc_txn.payee or '',
        memo=meta.get('api_memo', ''),
        amount=original_amount,
        currency=bc_txn.postings[0].units.currency if bc_txn.postings else 'USD',
        account=source_account,
        categorized_accounts=categorized_accounts,
        narration=bc_txn.narration or '',
        transaction_id=meta.get('transaction_id', ''),
        ofx_id=meta.get('ofx_id'),
        is_split=is_split,
        original_ofx_id=meta.get('ofx_id', '')  # For backward compatibility
    )


def create_beancount_transaction_from_api(api_txn: Transaction, source_account: str, id_generator=None) -> BeancountTransaction:
    """
    Create a Beancount transaction from API data with transaction_id generated.
    
    This is a convenience function that converts API data to Beancount format
    and generates the transaction_id in one step.
    
    Args:
        api_txn: API Transaction object
        source_account: The source account name
        id_generator: Optional TransactionIdGenerator instance for collision tracking
        
    Returns:
        Beancount transaction with transaction_id metadata
    """
    from shared_libs.transaction_id_generator import add_transaction_id_to_beancount_transaction
    
    # Convert to Beancount format
    bc_txn = api_transaction_to_beancount(api_txn, source_account)
    
    # Generate transaction_id
    bc_txn_with_id = add_transaction_id_to_beancount_transaction(
        transaction=bc_txn,
        strict_validation=True,
        id_generator=id_generator
    )
    
    return bc_txn_with_id


def batch_convert_api_to_beancount(api_transactions: List[Transaction], source_account: str) -> List[BeancountTransaction]:
    """
    Convert a batch of API transactions to Beancount transactions with transaction_ids.
    
    Args:
        api_transactions: List of API Transaction objects
        source_account: The source account name for all transactions
        
    Returns:
        List of Beancount transactions with transaction_ids
    """
    from shared_libs.transaction_id_generator import TransactionIdGenerator
    
    # Use a single generator instance for collision tracking
    id_generator = TransactionIdGenerator()
    
    beancount_transactions = []
    
    for api_txn in api_transactions:
        # Convert to Beancount format
        bc_txn = api_transaction_to_beancount(api_txn, source_account)
        
        # Generate transaction_id with collision tracking
        from shared_libs.transaction_id_generator import add_transaction_id_to_beancount_transaction
        bc_txn_with_id = add_transaction_id_to_beancount_transaction(
            transaction=bc_txn,
            strict_validation=True,
            id_generator=id_generator
        )
        
        beancount_transactions.append(bc_txn_with_id)
    
    return beancount_transactions


def clean_internal_metadata_for_output(beancount_transactions: List[BeancountTransaction]) -> List[BeancountTransaction]:
    """
    Remove internal processing metadata attributes from transactions before final output.
    
    This function removes metadata that was useful during processing but shouldn't
    appear in the final Beancount file output.
    
    Args:
        beancount_transactions: List of Beancount transactions with internal metadata
        
    Returns:
        List of Beancount transactions with clean metadata for output
    """
    # Metadata attributes to remove from final output
    internal_metadata_keys = {'api_memo', 'api_amount', 'is_categorized', 'is_split'}
    
    cleaned_transactions = []
    
    for txn in beancount_transactions:
        if not txn.meta:
            # No metadata to clean
            cleaned_transactions.append(txn)
            continue
        
        # Create clean metadata by excluding internal processing attributes
        clean_meta = {
            key: value for key, value in txn.meta.items() 
            if key not in internal_metadata_keys
        }
        
        # Create new transaction with cleaned metadata
        clean_txn = txn._replace(meta=clean_meta if clean_meta else None)
        cleaned_transactions.append(clean_txn)
    
    return cleaned_transactions