"""
Transaction ID Generator - Self-contained utility for generating unique transaction IDs.

This module provides a reusable service for generating SHA256-based transaction IDs
with collision handling and OFX ID validation. It's designed to be framework-agnostic
and easily portable to other projects.

Dependencies: Only standard library modules (hashlib, secrets, typing)
"""

import hashlib
import secrets
from typing import Dict, Set, Optional, Tuple, Union
from decimal import Decimal


class TransactionIdGenerator:
    """
    Generates unique transaction IDs using SHA256 hashes of immutable transaction fields.
    
    Features:
    - Deterministic SHA256 hashing based on date|payee|amount|account
    - Collision handling with -2, -3, etc. suffixes
    - Duplicate handling with -dup-1, -dup-2, etc. suffixes
    - OFX ID validation and cleaning
    - Fallback ID generation when mapped account unavailable
    - Self-contained with no external dependencies beyond standard library
    
    Usage:
        generator = TransactionIdGenerator()
        
        # Generate transaction ID
        txn_id = generator.generate_id("2024-01-15", "GROCERY STORE", "-85.50", "Liabilities:CreditCard")
        
        # Validate OFX ID
        clean_ofx_id = generator.validate_ofx_id("  20240115001234567890  ")
    """
    
    def __init__(self):
        """Initialize generator with empty state tracking."""
        self.used_ids: Set[str] = set()
        self.collision_counters: Dict[str, int] = {}
    
    def generate_id(self, 
                   date: str, 
                   payee: str, 
                   amount: Union[str, Decimal, float], 
                   mapped_account: str, 
                   is_kept_duplicate: bool = False) -> str:
        """
        Generate unique transaction ID using SHA256 hash of immutable fields.
        
        The hash input format is: "{date}|{payee}|{amount}|{mapped_account}"
        
        Args:
            date: Transaction date in YYYY-MM-DD format
            payee: Transaction payee/merchant name
            amount: Transaction amount (can be string, Decimal, or float)
            mapped_account: Beancount account name (e.g., "Assets:Checking")
            is_kept_duplicate: Whether this is a kept duplicate transaction
            
        Returns:
            64-character SHA256 hash string, potentially with suffix for collisions/duplicates
            
        Examples:
            # Normal transaction
            >>> gen = TransactionIdGenerator()
            >>> gen.generate_id("2024-01-15", "GROCERY STORE", "-85.50", "Liabilities:CreditCard")
            'a1b2c3d4e5f6789012345678901234567890123456789012345678901234567890'
            
            # Kept duplicate
            >>> gen.generate_id("2024-01-15", "GROCERY STORE", "-85.50", "Liabilities:CreditCard", True)
            'a1b2c3d4e5f6789012345678901234567890123456789012345678901234567890-dup-1'
            
            # Fallback when no account
            >>> gen.generate_id("2024-01-15", "GROCERY STORE", "-85.50", "")
            'fallback_a1b2c3d4'
        """
        # Fallback if mapped account not available
        if not mapped_account or not str(mapped_account).strip():
            random_suffix = secrets.token_hex(4)  # 8 char random string
            fallback_id = f"fallback_{random_suffix}"
            self.used_ids.add(fallback_id)
            return fallback_id
        
        # Normalize inputs
        clean_payee = str(payee) if payee else ""
        clean_amount = str(amount) if amount else "0"
        clean_account = str(mapped_account).strip()
        
        # Create hash input
        hash_input = f"{date}|{clean_payee}|{clean_amount}|{clean_account}"
        base_hash = hashlib.sha256(hash_input.encode('utf-8')).hexdigest()
        
        # Handle kept duplicates
        if is_kept_duplicate:
            final_id = self._handle_kept_duplicate(base_hash)
        else:
            # Handle collisions
            final_id = self._handle_collision(base_hash)
        
        self.used_ids.add(final_id)
        return final_id
    
    def _handle_kept_duplicate(self, base_hash: str) -> str:
        """Handle kept duplicate ID generation with -dup-N suffix."""
        dup_counter = 1
        while f"{base_hash}-dup-{dup_counter}" in self.used_ids:
            dup_counter += 1
        return f"{base_hash}-dup-{dup_counter}"
    
    def _handle_collision(self, base_hash: str) -> str:
        """Handle hash collision with -N suffix."""
        if base_hash not in self.used_ids:
            return base_hash
        
        # Initialize counter if first collision
        if base_hash not in self.collision_counters:
            self.collision_counters[base_hash] = 1
        
        self.collision_counters[base_hash] += 1
        return f"{base_hash}-{self.collision_counters[base_hash]}"
    
    def validate_ofx_id(self, ofx_id: Optional[str]) -> Optional[str]:
        """
        Validate and clean OFX transaction ID.
        
        Args:
            ofx_id: Original OFX transaction ID (may be None, empty, or whitespace)
            
        Returns:
            Cleaned OFX ID string, or None if invalid/empty
            
        Examples:
            >>> gen = TransactionIdGenerator()
            >>> gen.validate_ofx_id("  20240115001234567890  ")
            '20240115001234567890'
            >>> gen.validate_ofx_id("")
            None
            >>> gen.validate_ofx_id(None)
            None
        """
        if not ofx_id:
            return None
        
        cleaned = str(ofx_id).strip()
        if not cleaned or cleaned.isspace():
            return None
        
        return cleaned
    
    def generate_hash_components(self, date: str, payee: str, amount: Union[str, Decimal, float], mapped_account: str) -> Tuple[str, str]:
        """
        Generate hash components for debugging/testing purposes.
        
        Args:
            date: Transaction date
            payee: Transaction payee
            amount: Transaction amount
            mapped_account: Beancount account
            
        Returns:
            Tuple of (hash_input_string, sha256_hash)
        """
        clean_payee = str(payee) if payee else ""
        clean_amount = str(amount) if amount else "0"
        clean_account = str(mapped_account).strip()
        
        hash_input = f"{date}|{clean_payee}|{clean_amount}|{clean_account}"
        hash_output = hashlib.sha256(hash_input.encode('utf-8')).hexdigest()
        
        return hash_input, hash_output
    
    def reset(self):
        """Reset generator state (used_ids and collision_counters)."""
        self.used_ids.clear()
        self.collision_counters.clear()
    
    def get_stats(self) -> Dict[str, int]:
        """
        Get generator statistics for debugging/monitoring.
        
        Returns:
            Dictionary with generator statistics
        """
        return {
            'total_ids_generated': len(self.used_ids),
            'collision_count': len(self.collision_counters),
            'max_collision_suffix': max(self.collision_counters.values()) if self.collision_counters else 0
        }


def generate_single_transaction_id(date: str, 
                                 payee: str, 
                                 amount: Union[str, Decimal, float], 
                                 mapped_account: str) -> str:
    """
    Convenience function to generate a single transaction ID without state tracking.
    
    Use this when you don't need collision handling or are generating IDs for 
    separate, unrelated transactions.
    
    Args:
        date: Transaction date in YYYY-MM-DD format
        payee: Transaction payee/merchant name
        amount: Transaction amount
        mapped_account: Beancount account name
        
    Returns:
        64-character SHA256 hash string
        
    Example:
        >>> generate_single_transaction_id("2024-01-15", "GROCERY STORE", "-85.50", "Liabilities:CreditCard")
        'a1b2c3d4e5f6789012345678901234567890123456789012345678901234567890'
    """
    generator = TransactionIdGenerator()
    return generator.generate_id(date, payee, amount, mapped_account)


def validate_single_ofx_id(ofx_id: Optional[str]) -> Optional[str]:
    """
    Convenience function to validate a single OFX ID without instantiating generator.
    
    Args:
        ofx_id: OFX transaction ID to validate
        
    Returns:
        Cleaned OFX ID or None if invalid
        
    Example:
        >>> validate_single_ofx_id("  20240115001234567890  ")
        '20240115001234567890'
    """
    generator = TransactionIdGenerator()
    return generator.validate_ofx_id(ofx_id)


# Module-level constants for external use
HASH_INPUT_FORMAT = "{date}|{payee}|{amount}|{account}"
FALLBACK_PREFIX = "fallback_"
DUPLICATE_SUFFIX_FORMAT = "-dup-{counter}"
COLLISION_SUFFIX_FORMAT = "-{counter}"


if __name__ == "__main__":
    # Demo/test the generator
    generator = TransactionIdGenerator()
    
    print("Transaction ID Generator Demo")
    print("=" * 40)
    
    # Test normal transaction
    txn_id = generator.generate_id("2024-01-15", "GROCERY STORE", "-85.50", "Liabilities:CreditCard")
    print(f"Normal transaction ID: {txn_id}")
    
    # Test collision (same input)
    txn_id2 = generator.generate_id("2024-01-15", "GROCERY STORE", "-85.50", "Liabilities:CreditCard")
    print(f"Collision handling: {txn_id2}")
    
    # Test kept duplicate
    txn_id3 = generator.generate_id("2024-01-15", "GROCERY STORE", "-85.50", "Liabilities:CreditCard", is_kept_duplicate=True)
    print(f"Kept duplicate: {txn_id3}")
    
    # Test fallback
    txn_id4 = generator.generate_id("2024-01-15", "GROCERY STORE", "-85.50", "")
    print(f"Fallback ID: {txn_id4}")
    
    # Test OFX ID validation
    ofx_id = generator.validate_ofx_id("  20240115001234567890  ")
    print(f"Cleaned OFX ID: {ofx_id}")
    
    # Show stats
    stats = generator.get_stats()
    print(f"Generator stats: {stats}")
    
    # Show hash components
    hash_input, hash_output = generator.generate_hash_components("2024-01-15", "GROCERY STORE", "-85.50", "Liabilities:CreditCard")
    print(f"Hash input: {hash_input}")
    print(f"Hash output: {hash_output}")