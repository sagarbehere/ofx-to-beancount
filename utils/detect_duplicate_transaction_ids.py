#!/usr/bin/env python3
"""
Detect duplicate transaction_id metadata attributes in Beancount files.

This script reads a Beancount file and checks for duplicate transaction_id metadata
values across all transactions, providing a JSON summary of findings.
"""

import argparse
import json
import sys
from collections import defaultdict
from typing import Dict, List, Any
from decimal import Decimal

from beancount import loader
from beancount.core.data import Transaction


def convert_to_json_serializable(obj):
    """Convert objects to JSON serializable format."""
    if isinstance(obj, Decimal):
        return str(obj)
    elif isinstance(obj, dict):
        return {key: convert_to_json_serializable(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_to_json_serializable(item) for item in obj]
    else:
        return obj


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Detect duplicate transaction_id metadata attributes in Beancount files"
    )
    parser.add_argument(
        '-i', '--input-file',
        required=True,
        help="Path to the Beancount file to analyze"
    )
    parser.add_argument(
        '-q', '--quiet',
        action='store_true',
        help="Suppress parsing errors in the output"
    )
    parser.add_argument(
        '-f', '--output-format',
        choices=['text', 'json'],
        default='text',
        help="Output format: text (default) or json"
    )
    return parser.parse_args()


def analyze_transactions(entries, errors, quiet=False):
    """
    Analyze transactions for duplicate transaction_id metadata.
    
    Args:
        entries: List of Beancount entries
        errors: List of parsing errors
        quiet: If True, suppress parsing errors in output
        
    Returns:
        Dict containing analysis results
    """
    total_transactions = 0
    transactions_with_id = 0
    transactions_without_id = 0
    transaction_ids = defaultdict(list)
    
    # Analyze each transaction
    for entry in entries:
        if isinstance(entry, Transaction):
            total_transactions += 1
            
            # Check if transaction has transaction_id metadata
            transaction_id = entry.meta.get('transaction_id') if entry.meta else None
            
            if transaction_id:
                transactions_with_id += 1
                # Store transaction info with its ID
                transaction_info = {
                    'date': str(entry.date),
                    'payee': entry.payee or '',
                    'narration': entry.narration or '',
                    'flag': entry.flag,
                    'file': entry.meta.get('filename', 'unknown') if entry.meta else 'unknown',
                    'line': entry.meta.get('lineno', 0) if entry.meta else 0,
                    'transaction_id': transaction_id,
                    'meta': convert_to_json_serializable(dict(entry.meta)) if entry.meta else {},
                    'postings': [
                        {
                            'account': posting.account,
                            'units': str(posting.units) if posting.units else None,
                            'cost': str(posting.cost) if posting.cost else None,
                            'price': str(posting.price) if posting.price else None
                        }
                        for posting in entry.postings
                    ]
                }
                transaction_ids[transaction_id].append(transaction_info)
            else:
                transactions_without_id += 1
    
    # Find duplicates
    duplicates = {}
    for txn_id, transactions in transaction_ids.items():
        if len(transactions) > 1:
            duplicates[txn_id] = transactions
    
    result = {
        'total_transactions': total_transactions,
        'transactions_with_id': transactions_with_id,
        'transactions_without_id': transactions_without_id,
        'duplicate_count': len(duplicates),
        'duplicates': duplicates
    }
    
    # Only include parsing errors if not in quiet mode
    if not quiet:
        result['parsing_errors'] = [str(error) for error in errors] if errors else []
    
    return result


def format_text_output(results):
    """Format results as concise text output."""
    lines = []
    
    # Summary
    lines.append(f"Total transactions: {results['total_transactions']}")
    lines.append(f"With transaction_id: {results['transactions_with_id']}")
    lines.append(f"Without transaction_id: {results['transactions_without_id']}")
    lines.append(f"Duplicate transaction_ids found: {results['duplicate_count']}")
    
    # Show parsing errors if present and not suppressed
    if 'parsing_errors' in results and results['parsing_errors']:
        lines.append(f"Parsing errors: {len(results['parsing_errors'])}")
    
    # Show duplicates
    if results['duplicate_count'] > 0:
        lines.append("\nDuplicate transactions:")
        for txn_id, transactions in results['duplicates'].items():
            lines.append(f"\n  transaction_id: {txn_id} ({len(transactions)} occurrences)")
            for i, txn in enumerate(transactions, 1):
                file_info = f"{txn['file']}:{txn['line']}"
                description = f"{txn['date']} {txn['payee']} '{txn['narration']}'" if txn['narration'] else f"{txn['date']} {txn['payee']}"
                lines.append(f"    {i}. {description} [{file_info}]")
    else:
        lines.append("\nNo duplicate transaction_ids found.")
    
    return "\n".join(lines)


def main():
    """Main function."""
    args = parse_arguments()
    
    try:
        # Load the Beancount file
        entries, errors, _ = loader.load_file(args.input_file)
        
        # Analyze transactions
        results = analyze_transactions(entries, errors, quiet=args.quiet)
        
        # Output results in requested format
        if args.output_format == 'json':
            serializable_results = convert_to_json_serializable(results)
            print(json.dumps(serializable_results, indent=2))
        else:
            # Text format (default)
            print(format_text_output(results))
        
        # Exit with code 1 if duplicates found, 0 otherwise
        sys.exit(1 if results['duplicate_count'] > 0 else 0)
        
    except FileNotFoundError:
        if args.output_format == 'json':
            error_result = {
                'error': f"File not found: {args.input_file}",
                'total_transactions': 0,
                'transactions_with_id': 0,
                'transactions_without_id': 0,
                'duplicate_count': 0,
                'duplicates': {}
            }
            if not args.quiet:
                error_result['parsing_errors'] = []
            serializable_error_result = convert_to_json_serializable(error_result)
            print(json.dumps(serializable_error_result, indent=2))
        else:
            print(f"Error: File not found: {args.input_file}")
        sys.exit(1)
        
    except Exception as e:
        if args.output_format == 'json':
            error_result = {
                'error': f"Error processing file: {str(e)}",
                'total_transactions': 0,
                'transactions_with_id': 0,
                'transactions_without_id': 0,
                'duplicate_count': 0,
                'duplicates': {}
            }
            if not args.quiet:
                error_result['parsing_errors'] = []
            serializable_error_result = convert_to_json_serializable(error_result)
            print(json.dumps(serializable_error_result, indent=2))
        else:
            print(f"Error: Error processing file: {str(e)}")
        sys.exit(1)


if __name__ == '__main__':
    main()