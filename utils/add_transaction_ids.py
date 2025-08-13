#!/usr/bin/env python3
"""
Add transaction_id metadata to existing Beancount transactions.

This utility script processes existing Beancount files and adds SHA256-based
transaction_id metadata to all transaction directives that don't already have them.

The transaction_id is generated using the same logic as the main OFX converter:
SHA256 hash of: "{date}|{payee}|{amount} {currency}|{account}"

Account selection priority:
1. Assets or Liabilities accounts (first found)
2. Income accounts (first found) 
3. First posting account

Usage:
    python utils/add_transaction_ids.py -i input.beancount -o output.beancount
    python utils/add_transaction_ids.py --input input.beancount --output output.beancount

Safety Features:
- Never overwrites existing files (output file must not exist)
- Preserves original file structure and formatting
- Skips transactions that already have transaction_id metadata
- Provides detailed processing statistics

Author: OFX to Beancount Converter
License: Same as parent project
"""

import argparse
import sys
from pathlib import Path
from typing import Dict, Tuple, Any, List
from beancount import loader
from beancount.core import data
from beancount.parser import printer
import io

# Import our reusable transaction ID generator
# Add parent directory to path to access core module
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.transaction_id_generator import generate_single_transaction_id, TransactionIdValidationError


# Exit codes for different error conditions
EXIT_SUCCESS = 0
EXIT_FILE_ERROR = 1
EXIT_PARSE_ERROR = 2
EXIT_PROCESSING_ERROR = 3
EXIT_ARGUMENT_ERROR = 4


class ProcessingError(Exception):
    """Custom exception for processing errors."""
    pass


def main():
    """Entry point with argument parsing and main workflow."""
    parser = argparse.ArgumentParser(
        description="Add transaction_id metadata to existing Beancount files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python utils/add_transaction_ids.py -i my_accounts.beancount -o my_accounts_with_ids.beancount
  python utils/add_transaction_ids.py --input ledger.beancount --output ledger_processed.beancount

Safety Features:
  - Never overwrites existing output files
  - Preserves original file structure and formatting  
  - Skips transactions that already have transaction_id metadata
  - Provides detailed processing statistics

The transaction_id is generated using SHA256 hash of:
  "{date}|{payee}|{amount} {currency}|{account}"

Account selection priority:
  1. Assets or Liabilities accounts (first found)
  2. Income accounts (first found)
  3. First posting account
        """
    )
    
    parser.add_argument(
        '-i', '--input',
        required=True,
        type=Path,
        help='Input Beancount file (must exist and be readable)'
    )
    
    parser.add_argument(
        '-o', '--output', 
        required=True,
        type=Path,
        help='Output Beancount file (must not exist for safety)'
    )
    
    parser.add_argument(
        '--force',
        action='store_true',
        help='Allow overwriting existing output file (use with caution!)'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be processed without writing output file'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose output showing processing details'
    )
    
    try:
        args = parser.parse_args()
        
        # Validate arguments
        validate_arguments(args)
        
        if args.dry_run:
            print("🔍 DRY RUN MODE - No files will be modified")
            
        # Process the file
        stats = process_beancount_file(args.input, args.output, args.dry_run, args.verbose)
        
        # Print summary
        print_summary(stats, args.input, args.output, args.dry_run)
        
        sys.exit(EXIT_SUCCESS)
        
    except KeyboardInterrupt:
        print("\n⚠️  Processing interrupted by user", file=sys.stderr)
        sys.exit(EXIT_PROCESSING_ERROR)
    except Exception as e:
        handle_error("PROCESSING_ERROR", str(e), EXIT_PROCESSING_ERROR)


def validate_arguments(args) -> None:
    """Validate input/output file arguments with safety checks."""
    
    # Check input file exists and is readable
    if not args.input.exists():
        handle_error("FILE_ERROR", f"Input file does not exist: {args.input}", EXIT_FILE_ERROR)
    
    if not args.input.is_file():
        handle_error("FILE_ERROR", f"Input path is not a file: {args.input}", EXIT_FILE_ERROR)
    
    try:
        with open(args.input, 'r', encoding='utf-8') as f:
            # Try to read first line to check readability
            f.readline()
    except PermissionError:
        handle_error("FILE_ERROR", f"Input file not readable: {args.input}", EXIT_FILE_ERROR)
    except UnicodeDecodeError:
        handle_error("FILE_ERROR", f"Input file contains invalid UTF-8: {args.input}", EXIT_FILE_ERROR)
    
    # Check output file safety (unless force or dry-run)
    if not args.dry_run:
        if args.output.exists() and not args.force:
            handle_error(
                "FILE_ERROR", 
                f"Output file already exists: {args.output}. Use --force to overwrite or choose a different output file.",
                EXIT_FILE_ERROR
            )
        
        # Test if output file is writable by trying to create it
        try:
            # Create parent directories if needed
            args.output.parent.mkdir(parents=True, exist_ok=True)
            
            # Test write access (create empty file then remove it)
            if not args.output.exists():
                with open(args.output, 'w', encoding='utf-8') as f:
                    pass
                args.output.unlink()  # Remove test file
            else:
                # File exists and --force was used, test if writable
                with open(args.output, 'a', encoding='utf-8') as f:
                    pass
                    
        except PermissionError:
            handle_error("FILE_ERROR", f"Output file not writable: {args.output}", EXIT_FILE_ERROR)
        except Exception as e:
            handle_error("FILE_ERROR", f"Cannot create output file: {args.output} - {e}", EXIT_FILE_ERROR)


def process_beancount_file(input_path: Path, output_path: Path, dry_run: bool = False, verbose: bool = False) -> Dict[str, int]:
    """
    Main file processing logic returning statistics.
    
    Args:
        input_path: Path to input Beancount file
        output_path: Path to output Beancount file
        dry_run: If True, don't write output file
        verbose: If True, show processing details
        
    Returns:
        Dictionary with processing statistics
    """
    print(f"📖 Loading Beancount file: {input_path}")
    
    try:
        # Load and parse Beancount file
        entries, errors, options_map = loader.load_file(str(input_path))
        
        if errors:
            print(f"⚠️  {len(errors)} parsing warnings in input file:")
            for error in errors[:5]:  # Show first 5 errors
                print(f"   {error}")
            if len(errors) > 5:
                print(f"   ... and {len(errors) - 5} more warnings")
                
    except Exception as e:
        handle_error("PARSE_ERROR", f"Failed to parse Beancount file: {e}", EXIT_PARSE_ERROR)
    
    # Process entries
    stats = {
        'total_entries': len(entries),
        'transaction_entries': 0,
        'transactions_processed': 0,
        'transactions_skipped': 0,
        'transactions_with_existing_ids': 0,
        'processing_errors': 0
    }
    
    processed_entries = []
    
    print(f"🔄 Processing {len(entries)} entries...")
    
    for entry in entries:
        if isinstance(entry, data.Transaction):
            stats['transaction_entries'] += 1
            
            try:
                processed_entry, was_modified = process_transaction(entry, verbose)
                processed_entries.append(processed_entry)
                
                if was_modified:
                    stats['transactions_processed'] += 1
                    if verbose:
                        print(f"   ✅ Added ID to: {entry.date} {entry.payee or '(no payee)'}")
                else:
                    if has_transaction_id(entry):
                        stats['transactions_with_existing_ids'] += 1
                        if verbose:
                            print(f"   ⏭️  Skipped (has ID): {entry.date} {entry.payee or '(no payee)'}")
                    else:
                        stats['transactions_skipped'] += 1
                        if verbose:
                            print(f"   ⚠️  Skipped (error): {entry.date} {entry.payee or '(no payee)'}")
                        
            except ProcessingError as e:
                # ProcessingError indicates a fatal data quality issue - terminate immediately
                handle_error("DATA_VALIDATION_ERROR", str(e), EXIT_PROCESSING_ERROR)
            except Exception as e:
                stats['processing_errors'] += 1
                processed_entries.append(entry)  # Keep original entry
                print(f"   ❌ Error processing transaction {entry.date}: {e}")
                if verbose:
                    import traceback
                    traceback.print_exc()
        else:
            # Non-transaction entry, keep as-is
            processed_entries.append(entry)
    
    # Write output file
    if not dry_run:
        try:
            print(f"💾 Writing output file: {output_path}")
            
            # Use beancount printer to maintain formatting
            output_content = io.StringIO()
            printer.print_entries(processed_entries, file=output_content)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(output_content.getvalue())
                
        except Exception as e:
            handle_error("PROCESSING_ERROR", f"Failed to write output file: {e}", EXIT_PROCESSING_ERROR)
    
    return stats


def process_transaction(txn: data.Transaction, verbose: bool = False) -> Tuple[data.Transaction, bool]:
    """
    Process individual transaction, return (modified_txn, was_modified).
    
    Args:
        txn: Beancount transaction to process
        verbose: If True, show detailed processing info
        
    Returns:
        Tuple of (processed_transaction, was_modified_flag)
    """
    # Skip if transaction already has transaction_id metadata
    if has_transaction_id(txn):
        return txn, False
    
    try:
        # Select account and amount using priority logic
        account, amount_currency = select_account_for_hash(txn)
        
        # Generate transaction ID using strict validation
        # This will raise TransactionIdValidationError if any critical field is invalid
        transaction_id = generate_single_transaction_id(
            date=txn.date.strftime('%Y-%m-%d'),
            payee=txn.payee or "",
            amount=amount_currency,
            mapped_account=account,
            narration=txn.narration or "",
            strict_validation=True
        )
        
        # Add transaction_id metadata
        modified_txn = add_transaction_id_metadata(txn, transaction_id)
        
        if verbose:
            print(f"      Generated ID: {transaction_id[:16]}... for account: {account}")
        
        return modified_txn, True
        
    except TransactionIdValidationError as e:
        # Convert to ProcessingError with file location context
        filename = txn.meta.get('filename', 'unknown file') if txn.meta else 'unknown file'
        lineno = txn.meta.get('lineno', 'unknown line') if txn.meta else 'unknown line'
        location = f"{filename}:{lineno}"
        
        # Add specific guidance for common payee/narration field issue
        if "Both payee and narration fields are empty" in str(e):
            detailed_message = (
                f"Transaction at {location} has both empty payee and narration fields. "
                f"At least one of these fields must contain meaningful content for transaction ID generation. "
                f"Please ensure the transaction has either a proper payee or narration."
            )
        else:
            detailed_message = f"Transaction at {location}: {e}"
        
        raise ProcessingError(detailed_message)
    except Exception as e:
        if verbose:
            print(f"      Error: {e}")
        return txn, False


def select_account_for_hash(txn: data.Transaction) -> Tuple[str, str]:
    """
    Select account and amount using priority logic.
    
    Priority order:
    1. Assets or Liabilities accounts (first found)
    2. Income accounts (first found) 
    3. First posting account
    
    Args:
        txn: Beancount transaction
        
    Returns:
        Tuple of (account_name, amount_with_currency)
        
    Raises:
        ProcessingError: If transaction has no postings
    """
    if not txn.postings:
        raise ProcessingError("Transaction has no postings")
    
    # Priority 1: Assets or Liabilities accounts
    for posting in txn.postings:
        if posting.account.startswith(('Assets:', 'Liabilities:')):
            if posting.units:
                amount_str = f"{posting.units.number} {posting.units.currency}"
                return posting.account, amount_str
    
    # Priority 2: Income accounts  
    for posting in txn.postings:
        if posting.account.startswith('Income:'):
            if posting.units:
                amount_str = f"{posting.units.number} {posting.units.currency}"
                return posting.account, amount_str
    
    # Priority 3: First posting with units
    for posting in txn.postings:
        if posting.units:
            amount_str = f"{posting.units.number} {posting.units.currency}"
            return posting.account, amount_str
    
    # Fallback: first posting even without units
    first_posting = txn.postings[0]
    amount_str = "0 USD"  # Default if no units
    return first_posting.account, amount_str


def has_transaction_id(txn: data.Transaction) -> bool:
    """Check if transaction already has transaction_id metadata."""
    return (hasattr(txn, 'meta') and 
            txn.meta is not None and 
            'transaction_id' in txn.meta)


def add_transaction_id_metadata(txn: data.Transaction, transaction_id: str) -> data.Transaction:
    """
    Add transaction_id as first metadata entry, preserving existing metadata.
    
    Args:
        txn: Original transaction
        transaction_id: Generated transaction ID
        
    Returns:
        New transaction with transaction_id metadata added
    """
    # Start with existing metadata or empty dict
    new_meta = txn.meta.copy() if txn.meta else {}
    
    # Add transaction_id at beginning (will appear first when printed)
    # Create new dict with transaction_id first, then existing metadata
    updated_meta = {'transaction_id': transaction_id}
    updated_meta.update(new_meta)
    
    # Create new transaction with updated metadata
    return txn._replace(meta=updated_meta)


def print_summary(stats: Dict[str, int], input_path: Path, output_path: Path, dry_run: bool) -> None:
    """Print success summary with processing statistics."""
    print("\n" + "=" * 60)
    print("📊 PROCESSING SUMMARY")
    print("=" * 60)
    
    print(f"Input file:  {input_path}")
    if not dry_run:
        print(f"Output file: {output_path}")
    else:
        print(f"Output file: {output_path} (NOT CREATED - dry run)")
    
    print(f"\nTotal entries processed: {stats['total_entries']:,}")
    print(f"Transaction entries found: {stats['transaction_entries']:,}")
    print(f"Transactions with IDs added: {stats['transactions_processed']:,}")
    print(f"Transactions already had IDs: {stats['transactions_with_existing_ids']:,}")
    print(f"Transactions skipped (errors): {stats['transactions_skipped']:,}")
    
    if stats['processing_errors'] > 0:
        print(f"⚠️  Processing errors: {stats['processing_errors']:,}")
    
    success_rate = 0
    if stats['transaction_entries'] > 0:
        processable = stats['transaction_entries'] - stats['transactions_with_existing_ids']
        if processable > 0:
            success_rate = (stats['transactions_processed'] / processable) * 100
    
    print(f"\nSuccess rate: {success_rate:.1f}% of processable transactions")
    
    if not dry_run and stats['transactions_processed'] > 0:
        print(f"✅ Successfully added transaction_id metadata to {stats['transactions_processed']} transactions!")
    elif dry_run:
        print(f"🔍 DRY RUN: Would add transaction_id metadata to {stats['transactions_processed']} transactions")
    elif stats['transactions_processed'] == 0 and stats['transactions_with_existing_ids'] > 0:
        print("ℹ️  All transactions already have transaction_id metadata - nothing to do!")
    else:
        print("⚠️  No transactions were processed")
    
    print("=" * 60)


def handle_error(error_type: str, message: str, exit_code: int) -> None:
    """Standard error handling with proper exit codes."""
    print(f"❌ {error_type}: {message}", file=sys.stderr)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()