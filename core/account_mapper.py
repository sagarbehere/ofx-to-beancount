"""
Account mapping service for OFX to Beancount conversion.

This module handles mapping OFX account information to Beancount account names
using configuration rules and provides account validation.
"""

import os
from typing import List, Optional, Tuple
from beancount import loader
from beancount.core import data

from api.models.config import Config, AccountMapping
from core.ofx_parser import AccountInfo


class AccountMappingError(Exception):
    """Exception raised when account mapping fails."""
    pass


class AccountMappingResult:
    """Result of account mapping operation."""
    
    def __init__(self, account: str, currency: str, confidence: float):
        self.account = account
        self.currency = currency
        self.confidence = confidence


def map_account(ofx_account: AccountInfo, config: Config) -> AccountMappingResult:
    """
    Map OFX account information to a Beancount account using configuration.
    
    Args:
        ofx_account: OFX account information
        config: Configuration with account mappings
        
    Returns:
        AccountMappingResult with mapped account info
        
    Raises:
        AccountMappingError: If no mapping can be found
    """
    # Try to find exact match first
    for mapping in config.accounts:
        if _is_exact_match(ofx_account, mapping):
            return AccountMappingResult(
                account=mapping.beancount_account,
                currency=mapping.currency,
                confidence=1.0
            )
    
    # Try partial matches with scoring
    best_match = None
    best_score = 0.0
    
    for mapping in config.accounts:
        score = _calculate_match_score(ofx_account, mapping)
        if score > best_score:
            best_score = score
            best_match = mapping
    
    # Require at least 70% confidence for partial matches
    if best_match and best_score >= 0.7:
        return AccountMappingResult(
            account=best_match.beancount_account,
            currency=best_match.currency,
            confidence=best_score
        )
    
    # No good match found
    raise AccountMappingError(
        f"No suitable account mapping found for {ofx_account.institution} "
        f"account {ofx_account.account_id} (type: {ofx_account.account_type})"
    )


def detect_currency(ofx_account: AccountInfo, config: Config) -> str:
    """
    Detect the currency for an account.
    
    Args:
        ofx_account: OFX account information
        config: Configuration with default currency
        
    Returns:
        Currency code (3-letter string)
    """
    # Use OFX-specified currency if available
    if ofx_account.currency and ofx_account.currency != "USD":
        return ofx_account.currency.upper()
    
    # Try to get from account mapping
    try:
        mapping_result = map_account(ofx_account, config)
        return mapping_result.currency.upper()
    except AccountMappingError:
        pass
    
    # Fall back to default
    return config.default_currency.upper()


def validate_account_exists(account_name: str, account_file: str) -> bool:
    """
    Validate that an account exists in the Beancount accounts file.
    
    Args:
        account_name: Beancount account name to validate
        account_file: Path to Beancount file with account definitions
        
    Returns:
        True if account exists, False otherwise
    """
    if not os.path.exists(account_file):
        return False
    
    try:
        valid_accounts = load_accounts_from_file(account_file)
        return account_name in valid_accounts
    except Exception:
        return False


def load_accounts_from_file(account_file: str) -> List[str]:
    """
    Load account names from a Beancount file.
    
    Args:
        account_file: Path to Beancount file
        
    Returns:
        List of account names found in open directives
        
    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If file cannot be parsed
    """
    if not os.path.exists(account_file):
        raise FileNotFoundError(f"Account file not found: {account_file}")
    
    try:
        entries, errors, options_map = loader.load_file(account_file)
        
        if errors:
            # Log warnings but continue if possible
            print(f"Warnings while parsing account file: {len(errors)} issues found")
        
        accounts = set()
        for entry in entries:
            if isinstance(entry, data.Open):
                accounts.add(entry.account)
        
        return sorted(list(accounts))
    
    except Exception as e:
        raise ValueError(f"Failed to parse Beancount file: {e}")


def load_account_currencies(account_file: str) -> dict:
    """
    Load account names and their currencies from a Beancount file.
    
    Args:
        account_file: Path to Beancount file
        
    Returns:
        Dictionary mapping account names to currencies
        
    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If file cannot be parsed
    """
    if not os.path.exists(account_file):
        raise FileNotFoundError(f"Account file not found: {account_file}")
    
    try:
        entries, errors, options_map = loader.load_file(account_file)
        
        account_currencies = {}
        for entry in entries:
            if isinstance(entry, data.Open):
                # Use USD as default if no currency specified
                currencies = entry.currencies if entry.currencies else ["USD"]
                # Take the first currency if multiple are specified
                currency = currencies[0] if currencies else "USD"
                account_currencies[entry.account] = currency
        
        return account_currencies
    
    except Exception as e:
        raise ValueError(f"Failed to parse Beancount file: {e}")


def _is_exact_match(ofx_account: AccountInfo, mapping: AccountMapping) -> bool:
    """Check if OFX account exactly matches a mapping."""
    return (
        ofx_account.institution.upper() == mapping.institution.upper() and
        ofx_account.account_type.upper() == mapping.account_type.upper() and
        ofx_account.account_id == mapping.account_id
    )


def _calculate_match_score(ofx_account: AccountInfo, mapping: AccountMapping) -> float:
    """
    Calculate a match score between OFX account and mapping.
    
    Returns score between 0.0 and 1.0 where 1.0 is exact match.
    """
    score = 0.0
    total_weight = 0.0
    
    # Institution match (weight: 0.4)
    institution_weight = 0.4
    if ofx_account.institution.upper() == mapping.institution.upper():
        score += institution_weight
    total_weight += institution_weight
    
    # Account ID match (weight: 0.4)
    account_id_weight = 0.4
    if ofx_account.account_id == mapping.account_id:
        score += account_id_weight
    elif _account_id_similarity(ofx_account.account_id, mapping.account_id) > 0.8:
        # Partial match for similar account IDs
        score += account_id_weight * 0.7
    total_weight += account_id_weight
    
    # Account type match (weight: 0.2)
    account_type_weight = 0.2
    if ofx_account.account_type.upper() == mapping.account_type.upper():
        score += account_type_weight
    elif mapping.account_type == "":  # Empty type matches anything
        score += account_type_weight * 0.5
    total_weight += account_type_weight
    
    return score / total_weight if total_weight > 0 else 0.0


def _account_id_similarity(id1: str, id2: str) -> float:
    """Calculate similarity between two account IDs."""
    if not id1 or not id2:
        return 0.0
    
    if id1 == id2:
        return 1.0
    
    # Check if one is contained in the other (common for partial IDs)
    if id1 in id2 or id2 in id1:
        return max(len(id1), len(id2)) / max(len(id1), len(id2), 1)
    
    # Simple character-based similarity
    common_chars = set(id1) & set(id2)
    total_chars = set(id1) | set(id2)
    
    return len(common_chars) / len(total_chars) if total_chars else 0.0


def validate_config_accounts(config: Config, account_file: str) -> List[str]:
    """
    Validate that all configured account mappings reference existing accounts.
    
    Args:
        config: Configuration to validate
        account_file: Path to Beancount accounts file
        
    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []
    
    try:
        valid_accounts = load_accounts_from_file(account_file)
        
        for mapping in config.accounts:
            if mapping.beancount_account not in valid_accounts:
                errors.append(
                    f"Account '{mapping.beancount_account}' from configuration "
                    f"not found in accounts file"
                )
    
    except Exception as e:
        errors.append(f"Failed to validate accounts: {e}")
    
    return errors