"""
Export API endpoints for generating Beancount output.

This module handles the final export of processed transactions
to Beancount format files.
"""

from fastapi import APIRouter, HTTPException, status
from typing import List
from decimal import Decimal
import traceback

from api.models.session import (
    ExportBeancountRequest, ExportBeancountResponse, ExportSummary
)
from api.services.session_manager import get_session_manager
from api.services.validator import validate_export_request
from core.beancount_generator import (
    append_to_beancount_file, write_to_beancount_file,
    generate_export_summary, preview_beancount_output, validate_transaction
)


router = APIRouter(prefix="/export", tags=["export"])


@router.post("/beancount", response_model=ExportBeancountResponse)
async def export_beancount(request: ExportBeancountRequest):
    """
    Export processed transactions to Beancount format.
    
    This endpoint:
    1. Validates the session and export parameters
    2. Filters out skipped transactions
    3. Validates all transactions for Beancount compliance
    4. Generates the Beancount output format
    5. Writes to the output file (append or overwrite mode)
    6. Returns export summary and preview
    """
    try:
        session_manager = get_session_manager()
        
        # Validate session exists and is categorized
        session_manager.validate_session_state(request.session_id, 'categorized')
        session = session_manager.get_session(request.session_id)
        
        # Validate export request
        validation_errors = validate_export_request(
            request.session_id,
            request.output_file_path,
            request.output_mode
        )
        
        if validation_errors:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Validation errors: {'; '.join(validation_errors)}"
            )
        
        # Filter Beancount transactions for export (use canonical format)
        beancount_transactions_to_export = []
        validation_errors = []
        
        # Use Beancount transactions if available, fall back to API transactions for backward compatibility
        if hasattr(session, 'beancount_transactions') and session.beancount_transactions:
            for bc_transaction in session.beancount_transactions:
                # Skip transactions marked for skipping
                if bc_transaction.narration and "SKIP:" in bc_transaction.narration:
                    continue
                
                beancount_transactions_to_export.append(bc_transaction)
        else:
            # Backward compatibility: convert from API transactions
            print("Warning: Using API transactions for export (backward compatibility mode)")
            from core.beancount_converter import api_transaction_to_beancount
            
            for transaction in session.transactions:
                # Skip transactions marked for skipping
                if transaction.narration and "SKIP:" in transaction.narration:
                    continue
                
                # Validate transaction before export
                transaction_errors = validate_transaction(transaction)
                if transaction_errors:
                    validation_errors.extend([
                        f"Transaction {transaction.transaction_id}: {error}"
                        for error in transaction_errors
                    ])
                    continue  # Skip invalid transactions
                
                # Ensure transaction has categorized accounts
                if not transaction.categorized_accounts:
                    # Add default unknown category
                    from api.models.transaction import Posting
                    unknown_posting = Posting(
                        account="Expenses:Unknown",
                        amount=abs(transaction.amount),
                        currency=transaction.currency
                    )
                    transaction.categorized_accounts = [unknown_posting]
                
                # Convert to Beancount format
                bc_transaction = api_transaction_to_beancount(transaction, transaction.account)
                beancount_transactions_to_export.append(bc_transaction)
        
        if not beancount_transactions_to_export:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid transactions to export"
            )
        
        if validation_errors:
            # Return validation errors but don't fail completely
            print(f"Transaction validation warnings: {'; '.join(validation_errors)}")
        
        # Generate Beancount output using native printer (same as add_transaction_ids.py)
        try:
            from beancount.parser import printer
            from core.beancount_converter import clean_internal_metadata_for_output
            import io
            
            # Clean up internal metadata before final output
            clean_transactions = clean_internal_metadata_for_output(beancount_transactions_to_export)
            
            output_content = io.StringIO()
            printer.print_entries(clean_transactions, file=output_content)
            beancount_content = output_content.getvalue()
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to generate Beancount output: {e}"
            )
        
        # Write to file
        try:
            if request.output_mode == "append":
                append_to_beancount_file(beancount_content, request.output_file_path)
            else:  # overwrite
                write_to_beancount_file(beancount_content, request.output_file_path)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to write output file: {e}"
            )
        
        # Convert Beancount transactions back to API format for summary generation (temporary)
        # TODO: Update generate_export_summary to work with Beancount objects directly
        from core.beancount_converter import beancount_to_api_transaction
        api_transactions_for_summary = [
            beancount_to_api_transaction(bc_txn) 
            for bc_txn in beancount_transactions_to_export
        ]
        
        # Generate export summary
        summary_data = generate_export_summary(api_transactions_for_summary)
        export_summary = ExportSummary(
            total_amount=summary_data['total_amount'],
            currency=summary_data['currency'],
            categories=summary_data['categories'],
            date_range=summary_data['date_range']
        )
        
        # Generate preview using native Beancount printer
        from beancount.parser import printer
        from core.beancount_converter import clean_internal_metadata_for_output
        import io
        
        preview_transactions = beancount_transactions_to_export[:5]  # First 5 for preview
        clean_preview_transactions = clean_internal_metadata_for_output(preview_transactions)
        preview_content = io.StringIO()
        printer.print_entries(clean_preview_transactions, file=preview_content)
        preview = preview_content.getvalue()
        
        return ExportBeancountResponse(
            transactions_exported=len(beancount_transactions_to_export),
            file_path=request.output_file_path,
            summary=export_summary,
            beancount_preview=preview
        )
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"Export error: {e}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error during export: {str(e)}"
        )


@router.get("/preview/{session_id}")
async def preview_export(session_id: str, max_transactions: int = 5):
    """
    Preview the Beancount output without writing to file.
    
    Args:
        session_id: Session identifier
        max_transactions: Maximum number of transactions to include in preview
    """
    try:
        session_manager = get_session_manager()
        session = session_manager.get_session(session_id)
        
        # Filter Beancount transactions for preview (use same logic as export)
        beancount_transactions_to_export = []
        
        # Use Beancount transactions if available, fall back to API transactions for backward compatibility
        if hasattr(session, 'beancount_transactions') and session.beancount_transactions:
            for bc_transaction in session.beancount_transactions:
                # Skip transactions marked for skipping
                if bc_transaction.narration and "SKIP:" in bc_transaction.narration:
                    continue
                
                beancount_transactions_to_export.append(bc_transaction)
        else:
            # Backward compatibility: convert from API transactions
            from core.beancount_converter import api_transaction_to_beancount
            
            for transaction in session.transactions:
                # Skip transactions marked for skipping
                if transaction.narration and "SKIP:" in transaction.narration:
                    continue
                
                # Skip invalid transactions
                transaction_errors = validate_transaction(transaction)
                if transaction_errors:
                    continue
                
                # Ensure transaction has categorized accounts
                if not transaction.categorized_accounts:
                    from api.models.transaction import Posting
                    unknown_posting = Posting(
                        account="Expenses:Unknown",
                        amount=abs(transaction.amount),
                        currency=transaction.currency
                    )
                    transaction.categorized_accounts = [unknown_posting]
                
                # Convert to Beancount format
                bc_transaction = api_transaction_to_beancount(transaction, transaction.account)
                beancount_transactions_to_export.append(bc_transaction)
        
        if not beancount_transactions_to_export:
            return {
                "preview": "",
                "message": "No valid transactions to export"
            }
        
        # Generate preview using native Beancount printer
        from beancount.parser import printer
        from core.beancount_converter import clean_internal_metadata_for_output
        import io
        
        preview_transactions = beancount_transactions_to_export[:max_transactions]
        clean_preview_transactions = clean_internal_metadata_for_output(preview_transactions)
        preview_content = io.StringIO()
        printer.print_entries(clean_preview_transactions, file=preview_content)
        preview = preview_content.getvalue()
        
        return {
            "preview": preview,
            "total_transactions": len(beancount_transactions_to_export),
            "preview_count": min(len(beancount_transactions_to_export), max_transactions)
        }
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found or preview error: {e}"
        )


@router.get("/validate/{session_id}")
async def validate_export_readiness(session_id: str):
    """
    Validate that a session is ready for export.
    
    Returns validation results without performing export.
    """
    try:
        session_manager = get_session_manager()
        session = session_manager.get_session(session_id)
        
        validation_results = {
            "session_valid": True,
            "is_categorized": session.is_categorized,
            "total_transactions": len(session.transactions),
            "exportable_transactions": 0,
            "skipped_transactions": 0,
            "invalid_transactions": 0,
            "validation_errors": []
        }
        
        for transaction in session.transactions:
            # Check if skipped
            if transaction.narration and "SKIP:" in transaction.narration:
                validation_results["skipped_transactions"] += 1
                continue
            
            # Validate transaction
            transaction_errors = validate_transaction(transaction)
            if transaction_errors:
                validation_results["invalid_transactions"] += 1
                validation_results["validation_errors"].extend([
                    f"Transaction {transaction.transaction_id}: {error}"
                    for error in transaction_errors
                ])
                continue
            
            validation_results["exportable_transactions"] += 1
        
        # Overall readiness assessment
        validation_results["ready_for_export"] = (
            validation_results["is_categorized"] and
            validation_results["exportable_transactions"] > 0
        )
        
        return validation_results
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found or validation error: {e}"
        )