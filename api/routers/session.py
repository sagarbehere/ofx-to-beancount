"""
Session management API endpoints.

This module handles session initialization including OFX parsing,
configuration loading, account mapping, and ML classifier training.
"""

from fastapi import APIRouter, HTTPException, status
from typing import List
import traceback
import os

from api.models.session import (
    SessionInitRequest, SessionInitResponse, OFXStats, DetectedAccount,
    ConfirmationRequired, SessionConfirmRequest, SessionConfirmResponse
)
from api.models.config import Config, load_config_file
from api.models.transaction import SystemMessage
from api.services.session_manager import get_session_manager
from api.services.validator import validate_session_init_request, validate_configuration
from core.file_validator import FileValidator, FileValidationError, FileErrorType
from core.ofx_parser import parse_ofx_file, validate_ofx_file
from core.account_mapper import (
    map_account, load_accounts_from_file, validate_config_accounts
)
from core.classifier import (
    extract_training_data_from_beancount, train_classifier, 
    validate_classifier_training
)


router = APIRouter(prefix="/session", tags=["session"])


@router.post("/initialize", response_model=SessionInitResponse)
async def initialize_session(request: SessionInitRequest):
    """
    Initialize a new processing session with comprehensive error handling.
    
    This endpoint handles file validation, graceful degradation for optional files,
    and confirmation workflows when files are unavailable.
    """
    try:
        from api.models.session import create_session_data
        
        session = create_session_data(request)
        session_manager = get_session_manager()
        # Store session in manager
        session_manager.sessions[session.session_id] = session
        system_messages = []
        
        # Phase 1: Validate all critical files first
        
        # Validate input OFX file (critical - must exist and be readable)
        ofx_errors = FileValidator.validate_input_file(request.ofx_file_path)
        if ofx_errors:
            error = ofx_errors[0]
            if error.error_type == FileErrorType.FILE_NOT_FOUND:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Input OFX file not found: {request.ofx_file_path}"
                )
            elif error.error_type == FileErrorType.PERMISSION_DENIED:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Input OFX file not readable: {request.ofx_file_path} - {error.details or error.message}"
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Input file error: {error.message}"
                )
        
        # Validate configuration file (critical - must exist and be valid)
        config_errors = FileValidator.validate_input_file(request.config_file_path)
        if config_errors:
            error = config_errors[0]
            if error.error_type == FileErrorType.FILE_NOT_FOUND:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Configuration file not found: {request.config_file_path}"
                )
            elif error.error_type == FileErrorType.PERMISSION_DENIED:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Configuration file not readable: {request.config_file_path} - {error.details or error.message}"
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Configuration file error: {error.message}"
                )
        
        # Validate output file (critical - must be specified and writable)
        output_errors = FileValidator.validate_output_file(request.output_file_path)
        if output_errors:
            error = output_errors[0]
            if error.error_type == FileErrorType.PERMISSION_DENIED:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Output file not writable: {error.message}"
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Output file error: {error.message}"
                )
        
        # Phase 2: Load critical files
        
        # Load configuration
        try:
            config = load_config_file(request.config_file_path)
            system_messages.append(SystemMessage(
                level="info",
                message=f"Configuration loaded successfully from {request.config_file_path}"
            ))
        except ValueError as e:
            # Config loading already provides detailed error messages
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )
        
        # Parse OFX file
        try:
            transactions, account_info, file_stats = parse_ofx_file(request.ofx_file_path)
            system_messages.append(SystemMessage(
                level="info",
                message=f"Successfully parsed OFX file: {file_stats.transaction_count} transactions from {request.ofx_file_path}"
            ))
        except Exception as e:
            # Check if it's a format error vs other error
            if "not appear to be a valid OFX file" in str(e) or "OFX" in str(e):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Input file does not appear to be a valid OFX file: {str(e)}"
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Error parsing OFX file: {str(e)}"
                )
        
        # Create output file if it doesn't exist
        if not os.path.exists(request.output_file_path):
            try:
                # Create empty output file
                write_errors = FileValidator.safe_file_write(request.output_file_path, "", create_dirs=True)
                if write_errors:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Cannot create output file: {write_errors[0].message}"
                    )
                system_messages.append(SystemMessage(
                    level="info",
                    message=f"Created output file: {request.output_file_path}"
                ))
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Error creating output file: {str(e)}"
                )
        
        # Phase 3: Handle optional files with confirmation workflow
        
        confirmation_required = False
        confirmations_needed = []
        
        # Check training data file
        training_available = True
        if request.training_file_path:
            training_errors = FileValidator.validate_optional_file(request.training_file_path)
            if training_errors:
                training_available = False
                error = training_errors[0]
                if error.error_type == FileErrorType.FILE_NOT_FOUND:
                    message = f"Training data file not found: {request.training_file_path}"
                elif error.error_type == FileErrorType.PERMISSION_DENIED:
                    message = f"Training data file not readable: {request.training_file_path}"
                else:
                    message = f"Training data file error: {error.message}"
                
                confirmations_needed.append(ConfirmationRequired(
                    confirmation_message=f"{message}. Continue without ML categorization? All transactions will use {config.default_account_when_training_unavailable}.",
                    confirmation_type="training_data_unavailable",
                    fallback_account=config.default_account_when_training_unavailable,
                    system_messages=[SystemMessage(level="warning", message=message)]
                ))
            else:
                # Try to load and validate training data
                try:
                    training_data = extract_training_data_from_beancount(request.training_file_path)
                    if not training_data:
                        training_available = False
                        message = f"Training data file does not contain valid Beancount transactions: {request.training_file_path}"
                        confirmations_needed.append(ConfirmationRequired(
                            confirmation_message=f"{message}. Continue without ML categorization? All transactions will use {config.default_account_when_training_unavailable}.",
                            confirmation_type="training_data_unavailable", 
                            fallback_account=config.default_account_when_training_unavailable,
                            system_messages=[SystemMessage(level="warning", message=message)]
                        ))
                except Exception as e:
                    training_available = False
                    message = f"Training data file contains invalid content: {str(e)}"
                    confirmations_needed.append(ConfirmationRequired(
                        confirmation_message=f"{message}. Continue without ML categorization? All transactions will use {config.default_account_when_training_unavailable}.",
                        confirmation_type="training_data_unavailable",
                        fallback_account=config.default_account_when_training_unavailable,
                        system_messages=[SystemMessage(level="warning", message=message)]
                    ))
        else:
            training_available = False
            system_messages.append(SystemMessage(
                level="warning",
                message="Training data file not specified - ML categorization will not be available"
            ))
        
        # Check accounts file
        accounts_available = True
        if request.account_file_path:
            account_errors = FileValidator.validate_optional_file(request.account_file_path)
            if account_errors:
                accounts_available = False
                error = account_errors[0]
                if error.error_type == FileErrorType.FILE_NOT_FOUND:
                    message = f"Accounts file not found: {request.account_file_path}"
                elif error.error_type == FileErrorType.PERMISSION_DENIED:
                    message = f"Accounts file not readable: {request.account_file_path}"
                else:
                    message = f"Accounts file error: {error.message}"
                
                confirmations_needed.append(ConfirmationRequired(
                    confirmation_message=f"{message}. Continue without account validation? Fuzzy completion will be limited.",
                    confirmation_type="accounts_unavailable", 
                    fallback_account=config.default_account_when_training_unavailable,
                    system_messages=[SystemMessage(level="warning", message=message)]
                ))
            else:
                # Try to load accounts
                try:
                    valid_accounts = load_accounts_from_file(request.account_file_path)
                    if not valid_accounts:
                        accounts_available = False
                        message = f"Accounts file does not contain valid Beancount account definitions: {request.account_file_path}"
                        confirmations_needed.append(ConfirmationRequired(
                            confirmation_message=f"{message}. Continue without account validation? Fuzzy completion will be limited.",
                            confirmation_type="accounts_unavailable",
                            fallback_account=config.default_account_when_training_unavailable,
                            system_messages=[SystemMessage(level="warning", message=message)]
                        ))
                except Exception as e:
                    accounts_available = False
                    message = f"Accounts file contains invalid content: {str(e)}"
                    confirmations_needed.append(ConfirmationRequired(
                        confirmation_message=f"{message}. Continue without account validation? Fuzzy completion will be limited.",
                        confirmation_type="accounts_unavailable",
                        fallback_account=config.default_account_when_training_unavailable,
                        system_messages=[SystemMessage(level="warning", message=message)]
                    ))
        else:
            accounts_available = False
            system_messages.append(SystemMessage(
                level="warning", 
                message="Accounts file not specified - Account validation and auto-suggestions will not work"
            ))
        
        # If confirmations are needed, return confirmation required response
        if confirmations_needed:
            # Return first confirmation needed (handle one at a time)
            return SessionInitResponse(
                session_id=session.session_id,
                requires_confirmation=True,
                confirmation_details=confirmations_needed[0],
                system_messages=system_messages
            )
        
        # Phase 4: Complete initialization (no confirmations needed)
        
        # Store session data
        session.transactions = transactions
        if accounts_available:
            session.valid_accounts = load_accounts_from_file(request.account_file_path)
            system_messages.append(SystemMessage(
                level="info",
                message=f"Account validation enabled with {len(session.valid_accounts)} accounts from {request.account_file_path}"
            ))
        else:
            session.valid_accounts = []
        
        # Train classifier if training data available
        classifier_trained = False
        training_data_count = 0
        if training_available:
            try:
                training_data = extract_training_data_from_beancount(request.training_file_path)
                classifier_model = train_classifier(training_data)
                session.classifier_model = classifier_model
                session.training_data_count = len(training_data)
                training_data_count = len(training_data)
                classifier_trained = True
                system_messages.append(SystemMessage(
                    level="info",
                    message=f"ML classifier trained on {training_data_count} transactions from {request.training_file_path}"
                ))
            except Exception as e:
                system_messages.append(SystemMessage(
                    level="warning",
                    message=f"Classifier training failed: {str(e)}"
                ))
        
        # Detect account mapping
        try:
            account_mapping = map_account(account_info, config)
            detected_account = DetectedAccount(
                account=account_mapping.account,
                currency=account_mapping.currency,
                confidence=account_mapping.confidence
            )
        except Exception as e:
            # If mapping fails, use a default account with low confidence
            detected_account = DetectedAccount(
                account="Assets:Unknown",
                currency=config.default_currency,
                confidence=0.0
            )
        
        session.detected_account = detected_account.account
        session.detected_currency = detected_account.currency
        session.is_initialized = True
        
        # Prepare response
        ofx_stats = OFXStats(
            transaction_count=file_stats.transaction_count,
            date_range={
                "start": file_stats.start_date,
                "end": file_stats.end_date
            },
            balance=file_stats.balance,
            currency=file_stats.currency
        )
        
        return SessionInitResponse(
            session_id=session.session_id,
            ofx_stats=ofx_stats,
            detected_account=detected_account,
            valid_accounts=session.valid_accounts,
            classifier_trained=classifier_trained,
            training_data_count=training_data_count,
            system_messages=system_messages
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Session initialization error: {e}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error during session initialization: {str(e)}"
        )


# Add new endpoint for handling confirmations
@router.post("/confirm", response_model=SessionConfirmResponse)  
async def confirm_degraded_functionality(request: SessionConfirmRequest) -> SessionConfirmResponse:
    """Handle user confirmation for degraded functionality scenarios."""
    try:
        session_manager = get_session_manager()
        session = session_manager.get_session(request.session_id)
        system_messages = []
        
        if request.user_choice == "abort":
            # User chose to abort - clean up session
            session_manager.delete_session(request.session_id)
            return SessionConfirmResponse(
                session_id=request.session_id,
                processing_continues=False,
                system_messages=[SystemMessage(level="info", message="Session aborted by user")]
            )
        elif request.user_choice == "continue":
            # User chose to continue - handle based on confirmation type
            if request.confirmation_type == "training_data_unavailable":
                # Continue without classifier - use default account
                session.classifier_model = None
                session.training_data_count = 0
                system_messages.append(SystemMessage(
                    level="warning", 
                    message="Continuing without ML categorization. Using default account from config."
                ))
            elif request.confirmation_type == "accounts_unavailable":
                # Continue without account validation
                session.valid_accounts = []
                system_messages.append(SystemMessage(
                    level="warning",
                    message="Continuing without account validation. Fuzzy completion will be limited."
                ))
            
            # Mark session as initialized if this was the last confirmation
            # Note: This simplified version handles one confirmation at a time
            # A full implementation might need to track multiple pending confirmations
            session.is_initialized = True
            
            return SessionConfirmResponse(
                session_id=request.session_id,
                processing_continues=True,
                system_messages=system_messages
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid user choice: {request.user_choice}. Must be 'continue' or 'abort'"
            )
            
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )
    except Exception as e:
        print(f"Session confirmation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing confirmation: {str(e)}"
        )


@router.get("/status/{session_id}")
async def get_session_status(session_id: str):
    """Get the current status of a session."""
    try:
        session_manager = get_session_manager()
        session = session_manager.get_session(session_id)
        
        return {
            "session_id": session_id,
            "created_at": session.created_at.isoformat(),
            "is_initialized": session.is_initialized,
            "is_categorized": session.is_categorized,
            "transaction_count": len(session.transactions),
            "has_classifier": session.classifier_model is not None,
            "training_data_count": session.training_data_count
        }
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found or expired: {e}"
        )


@router.delete("/cleanup")
async def cleanup_expired_sessions():
    """Clean up expired sessions (admin endpoint)."""
    try:
        session_manager = get_session_manager()
        cleaned_up = session_manager.cleanup_expired_sessions()
        
        return {
            "cleaned_up_sessions": cleaned_up,
            "remaining_sessions": session_manager.get_session_count()
        }
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cleanup sessions: {e}"
        )


@router.get("/stats")
async def get_session_stats():
    """Get overall session statistics (admin endpoint)."""
    try:
        session_manager = get_session_manager()
        return session_manager.get_session_stats()
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get session stats: {e}"
        )