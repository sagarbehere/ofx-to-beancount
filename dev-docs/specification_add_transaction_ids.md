# Add Transaction IDs Utility Script Specification

## Overview

The `add_transaction_ids.py` utility script processes existing Beancount files to add SHA256-based transaction IDs as metadata to transactions that don't already have them. This script enables users to retroactively add transaction tracking capabilities to existing Beancount files.

## Script Purpose

- **Input**: Existing Beancount file without transaction_id metadata
- **Output**: New Beancount file with transaction_id metadata added to applicable transactions
- **Safety**: Never modifies input file, requires non-existing output file to prevent data loss

## Command Line Interface

```bash
python add_transaction_ids.py -i input.beancount -o output.beancount
```

### Arguments

- `-i, --input` (required): Path to input Beancount file to process
- `-o, --output` (required): Path to output Beancount file to create

### Argument Validation

- **Input file**: Must exist and be readable
- **Output file**: Must NOT exist (script stops with error if output file exists)
- **Both arguments**: Required, script stops with error if either is missing

## Processing Logic

### Transaction ID Generation

#### Hash Algorithm
- **Algorithm**: SHA256
- **Input Format**: `"{date}|{payee}|{amount} {currency}|{selected_account}"`
- **Output**: 64-character hexadecimal string

#### Hash Input Examples
```
"2024-01-15|GROCERY STORE|-85.50 USD|Liabilities:Chase:SapphireReserve"
"2024-01-16||-4.50 USD|Assets:Checking"  # Empty payee
"2024-01-17|Coffee Shop|12.75 EUR|Liabilities:Amex:Card"
```

### Account Selection Priority

For determining which account to use in the hash calculation:

1. **Priority 1**: Assets: or Liabilities: accounts
   - Look for any posting with account starting with `Assets:` or `Liabilities:`
   - If multiple found, use the first one encountered
   - Use the exact amount from that specific posting

2. **Priority 2**: Income: accounts
   - If no Assets/Liabilities accounts found, look for accounts starting with `Income:`
   - Use the first Income account found
   - Use the exact amount from that specific posting

3. **Priority 3**: First posting account
   - If no Assets/Liabilities/Income accounts found, use the account from the first posting
   - Use the exact amount from the first posting

### Amount Formatting

- **Include sign**: Use exact amount including positive/negative sign
- **Include currency**: Format as "{amount} {currency}" (e.g., "-85.50 USD")
- **Decimal precision**: Preserve original precision from Beancount file

### Payee Handling

- **Present payee**: Use as-is in hash calculation
- **Missing payee**: Use empty string in hash calculation
- **Empty payee**: Use empty string in hash calculation

## File Processing Specifications

### Input File Processing

#### Directive Handling
- **Transaction directives**: Process for potential transaction_id addition
- **All other directives**: Pass through unchanged (open, close, balance, price, etc.)
- **Comments**: Preserve all comments in original positions
- **Formatting**: Preserve original spacing and structure as much as possible

#### Transaction Processing Rules
1. **Parse transaction**: Extract date, payee, and all postings
2. **Check existing metadata**: Look for existing `transaction_id` metadata field
3. **Skip if exists**: If `transaction_id` already present, pass transaction through unchanged
4. **Generate ID**: If no `transaction_id`, compute SHA256 hash using algorithm above
5. **Add metadata**: Insert `transaction_id` metadata at top of metadata section

### Output File Generation

#### File Structure
- **Directive order**: Preserve exact order of all directives from input file
- **Spacing**: Maintain original spacing between directives
- **Comments**: Preserve all comments in original positions
- **Formatting**: Keep original formatting for all non-modified transactions

#### Metadata Placement
```beancount
2024-01-15 * "GROCERY STORE" "Weekly shopping"
  transaction_id: "a1b2c3d4e5f6789012345678901234567890123456789012345678901234567890"
  category: "food"          ; Existing metadata preserved
  receipt: "receipt123"     ; Original metadata order maintained
  Assets:Checking          -85.50 USD
  Expenses:Food:Groceries   85.50 USD
```

#### Metadata Rules
- **Placement**: transaction_id placed at top of metadata section
- **Indentation**: Use 2-space indentation to match Beancount standards
- **Format**: `transaction_id: "64-character-hash"`
- **Preservation**: All existing metadata preserved in original order

## Error Handling

### File Errors

#### Input File Issues
- **File not found**: Stop with error "Input file does not exist: {path}"
- **Permission denied**: Stop with error "Cannot read input file: {path}"
- **Not a file**: Stop with error "Input path is not a file: {path}"

#### Output File Issues
- **File exists**: Stop with error "Output file already exists: {path}. Will not overwrite existing file."
- **Permission denied**: Stop with error "Cannot create output file: {path}"
- **Directory doesn't exist**: Stop with error "Output directory does not exist: {path}"

### Parsing Errors

#### Malformed Beancount Syntax
- **Invalid syntax**: Stop with error "Malformed Beancount syntax at line {line}: {details}"
- **Parsing failure**: Stop with error "Failed to parse Beancount file: {details}"
- **Encoding issues**: Stop with error "Cannot read file encoding: {details}"

#### Missing Required Fields
- **No date**: Stop with error "Transaction missing date at line {line}"
- **No postings**: Stop with error "Transaction has no postings at line {line}"
- **Invalid posting**: Stop with error "Invalid posting format at line {line}: {details}"

### Processing Errors

#### Account Selection Failures
- **No accounts found**: Stop with error "Transaction has no valid accounts at line {line}"
- **Amount parsing**: Stop with error "Cannot parse amount for transaction at line {line}: {details}"
- **Currency missing**: Stop with error "Posting missing currency at line {line}"

#### Hash Generation Errors
- **Encoding error**: Stop with error "Cannot encode transaction data for hashing at line {line}"
- **Hash computation**: Stop with error "Hash generation failed for transaction at line {line}"

## Success Output

### Summary Information
Upon successful completion, display:
```
Transaction ID Addition Complete
===============================
Input file: /path/to/input.beancount
Output file: /path/to/output.beancount

Processing Summary:
- Total directives processed: 450
- Transaction directives found: 150
- Transactions already with IDs: 7
- Transaction IDs added: 143
- Other directives preserved: 300

All transactions now have transaction_id metadata.
```

### Progress Indication
For large files (>1000 transactions), optionally show progress:
```
Processing transactions... [143/150] (95%)
```

## Implementation Requirements

### Dependencies
- **beancount**: For parsing and handling Beancount files
- **hashlib**: For SHA256 hash generation
- **argparse**: For command-line argument handling
- **sys**: For error exit codes
- **pathlib**: For file path handling

### Python Version
- **Minimum**: Python 3.8+ (to match main project requirements)

### Code Structure
```python
add_transaction_ids.py
├── main()                    # Entry point and argument parsing
├── validate_arguments()      # Validate input/output file arguments
├── process_beancount_file()  # Main file processing logic
├── process_transaction()     # Individual transaction processing
├── select_account()          # Account selection priority logic
├── generate_transaction_id() # SHA256 hash generation
├── format_transaction()      # Output formatting with metadata
└── print_summary()          # Success summary output
```

### Error Exit Codes
- **0**: Success
- **1**: File errors (missing input, existing output, permissions)
- **2**: Parsing errors (malformed Beancount, invalid syntax)
- **3**: Processing errors (missing fields, hash generation)
- **4**: Argument errors (missing required arguments)

## Testing Requirements

### Unit Tests
1. **Hash generation**: Verify SHA256 computation with known inputs
2. **Account selection**: Test priority logic with various account combinations
3. **Metadata insertion**: Verify proper placement and formatting
4. **Error handling**: Test all error conditions and exit codes

### Integration Tests
1. **Small Beancount files**: Process files with 5-10 transactions
2. **Large Beancount files**: Process files with 1000+ transactions
3. **Edge cases**: Empty payees, multiple currencies, complex transactions
4. **Preservation**: Verify original formatting and comments preserved

### Test Data
- **Valid Beancount files**: Various transaction types and metadata
- **Invalid Beancount files**: Malformed syntax, missing fields
- **Edge case files**: Empty payees, no asset/liability accounts
- **Already processed files**: Transactions with existing transaction_ids

## Security Considerations

### File Safety
- **No overwrites**: Never modify existing files
- **Input preservation**: Original file remains completely untouched
- **Atomic operations**: Create output file completely or not at all

### Data Integrity
- **Hash determinism**: Same transaction always produces same ID
- **Metadata preservation**: All original metadata maintained
- **Structure preservation**: File structure and formatting maintained

## Usage Examples

### Basic Usage
```bash
# Add transaction IDs to existing file
python add_transaction_ids.py -i my_accounts.beancount -o my_accounts_with_ids.beancount
```

### Error Cases
```bash
# Output file exists - will fail with error
python add_transaction_ids.py -i input.beancount -o existing_file.beancount
# Error: Output file already exists: existing_file.beancount

# Input file missing - will fail with error  
python add_transaction_ids.py -i missing.beancount -o output.beancount
# Error: Input file does not exist: missing.beancount
```

### Success Case Output
```bash
$ python add_transaction_ids.py -i accounts.beancount -o accounts_with_ids.beancount

Transaction ID Addition Complete
===============================
Input file: accounts.beancount
Output file: accounts_with_ids.beancount

Processing Summary:
- Total directives processed: 1,250
- Transaction directives found: 800
- Transactions already with IDs: 0
- Transaction IDs added: 800
- Other directives preserved: 450

All transactions now have transaction_id metadata.
```

## Future Enhancements

### Potential Future Features
1. **Batch processing**: Process multiple files at once
2. **In-place update**: Optional flag to modify input file directly
3. **Dry run mode**: Preview changes without creating output file
4. **Custom hash algorithms**: Support for different hash algorithms
5. **Selective processing**: Process only transactions matching criteria
6. **Validation mode**: Verify existing transaction_ids are correct

### Integration Opportunities
1. **Main project integration**: Include as part of main OFX converter toolkit
2. **CI/CD integration**: Automated processing of Beancount files
3. **Beancount plugin**: Develop as Beancount plugin for automatic ID generation