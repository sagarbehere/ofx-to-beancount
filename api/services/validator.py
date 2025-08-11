"""
Data validation service for API requests and responses.

This module provides validation utilities for ensuring data integrity
throughout the API processing pipeline.
"""

import os
from typing import List, Dict, Any, Optional
from decimal import Decimal

from api.models.transaction import Transaction, Posting, TransactionUpdateAPI
from api.models.config import Config, load_config_file, validate_config
from core.account_mapper import load_accounts_from_file


class ValidationError(Exception):
    """Exception raised when validation fails."""
    pass


def validate_file_paths(file_paths: Dict[str, Optional[str]]) -> List[str]:
    """
    Validate that file paths exist and are accessible.
    
    Args:
        file_paths: Dictionary of file path names to paths
        
    Returns:
        List of validation error messages
    """
    errors = []
    
    for path_name, path in file_paths.items():
        if path is None:
            continue  # Optional paths
        
        if not isinstance(path, str) or not path.strip():
            errors.append(f"{path_name} must be a non-empty string")
            continue
        
        if not os.path.exists(path):
            errors.append(f"{path_name} file not found: {path}")
        elif not os.path.isfile(path):
            errors.append(f"{path_name} is not a file: {path}")
        elif not os.access(path, os.R_OK):
            errors.append(f"{path_name} is not readable: {path}")
    
    return errors


def validate_configuration(config_file_path: str, account_file_path: Optional[str] = None) -> List[str]:
    """
    Validate configuration file and its contents.
    
    Args:
        config_file_path: Path to configuration file
        account_file_path: Path to accounts file for validation
        
    Returns:
        List of validation error messages
    """
    errors = []
    
    # Check if config file exists
    if not os.path.exists(config_file_path):
        errors.append(f"Configuration file not found: {config_file_path}")
        return errors
    
    try:
        # Load and validate configuration
        config = load_config_file(config_file_path)
        
        # Basic config validation
        if not config.accounts:
            errors.append("No account mappings found in configuration")
        
        if not config.default_currency:
            errors.append("Default currency not specified in configuration")
        elif len(config.default_currency) != 3:
            errors.append(f"Invalid default currency: {config.default_currency} (must be 3 characters)")
        
        # Validate account mappings if accounts file provided
        if account_file_path and config.accounts:
            account_errors = validate_config(config, load_accounts_from_file(account_file_path))
            errors.extend(account_errors)
    
    except Exception as e:
        errors.append(f"Configuration validation failed: {e}")
    
    return errors


def validate_session_init_request(ofx_file_path: str, config_file_path: str, output_file_path: str,
                                 training_file_path: Optional[str] = None,
                                 account_file_path: Optional[str] = None) -> List[str]:
    """
    Validate session initialization request data.
    
    Args:
        ofx_file_path: Path to OFX file
        config_file_path: Path to YAML configuration file
        training_file_path: Path to training file (optional)
        account_file_path: Path to accounts file (optional)
        output_file_path: Path to output file
        
    Returns:
        List of validation error messages
    """
    errors = []
    
    # Validate file paths
    file_paths = {
        'OFX file': ofx_file_path,
        'configuration file': config_file_path,
        'training file': training_file_path,
        'account file': account_file_path
    }
    
    # Don't validate output file existence (it may not exist yet)
    # Validate output file directory exists
    output_dir = os.path.dirname(output_file_path)
    if output_dir and not os.path.exists(output_dir):
        errors.append(f"Output directory does not exist: {output_dir}")
    elif output_dir and not os.access(output_dir, os.W_OK):
        errors.append(f"Output directory is not writable: {output_dir}")
    
    file_errors = validate_file_paths(file_paths)
    errors.extend(file_errors)
    
    # Config file validation is now handled when loading the file
    
    return errors


def validate_transaction_updates(updates: List[Dict[str, Any]], 
                               valid_accounts: List[str]) -> List[str]:
    """
    Validate transaction update data.
    
    Args:
        updates: List of transaction updates
        valid_accounts: List of valid account names
        
    Returns:
        List of validation error messages
    """
    errors = []
    
    if not updates:
        errors.append("No transaction updates provided")
        return errors
    
    for i, update in enumerate(updates):
        update_errors = validate_single_transaction_update(update, valid_accounts)
        # Prefix errors with update index
        for error in update_errors:
            errors.append(f"Update {i + 1}: {error}")
    
    return errors


def validate_single_transaction_update(update: Dict[str, Any], 
                                     valid_accounts: List[str]) -> List[str]:
    """
    Validate a single transaction update.
    
    Args:
        update: Transaction update data
        valid_accounts: List of valid account names
        
    Returns:
        List of validation error messages
    """
    errors = []
    
    # Required fields
    if 'transaction_id' not in update or not update['transaction_id']:
        errors.append("Transaction ID is required")
    
    # Validate account name if provided
    if 'confirmed_category' in update and update['confirmed_category']:
        account = update['confirmed_category']
        if account not in valid_accounts:
            errors.append(f"Invalid account: {account}")
    
    # Validate splits if provided
    if 'splits' in update and update['splits']:
        splits = update['splits']
        if not isinstance(splits, list):
            errors.append("Splits must be a list")
        else:
            total_amount = Decimal('0')
            for j, split in enumerate(splits):
                if not isinstance(split, dict):
                    errors.append(f"Split {j + 1} must be an object")
                    continue
                
                # Required split fields
                if 'account' not in split:
                    errors.append(f"Split {j + 1} missing account")
                elif split['account'] not in valid_accounts:
                    errors.append(f"Split {j + 1} invalid account: {split['account']}")
                
                if 'amount' not in split:
                    errors.append(f"Split {j + 1} missing amount")
                else:
                    try:
                        amount = Decimal(str(split['amount']))
                        total_amount += amount
                    except (ValueError, TypeError):
                        errors.append(f"Split {j + 1} invalid amount: {split['amount']}")
                
                if 'currency' not in split:
                    errors.append(f"Split {j + 1} missing currency")
                elif len(split['currency']) != 3:
                    errors.append(f"Split {j + 1} invalid currency: {split['currency']}")
            
            # Check if splits balance (should sum to positive amount)
            if abs(total_amount) < Decimal('0.01'):
                errors.append("Split amounts must sum to a positive value")
    
    # Validate action if provided
    if 'action' in update:
        valid_actions = ['skip']
        if update['action'] not in valid_actions:
            errors.append(f"Invalid action: {update['action']}")
    
    return errors


def validate_export_request(session_id: str, output_file_path: str, 
                           output_mode: str = "append") -> List[str]:
    """
    Validate export request data.
    
    Args:
        session_id: Session identifier
        output_file_path: Path to output file
        output_mode: Export mode ('append' or 'overwrite')
        
    Returns:
        List of validation error messages
    """
    errors = []
    
    if not session_id:
        errors.append("Session ID is required")
    
    if not output_file_path:
        errors.append("Output file path is required")
    else:
        # Check if directory exists and is writable
        output_dir = os.path.dirname(output_file_path)
        if output_dir and not os.path.exists(output_dir):
            errors.append(f"Output directory does not exist: {output_dir}")
        elif output_dir and not os.access(output_dir, os.W_OK):
            errors.append(f"Output directory is not writable: {output_dir}")
    
    if output_mode not in ['append', 'overwrite']:
        errors.append("Output mode must be 'append' or 'overwrite'")
    
    return errors


def validate_account_name_format(account_name: str) -> List[str]:
    """
    Validate Beancount account name format.
    
    Args:
        account_name: Account name to validate
        
    Returns:
        List of validation error messages
    """
    errors = []
    
    if not account_name:
        errors.append("Account name is required")
        return errors
    
    parts = account_name.split(':')
    if len(parts) < 2:
        errors.append("Account name must have at least two levels (e.g., Assets:Checking)")
    
    valid_root_types = ['Assets', 'Liabilities', 'Equity', 'Income', 'Expenses']
    if parts and parts[0] not in valid_root_types:
        errors.append(f"Account must start with one of: {', '.join(valid_root_types)}")
    
    for i, part in enumerate(parts):
        if not part:
            errors.append(f"Account level {i + 1} cannot be empty")
        elif not part.replace('-', '').replace('_', '').isalnum():
            errors.append(f"Account level '{part}' contains invalid characters")
    
    return errors


def validate_currency_code(currency: str) -> List[str]:
    """
    Validate currency code format.
    
    Args:
        currency: Currency code to validate
        
    Returns:
        List of validation error messages
    """
    errors = []
    
    if not currency:
        errors.append("Currency code is required")
    elif len(currency) != 3:
        errors.append("Currency code must be exactly 3 characters")
    elif not currency.isalpha():
        errors.append("Currency code must contain only letters")
    elif not currency.isupper():
        errors.append("Currency code must be uppercase")
    
    return errors