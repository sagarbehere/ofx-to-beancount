"""
Configuration data models for the OFX to Beancount converter.

This module defines the data structures for handling YAML configuration
files and account mappings.
"""

from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, validator
import yaml
import os


@dataclass
class AccountMapping:
    """Represents a mapping between OFX account data and Beancount accounts."""
    institution: str
    account_type: str
    account_id: str
    beancount_account: str
    currency: str


@dataclass
class Config:
    """Main configuration data structure."""
    accounts: List[AccountMapping]
    default_currency: str
    default_account_when_training_unavailable: str
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Config':
        """Create Config from dictionary data."""
        mappings = []
        if 'accounts' in data and 'mappings' in data['accounts']:
            for mapping_data in data['accounts']['mappings']:
                if 'beancount_account' not in mapping_data:
                    raise ValueError(f"Missing required field 'beancount_account' in account mapping")
                
                mappings.append(AccountMapping(
                    institution=mapping_data.get('institution', ''),
                    account_type=mapping_data.get('account_type', ''),
                    account_id=mapping_data.get('account_id', ''),
                    beancount_account=mapping_data['beancount_account'],
                    currency=mapping_data.get('currency', data.get('default_currency', 'USD'))
                ))
        
        return cls(
            accounts=mappings,
            default_currency=data.get('default_currency', 'USD'),
            default_account_when_training_unavailable=data.get('default_account_when_training_unavailable', 'Expenses:Unknown')
        )


# Pydantic models for API validation
class AccountMappingAPI(BaseModel):
    """API model for account mappings."""
    institution: str = Field(..., description="Financial institution name")
    account_type: str = Field("", description="Account type from OFX")
    account_id: str = Field(..., description="Account ID from OFX")
    beancount_account: str = Field(..., description="Target Beancount account name")
    currency: str = Field("USD", description="Account currency")
    
    @validator('beancount_account')
    def validate_account_name(cls, v):
        """Validate Beancount account name format."""
        if not v:
            raise ValueError('Beancount account name is required')
        
        # Basic validation for Beancount account naming conventions
        parts = v.split(':')
        if len(parts) < 2:
            raise ValueError('Beancount account must have at least two levels (e.g., Assets:Checking)')
        
        valid_root_types = ['Assets', 'Liabilities', 'Equity', 'Income', 'Expenses']
        if parts[0] not in valid_root_types:
            raise ValueError(f'Account must start with one of: {", ".join(valid_root_types)}')
        
        return v


class ConfigAPI(BaseModel):
    """API model for configuration data."""
    accounts: Dict[str, List[AccountMappingAPI]] = Field(..., description="Account mappings")
    default_currency: str = Field("USD", description="Default currency code")
    default_account_when_training_unavailable: str = Field("Expenses:Unknown", description="Default account when training data unavailable")
    
    @validator('default_currency')
    def validate_currency(cls, v):
        """Validate currency code format."""
        if len(v) != 3:
            raise ValueError('Currency code must be 3 characters')
        return v.upper()


# Configuration file operations
def load_config_file(file_path: str) -> Config:
    """Load and validate configuration file with comprehensive error handling."""
    from core.file_validator import FileValidator, FileErrorType
    
    # Use FileValidator for robust error handling
    content, errors = FileValidator.safe_file_read(file_path)
    if errors:
        error = errors[0]  # Take first error
        if error.error_type == FileErrorType.FILE_NOT_FOUND:
            raise ValueError(f"Configuration file not found: {file_path}")
        elif error.error_type == FileErrorType.PERMISSION_DENIED:
            raise ValueError(f"Configuration file not readable: {file_path} - {error.message}")
        else:
            raise ValueError(f"Configuration file error: {error.message}")
    
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise ValueError(f"Configuration file contains invalid YAML: {str(e)}")
    
    if not isinstance(data, dict):
        raise ValueError("Configuration file must contain a YAML dictionary")
    
    # Validate required fields
    if 'accounts' not in data:
        raise ValueError("Configuration file missing required 'accounts' section")
    
    return Config.from_dict(data)


def validate_config(config: Config, valid_accounts: List[str]) -> List[str]:
    """
    Validate configuration against available accounts.
    
    Returns list of validation errors, empty if valid.
    """
    errors = []
    
    if not config.accounts:
        errors.append("No account mappings found in configuration")
        return errors
    
    for mapping in config.accounts:
        if not mapping.beancount_account:
            errors.append("Account mapping missing beancount_account")
            continue
        
        if mapping.beancount_account not in valid_accounts:
            errors.append(f"Account '{mapping.beancount_account}' not found in accounts file")
    
    return errors


def create_example_config() -> Dict[str, Any]:
    """Create an example configuration structure."""
    return {
        'accounts': {
            'mappings': [
                {
                    'institution': 'AMEX',
                    'account_type': '',
                    'account_id': '9OIB5AB8SY32XLB|12007',
                    'beancount_account': 'Liabilities:Amex:BlueCashPreferred',
                    'currency': 'USD'
                },
                {
                    'institution': 'CHASE',
                    'account_type': 'CHECKING',
                    'account_id': '1234567890',
                    'beancount_account': 'Assets:Chase:Checking',
                    'currency': 'USD'
                }
            ]
        },
        'default_currency': 'USD',
        'default_account_when_training_unavailable': 'Expenses:Unknown'
    }