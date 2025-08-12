"""
Transaction processing API endpoints.

This module handles transaction categorization and batch updates
during the interactive processing workflow.
"""

from fastapi import APIRouter, HTTPException, status
from typing import List, Dict, Any
from decimal import Decimal
import traceback

from api.models.session import (
    TransactionCategorizeRequest, TransactionCategorizeResponse,
    TransactionUpdateBatchRequest, TransactionUpdateBatchResponse
)
from api.models.transaction import (
    TransactionAPI, TransactionUpdateAPI, PostingAPI, ValidationError, SystemMessage
)
from api.services.session_manager import get_session_manager
from api.services.validator import validate_transaction_updates
from core.classifier import categorize_transaction, get_confidence_threshold
from core.duplicate_detector import detect_duplicates
from core.beancount_generator import validate_transaction
from core.transaction_id_generator import TransactionIdGenerator


router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.post("/categorize", response_model=TransactionCategorizeResponse)
async def categorize_transactions(request: TransactionCategorizeRequest):
    """
    Categorize all transactions using ML and detect duplicates.
    
    This endpoint:
    1. Validates the session and confirmed account information
    2. Updates all transactions with the confirmed account/currency
    3. Runs ML categorization on all transactions
    4. Performs duplicate detection against existing output file
    5. Returns all categorized transactions with confidence scores
    """
    try:
        session_manager = get_session_manager()
        
        # Validate session exists and is initialized
        session_manager.validate_session_state(request.session_id, 'initialized')
        session = session_manager.get_session(request.session_id)
        
        # Update transactions with confirmed account and currency
        for transaction in session.transactions:
            transaction.account = request.confirmed_account
            transaction.currency = request.confirmed_currency
        
        # Initialize transaction ID generator for this session
        id_generator = TransactionIdGenerator()
        
        # Generate transaction IDs and validate OFX IDs for all transactions
        for transaction in session.transactions:
            # Generate SHA256-based transaction ID using mapped account
            transaction.transaction_id = id_generator.generate_id(
                date=transaction.date,
                payee=transaction.payee,
                amount=str(transaction.amount),
                mapped_account=request.confirmed_account,  # Use confirmed account for ID generation
                is_kept_duplicate=False  # Will handle kept duplicates later if needed
            )
            
            # Validate and set OFX ID from original_ofx_id
            transaction.ofx_id = id_generator.validate_ofx_id(transaction.original_ofx_id)
        
        # Perform ML categorization if classifier is available
        categorized_transactions = []
        high_confidence_count = 0
        confidence_threshold = get_confidence_threshold()
        
        for transaction in session.transactions:
            # Initialize with unknown category
            suggested_category = "Expenses:Unknown"
            confidence = 0.0
            
            # Use ML classifier if available
            if session.classifier_model:
                try:
                    suggested_category, confidence = categorize_transaction(
                        transaction, session.classifier_model
                    )
                    
                    # Count high-confidence predictions
                    if confidence >= confidence_threshold:
                        high_confidence_count += 1
                except Exception as e:
                    print(f"Categorization failed for transaction {transaction.transaction_id}: {e}")
            
            # Create API transaction object with dual metadata
            api_transaction = TransactionAPI(
                id=transaction.transaction_id,
                date=transaction.date,
                payee=transaction.payee,
                memo=transaction.memo,
                amount=transaction.amount,
                currency=transaction.currency,
                suggested_category=suggested_category,
                confidence=confidence,
                is_potential_duplicate=False,  # Will be updated below
                transaction_id=transaction.transaction_id,
                ofx_id=transaction.ofx_id
            )
            
            categorized_transactions.append(api_transaction)
        
        # Perform duplicate detection if output file exists
        duplicate_count = 0
        system_messages = []
        
        # Always run duplicate detection since output file is now required
        try:
            duplicates = detect_duplicates(session.transactions, session.output_file_path)
            
            # Create mapping from new transaction to duplicate details
            duplicate_map = {}
            
            for dup in duplicates:
                # Find the API transaction that matches this duplicate's new transaction
                # Use transaction fields to match since we now have proper transaction IDs
                for api_txn in categorized_transactions:
                    if (api_txn.date == dup.new_transaction_date and 
                        api_txn.payee == dup.new_transaction_payee and 
                        api_txn.amount == dup.new_transaction_amount):
                        duplicate_map[api_txn.id] = dup
                        break
            
            # Apply duplicate information
            for api_txn in categorized_transactions:
                if api_txn.id in duplicate_map:
                    api_txn.is_potential_duplicate = True
                    api_txn.duplicate_details = duplicate_map[api_txn.id]
                    duplicate_count += 1
                    
        except Exception as e:
            print(f"Duplicate detection failed: {e}")
            system_messages.append(SystemMessage(
                level="warning",
                message=f"Duplicate detection unavailable: {str(e)}"
            ))
        
        # Update session state
        session_manager.update_session(request.session_id, is_categorized=True)
        
        return TransactionCategorizeResponse(
            transactions=categorized_transactions,
            total_count=len(categorized_transactions),
            high_confidence_count=high_confidence_count,
            duplicate_count=duplicate_count,
            system_messages=system_messages
        )
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"Transaction categorization error: {e}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error during categorization: {str(e)}"
        )


@router.post("/update-batch", response_model=TransactionUpdateBatchResponse)
async def update_transactions_batch(request: TransactionUpdateBatchRequest):
    """
    Update multiple transactions based on user interaction.
    
    This endpoint processes batch updates from the interactive CLI,
    including category confirmations, splits, and skip actions.
    """
    try:
        session_manager = get_session_manager()
        
        # Validate session exists and is categorized
        session_manager.validate_session_state(request.session_id, 'categorized')
        session = session_manager.get_session(request.session_id)
        
        # Validate transaction updates
        update_dicts = [update.dict() if hasattr(update, 'dict') else update for update in request.updates]
        validation_errors_list = validate_transaction_updates(update_dicts, session.valid_accounts)
        
        if validation_errors_list:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Validation errors: {'; '.join(validation_errors_list)}"
            )
        
        # Process updates
        updated_count = 0
        skipped_count = 0
        split_count = 0
        validation_errors = []
        
        # Create transaction lookup by transaction_id
        transaction_lookup = {}
        for i, transaction in enumerate(session.transactions):
            transaction_lookup[transaction.transaction_id] = i
        
        for update_data in update_dicts:
            transaction_id = update_data['transaction_id']
            
            # Find transaction
            if transaction_id not in transaction_lookup:
                validation_errors.append(ValidationError(
                    transaction_id=transaction_id,
                    error="Transaction not found",
                    details=f"No transaction found with ID: {transaction_id}"
                ))
                continue
            
            transaction_index = transaction_lookup[transaction_id]
            transaction = session.transactions[transaction_index]
            
            try:
                # Handle skip action
                if update_data.get('action') == 'skip':
                    # Mark transaction for skipping (don't include in export)
                    transaction.narration = f"SKIP: {update_data.get('reason', 'User skipped')}"
                    skipped_count += 1
                    continue
                
                # Update category
                if 'confirmed_category' in update_data and update_data['confirmed_category']:
                    from api.models.transaction import Posting
                    confirmed_category = update_data['confirmed_category']
                    
                    # Clear existing categorized accounts
                    transaction.categorized_accounts = []
                    
                    # Add new posting - opposite sign of source transaction
                    posting = Posting(
                        account=confirmed_category,
                        amount=-transaction.amount,
                        currency=transaction.currency
                    )
                    transaction.categorized_accounts.append(posting)
                    updated_count += 1
                
                # Update narration
                if 'narration' in update_data:
                    transaction.narration = update_data['narration'] or ""
                
                # Handle splits
                if 'splits' in update_data and update_data['splits']:
                    splits_data = update_data['splits']
                    transaction.is_split = True
                    transaction.categorized_accounts = []
                    
                    # Validate split balance
                    total_split_amount = Decimal('0')
                    
                    for split_data in splits_data:
                        from api.models.transaction import Posting
                        split_amount = Decimal(str(split_data['amount']))
                        total_split_amount += split_amount
                        
                        posting = Posting(
                            account=split_data['account'],
                            amount=split_amount,
                            currency=split_data['currency']
                        )
                        transaction.categorized_accounts.append(posting)
                    
                    # Check if splits balance with transaction amount
                    if abs(total_split_amount - abs(transaction.amount)) > Decimal('0.01'):
                        validation_errors.append(ValidationError(
                            transaction_id=transaction_id,
                            error="Split amounts do not balance",
                            details=f"Split total: {total_split_amount}, Transaction amount: {abs(transaction.amount)}"
                        ))
                        continue
                    
                    split_count += 1
                
                # Validate updated transaction
                transaction_validation_errors = validate_transaction(transaction)
                if transaction_validation_errors:
                    validation_errors.append(ValidationError(
                        transaction_id=transaction_id,
                        error="Transaction validation failed",
                        details="; ".join(transaction_validation_errors)
                    ))
            
            except Exception as e:
                validation_errors.append(ValidationError(
                    transaction_id=transaction_id,
                    error="Update processing failed",
                    details=str(e)
                ))
        
        return TransactionUpdateBatchResponse(
            updated_count=updated_count,
            skipped_count=skipped_count,
            split_count=split_count,
            validation_errors=validation_errors,
            system_messages=[]  # No system messages for updates currently
        )
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"Transaction batch update error: {e}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error during batch update: {str(e)}"
        )


@router.get("/{session_id}/summary")
async def get_transaction_summary(session_id: str):
    """Get summary statistics for session transactions."""
    try:
        session_manager = get_session_manager()
        session = session_manager.get_session(session_id)
        
        total_transactions = len(session.transactions)
        categorized_count = 0
        split_count = 0
        skip_count = 0
        
        categories = {}
        total_amount = Decimal('0')
        
        for transaction in session.transactions:
            if "SKIP:" in transaction.narration:
                skip_count += 1
                continue
            
            if transaction.categorized_accounts:
                categorized_count += 1
                
                if transaction.is_split:
                    split_count += 1
                
                for posting in transaction.categorized_accounts:
                    if posting.account not in categories:
                        categories[posting.account] = Decimal('0')
                    categories[posting.account] += posting.amount
                    total_amount += posting.amount
        
        return {
            "session_id": session_id,
            "total_transactions": total_transactions,
            "categorized_transactions": categorized_count,
            "split_transactions": split_count,
            "skipped_transactions": skip_count,
            "total_amount": float(total_amount),
            "categories": {cat: float(amount) for cat, amount in categories.items()}
        }
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found or error getting summary: {e}"
        )