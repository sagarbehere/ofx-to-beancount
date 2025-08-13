# OFX to Beancount Converter - Project Specification

## Overview

This project creates an application that reads financial transactions from OFX (Open Financial Exchange) files and converts them to Beancount format with intelligent categorization. The system provides both API and CLI interfaces for processing transactions with machine learning-based categorization and interactive user verification.

## Architecture

### Clean API/Core Separation
The system employs a clean separation between the API layer and core processing:

- **CLI Client**: Lightweight, sends file paths and receives/sends JSON transaction data
- **API Layer**: Handles HTTP communication using generic JSON-based models (`TransactionAPI`, `PostingAPI`)  
- **Server Core**: Converts API models to standard Beancount objects for all transaction processing
- **Output Generation**: Uses Beancount's native printer to ensure consistent formatting

### Transaction ID Generation
All transaction ID generation uses standard `beancount.core.data.Transaction` objects to guarantee consistency across:
- Main OFX converter output
- `add_transaction_ids.py` utility script  
- Any other tools using the `transaction_id_generator.py` module

This ensures perfect transaction ID consistency regardless of the processing path.

## Core Functionality

### 1. OFX File Processing
- Parse OFX files to extract transaction data (date, payee, memo, amount)
- Extract account information (institution, account type, account ID)
- Display file statistics (date range, balance, transaction count)
- Support multiple currencies from OFX files

### 2. Account Mapping
- Map OFX account data to Beancount account names using configuration
- Support Assets, Liabilities, and Equity account types
- Allow interactive account name correction/override
- Currency detection and override capabilities

### 3. Transaction Categorization
- Use machine learning (Random Forest classifier) with TF-IDF vectorization
- Train on existing Beancount transaction data (payee + memo as features)
- Auto-categorize transactions to appropriate expense/income/equity accounts
- Support multi-posting transaction splits
- Validate posting amount signs based on account types

### 4. Duplicate Detection
- Compare incoming transactions with existing output file transactions
- Identify potential duplicates using date, payee, amount, and account
- **Detection Timing**: Perform duplicate detection during `/transactions/categorize` API call
- **Requirements**: Always runs since output file is now required
- **Graceful Degradation**: If output file doesn't exist or duplicate detection fails, silently continue without duplicate detection and notify user via system messages
- **Detection Criteria**: Two transactions are considered duplicates if they match:
  - Date (exact match)
  - Source account (exact match)
  - Amount (exact match)
  - Payee (fuzzy match > 90% similarity using rapidfuzz library)
- **User Interface**: Potential duplicates displayed with warning "⚠️ Potential duplicate of YYYY-MM-DD PAYEE AMOUNT"
- **Resolution**: Users can skip duplicates using 'k' command during interactive review

### 5. Interactive User Interface
- CLI with prompt_toolkit for rich interaction
- Fuzzy account name completion
- Transaction-by-transaction review and correction
- Transaction splitting interface
- Note/narration entry for each transaction

#### CLI Navigation Controls
- **Enter key**: Accept suggested category
- **Up/Down arrows**: Context-dependent navigation
  - During categorization: Navigate account suggestions
  - During review: Navigate between previously processed transactions for editing
- **Interactive Commands**:
  - **s**: Split transaction into multiple categories
  - **k**: Skip transaction (exclude from output) - used for duplicates and unwanted transactions
  - **p**: Previous transaction (navigate backwards)
  - **q**: Quit review process
- **Standard editing**: Delete and backspace keys function normally
- **Batch mode skeleton**: Empty implementation prepared for future development
- **Duplicate Handling**: Potential duplicates shown with warning after transaction details, users skip with 'k' command

## System Architecture

### API Layer (FastAPI)
Core business logic exposed via REST API for local use, optimized for minimal data transfer:

#### Endpoints:

##### `POST /session/initialize`
**Purpose**: Single call to set up processing session with OFX parsing, account mapping, and ML training
**Input**:
```json
{
  "ofx_file_path": "/path/to/file.ofx",
  "config_file_path": "/path/to/config.yaml",
  "training_file_path": "/path/to/training.beancount",
  "account_file_path": "/path/to/accounts.beancount",
  "output_file_path": "/path/to/output.beancount"
}
```
**Output**:
```json
{
  "session_id": "uuid-string",
  "ofx_stats": {
    "transaction_count": 150,
    "date_range": {"start": "2024-01-01", "end": "2024-03-31"},
    "balance": 1250.50,
    "currency": "USD"
  },
  "detected_account": {
    "account": "Liabilities:Chase:SapphireReserve", 
    "currency": "USD",
    "confidence": 0.95
  },
  "valid_accounts": ["Assets:Checking", "Expenses:Food", "Expenses:Transport"],
  "classifier_trained": true,
  "training_data_count": 1200,
  "system_messages": [
    {
      "level": "info",
      "message": "Session initialized successfully"
    }
  ]
}
```

##### `POST /transactions/categorize`
**Purpose**: Get all transactions with ML categorization and duplicate detection in one call

**Duplicate Detection**: Runs automatically since output file is now required. If duplicate detection fails, continues without duplicate detection and includes appropriate system message.
**Input**:
```json
{
  "session_id": "uuid-string",
  "confirmed_account": "Liabilities:Chase:SapphireReserve",
  "confirmed_currency": "USD"
}
```
**Output**:
```json
{
  "transactions": [
    {
      "id": "a1b2c3d4e5f6789012345678901234567890123456789012345678901234567890",
      "date": "2024-01-15", 
      "payee": "GROCERY STORE",
      "memo": "FOOD PURCHASE",
      "amount": -85.50,
      "currency": "USD",
      "suggested_category": "Expenses:Food:Groceries",
      "confidence": 0.85,
      "is_potential_duplicate": false,
      "duplicate_details": {
        "existing_transaction_id": "z9y8x7w6v5u4t3s2r1q0p9o8n7m6l5k4j3h2g1f0e9d8c7b6a5948372615049382",
        "similarity_score": 0.95,
        "match_criteria": ["date", "amount", "account", "payee"],
        "existing_transaction_date": "2024-01-15",
        "existing_transaction_payee": "GROCERY STORE",
        "existing_transaction_amount": -85.50
      }
    }
  ],
  "total_count": 150,
  "high_confidence_count": 120,
  "duplicate_count": 3,
  "system_messages": [
    {
      "level": "warning",
      "message": "Duplicate detection unavailable - output file not found"
    }
  ]
}
```

##### `POST /transactions/update-batch` 
**Purpose**: Update multiple transactions after interactive user review
**Input**:
```json
{
  "session_id": "uuid-string",
  "updates": [
    {
      "transaction_id": "a1b2c3d4e5f6789012345678901234567890123456789012345678901234567890",
      "confirmed_category": "Expenses:Food:Groceries", 
      "narration": "Weekly grocery shopping",
      "splits": null
    },
    {
      "transaction_id": "b2c3d4e5f6789012345678901234567890123456789012345678901234567890ab",
      "confirmed_category": null,
      "action": "skip",
      "reason": "duplicate"
    },
    {
      "transaction_id": "c3d4e5f6789012345678901234567890123456789012345678901234567890abc1",
      "confirmed_category": "Expenses:Entertainment",
      "narration": "Movie tickets",
      "splits": [
        {
          "account": "Expenses:Entertainment:Movies",
          "amount": 25.00,
          "currency": "USD"
        },
        {
          "account": "Expenses:Food:Snacks", 
          "amount": 15.50,
          "currency": "USD"
        }
      ]
    }
  ]
}
```
**Output**:
```json
{
  "updated_count": 45,
  "skipped_count": 2,
  "split_count": 3,
  "validation_errors": [
    {
      "transaction_id": "d4e5f6789012345678901234567890123456789012345678901234567890abc12",
      "error": "Postings do not balance",
      "details": "Sum: 0.01 USD"
    }
  ],
  "system_messages": [
    {
      "level": "info",
      "message": "All transactions processed successfully"
    }
  ]
}
```

##### `POST /export/beancount`
**Purpose**: Generate final Beancount output with validated transactions
**Input**:
```json
{
  "session_id": "uuid-string", 
  "output_mode": "append",
  "output_file_path": "/path/to/output.beancount"
}
```
**Output**:
```json
{
  "transactions_exported": 43,
  "file_path": "/path/to/output.beancount", 
  "summary": {
    "total_amount": 2500.75,
    "currency": "USD",
    "categories": {
      "Expenses:Food": 450.25,
      "Expenses:Transport": 125.50,
      "Expenses:Entertainment": 75.00
    },
    "date_range": {"start": "2024-01-01", "end": "2024-03-31"}
  },
  "beancount_preview": "2024-01-15 * \"GROCERY STORE\" \"Weekly grocery shopping\"\n  transaction_id: \"a1b2c3d4e5f6789012345678901234567890123456789012345678901234567890\"\n  ofx_id: \"20240115001234567890\"\n  Expenses:Food:Groceries           85.50 USD\n  Liabilities:Chase:SapphireReserve -85.50 USD\n\n...",
  "system_messages": [
    {
      "level": "info",
      "message": "Export completed successfully"
    }
  ]
}
```

### CLI Client
Python command-line interface using the API:
- **File Path Coordination**: CLI sends all file paths to server; no client-side file parsing
- **Interactive prompts with prompt_toolkit**
- **Fuzzy completion for account names** using `FuzzyWordCompleter` from prompt_toolkit
- **Transaction review and editing interface**
- **Progress tracking and error handling**
- **System Message Display**: CLI displays all system messages (warnings/errors) from API responses to user
- **Duplicate Notification**: Potential duplicates shown as warning line after transaction details: "⚠️ Potential duplicate of YYYY-MM-DD PAYEE AMOUNT"
- **Server Management**: CLI automatically starts/stops API server unless `--server-only` mode is used
- **Connection Management**: CLI maintains persistent connection to API throughout entire workflow
- **Server-Only Mode**: `--server-only` flag runs only the API server for GUI client use, but still validates all required files via command line arguments
- **Server Startup**: When CLI starts API server automatically, it waits for server to be ready before proceeding with workflow
- **Error Recovery**: No session recovery - users must restart CLI if API server crashes
- **Graceful Error Handling**: When duplicate detection is unavailable, displays "Note: Duplicate detection unavailable"

### Data Models

#### Transaction Data Structure:
```python
@dataclass
class Transaction:
    date: str  # ISO format YYYY-MM-DD
    payee: str
    memo: str
    amount: Decimal
    currency: str
    account: str  # Source account (from OFX)
    categorized_accounts: List[Posting]  # Target accounts
    narration: str  # User-entered note
    is_split: bool
    original_ofx_id: str

@dataclass
class Posting:
    account: str
    amount: Decimal
    currency: str
```

## Configuration

### Configuration File Format
- **YAML format** for all configuration files
- **Required configuration file**: System must stop and notify user if configuration file is missing (specified via `-c`)
- **Optional file path specification**: File paths can be specified in config file and overridden by CLI arguments
- **Configuration Location**: No default location - must be specified via `-c` command-line option
- **Single Configuration**: Only one configuration file format supported
- **Account validation**: System must validate that configured account mappings reference accounts that exist in the provided Beancount accounts file. If validation fails, the program must warn the user and stop execution (not proceed)
- **Interactive override**: Users can adjust account names interactively during processing
- **Backward compatibility**: Existing config files without new optional sections continue to work unchanged

### Sample Configuration Structure
```yaml
# Optional file paths - can be overridden by command line arguments
files:
  input_file: "/path/to/input.ofx"
  learning_data_file: "/path/to/training.beancount"
  output_file: "/path/to/output.beancount"
  account_file: "/path/to/accounts.beancount"

# Optional server settings - can be overridden by command line arguments
server:
  port_num: 8000
  server_only: false

# Required account mappings
accounts:
  mappings:
    - institution: "AMEX"
      account_type: ""
      account_id: "9OIB5AB8SY32XLB|12007"
      beancount_account: "Liabilities:Amex:BlueCashPreferred"
      currency: "USD"

# Required defaults
default_currency: "USD"
default_account_when_training_unavailable: "Expenses:Unknown"
```

### Configuration Field Precedence

The system follows this precedence order for configuration values:

1. **Command Line Arguments** (highest precedence) - Override all other sources
2. **Configuration File Values** (medium precedence) - Used when CLI arguments not provided
3. **Application Defaults** (lowest precedence) - Used when neither CLI nor config specify values
4. **Error for Required Fields** - If required arguments missing from both CLI and config, system exits with error

### File Path Resolution

- **Relative paths**: Resolved relative to current working directory (same behavior as CLI arguments)
- **Absolute paths**: Used as-is
- **Path validation**: All resolved file paths validated using existing FileValidator after argument resolution

## Machine Learning Details

### Feature Processing
- **Training features**: Payee + Memo concatenated and preprocessed
- **Preprocessing function**: Based on `preprocess_description()` from reference implementation:
  - Remove all special characters (replace with spaces)
  - Remove all words containing numbers
  - Remove all single characters
  - Substitute multiple spaces with single space
  - Convert to lowercase
  - Remove specific terms: "aplpay", "com"

### Training Data Requirements
- **Training Data Source**: Parse all transaction directives from provided Beancount training file using the `beancount` Python library
- **Training Features**: Extract payee + memo from each transaction directive for ML training
- **Minimum training data**: If insufficient training data available, system should:
  - Not attempt auto-categorization
  - Inform user of insufficient training data
  - Allow all transactions to remain as "Expenses:Unknown"
  - Require full interactive categorization

### Confidence Threshold
- **Minimum confidence**: 70% threshold for auto-categorization
- **Below threshold**: Transactions flagged for mandatory manual review
- **Unknown account types**: System accepts new account types from training data and notifies user

## OFX Processing Specifications

### Supported Formats
- **OFX versions**: Support both 1.x and 2.x (as supported by ofxparse library)
- **Transaction types**: DEBIT, CREDIT, INT (Interest), DIV (Dividend)
- **Scope**: Banking transactions only (no investment transactions)

### Error Handling
- **Malformed files**: Reject with clear error message to user
- **Incomplete files**: Reject with clear error message to user
- **Zero amounts**: Process normally (no special handling)
- **Large files**: Display warning if OFX file contains more than 1000 transactions
- **Batch operation failures**: Commit successful transactions, continue processing despite partial failures

## Beancount Output Specifications

### Transaction Format
- **Date format**: Standard Beancount format (YYYY-MM-DD)
- **Transaction IDs**: Include unique identifier as metadata field `transaction_id` using SHA256 hash of immutable fields
- **ID Generation**: SHA256 hash of concatenated string: `date|payee|narration|amount|mapped_beancount_account`
- **ID Field Validation**: All critical fields used in transaction_id generation are strictly validated:
  - `date`: Must be non-empty and in valid YYYY-MM-DD format representing a real date
  - `payee`: Must be non-empty string OR narration must be non-empty (at least one required)
  - `narration`: Must be non-empty string OR payee must be non-empty (at least one required)  
  - `amount`: Must contain a valid numeric value (may include currency, e.g., "-85.50 USD")
  - `mapped_beancount_account`: Must be non-empty valid account name
- **Validation Failure Handling**: If any critical field is empty/invalid, system terminates with clear error message specifying the problematic transaction and required fix
- **Data Quality Enforcement**: No fallback processing for empty critical fields - users must fix data quality issues
- **Flexible Content Requirements**: Transactions may have empty payee if narration is meaningful, or empty narration if payee is meaningful
- **ID Collision Handling**: Append `-2`, `-3`, etc. for hash collisions within the same OFX file
- **Duplicate Transaction IDs**: For potential duplicates that users choose to keep, append `-dup-1`, `-dup-2`, etc.
- **OFX Source IDs**: Include original OFX transaction ID as metadata field `ofx_id` when available and valid
- **OFX ID Handling**: Omit `ofx_id` metadata if OFX file lacks transaction ID or ID is malformed/empty
- **Directives**: Focus only on transaction directives (ignore open/close/balance statements)
- **Metadata**: Both transaction_id and ofx_id metadata automatically generated for all transactions

### Transaction ID Utility Script
- **Purpose**: A standalone utility (`utils/add_transaction_ids.py`) adds transaction_id metadata to existing Beancount files
- **Use Cases**: 
  - Add transaction IDs to legacy Beancount files that lack them
  - Recalculate transaction IDs after manual edits to transactions
  - Standardize transaction IDs across different Beancount files
- **Features**:
  - Preserves original file structure and formatting
  - Skips transactions that already have transaction_id metadata (unless `--force-recalculate` is used)
  - Uses same ID generation logic as main OFX converter
  - Account selection priority for ID generation:
    1. Assets or Liabilities accounts (first found)
    2. Income accounts (first found)
    3. First posting account
- **Command Line Options**:
  - `-i, --input`: Input Beancount file (required)
  - `-o, --output`: Output Beancount file (required)
  - `--force-overwrite`: Allow overwriting existing output file
  - `--force-recalculate`: Remove and recalculate transaction_id for all transactions, even those that already have one
  - `--dry-run`: Show what would be processed without writing output file
  - `-v, --verbose`: Enable verbose output showing processing details
- **Statistics Tracking**:
  - Reports number of transactions with new IDs added
  - Reports number of transactions with IDs recalculated (when using `--force-recalculate`)
  - Reports number of transactions that already had IDs (skipped or recalculated)
  - Shows processing errors if any transactions couldn't be processed
- **Safety Features**:
  - Never overwrites existing output files unless `--force-overwrite` is specified
  - Validates input file readability and output file writability before processing
  - Provides detailed error messages for data quality issues
  - Maintains transaction_id as first metadata field for consistency

### Currency Handling
- **Multi-currency transactions**: Flag with exclamation mark in Beancount format
- **Flagging format**: `2024-01-15 ! "PAYEE" "memo"` (note: only one flag character allowed)
- **Multi-currency scenarios**: Use file-level currency defaults (no per-transaction prompting)
- **Date handling**: No special behavior for old or future-dated transactions

## Implementation Stack

### Backend (API)
- **Python 3.8+**
- **FastAPI** - Web framework for API
- **ofxparse** - OFX file parsing
- **scikit-learn** - Machine learning (RandomForest, TF-IDF)
- **pandas** - Data manipulation
- **beancount** - Transaction validation and parsing
- **pydantic** - Data validation and settings
- **PyYAML** - Configuration file parsing (server-side only)
- **rapidfuzz** - Fuzzy string matching for duplicate detection

### CLI Client
- **Python 3.8+**
- **prompt_toolkit** - Interactive CLI
- **requests** - API communication
- **click** - Command-line interface framework
- **Note**: No YAML parsing dependency - configuration handled server-side

### Future GUI Client
- **Vue 3** - Frontend framework
- **TypeScript** - Type safety
- **Tailwind CSS** - Styling
- **Axios** - API communication

## Command Line Arguments

```bash
python ofx_converter.py [OPTIONS]

Options:
  -i, --input-file PATH          OFX file to process [required if not in config]
  -l, --learning-data-file PATH  Beancount file for training data [optional, can be in config]
  -o, --output-file PATH         Output Beancount file (appends if exists) [required, can be in config] - enables duplicate detection
  -a, --account-file PATH        Full Beancount file with open directives for account validation [optional, can be in config]
  -c, --config-file PATH         YAML configuration file [required]
  -p, --port-num INTEGER         Port number for API server (default: 8000, can be in config)
  -s, --server-only              Run only the API server (for GUI client use) [can be in config]
  --help                         Show this message and exit
```

### Argument Resolution

All command line arguments (except `-c`) can now be specified in the configuration file. The system resolves arguments using this precedence:

1. **CLI Arguments** - Highest precedence, always override config file values
2. **Config File Values** - Used when CLI arguments not provided  
3. **Required Validation** - If neither CLI nor config provides required arguments (like input file), system exits with clear error message

**Example Error Messages:**
- `❌ Input file is required. Provide via -i/--input-file or config file 'files.input_file'`
- `❌ Config file is required and must be specified via -c/--config-file`

## User Workflow

### 1. Initial Setup
1. User provides OFX file path
2. System displays file statistics (date range, balance, transaction count)
3. System determines source account and currency using configuration mapping
4. User confirms or corrects account name and currency

### 2. Transaction Processing
1. System loads all OFX transactions
2. Creates initial Beancount transactions with "Expenses:Unknown" postings
3. Trains ML classifier using provided Beancount training data
4. Auto-categorizes all transactions
5. Performs duplicate detection against existing output file (if provided and exists)

### 3. Interactive Review
For each transaction:
1. Display: Date, Payee, Amount, Memo, Suggested Category
2. User options:
   - Press Enter to accept the Suggested Category
   - Type new account name (with fuzzy completion)
   - Split transaction into multiple postings ('s' command)
   - Skip transaction ('k' command) - used for duplicates and unwanted transactions
   - Navigate to previous transaction ('p' command)
   - Add narration/note
3. Duplicate handling:
   - Potential duplicates displayed with warning after transaction details
   - Warning format: "⚠️ Potential duplicate of YYYY-MM-DD PAYEE AMOUNT"
   - Users can skip duplicates using 'k' command

### 4. Output Generation
1. Validate all transaction postings and amounts
2. Check for sign correctness (expenses positive, income negative - This may not always be true. Sometimes an expense can be negative e.g. in the case of a return.)
3. Append to output file or write to stdout
4. Display summary statistics

## Data Flow

### API Call Sequence:
```
1. POST /session/initialize
   ├── Load and Parse Configuration File
   ├── Parse OFX File (server-side)
   ├── Map Account (with config)
   ├── Train ML Classifier 
   └── Return session info + detected account

2. POST /transactions/categorize
   ├── Auto-categorize all transactions
   ├── Detect potential duplicates
   └── Return categorized transactions (JSON API format)

3. POST /transactions/update-batch  
   ├── Process user corrections (JSON API format)
   ├── Convert API → Beancount objects
   ├── Generate transaction IDs using Beancount objects
   ├── Store Beancount objects as canonical format
   ├── Handle transaction splits
   ├── Validate postings balance
   └── Return validation results

4. POST /export/beancount
   ├── Use stored Beancount objects
   ├── Apply final filtering (skip marked transactions)
   ├── Generate output using native Beancount printer
   └── Write to output file
   └── Return export summary
```

### Optimized Data Flow:
```
File Paths → Initialize Session → Categorize All → Interactive Batch Updates → Export
     ↓              ↓                    ↓                      ↓                   ↓
  1 API call    1 API call         1 API call            N batch calls      1 API call
```

**Note**: All file operations (config parsing, OFX parsing, training data loading) are handled server-side. The CLI client sends only file paths to the API server.

### Output Consistency
Both the main OFX converter and the `add_transaction_ids.py` utility script produce identical output:

- **Same Transaction Objects**: Both use standard `beancount.core.data.Transaction` objects
- **Same ID Generation**: Both use `core/transaction_id_generator.py` with Beancount objects  
- **Same Output Format**: Both use Beancount's native `printer.print_entries()`
- **Same Metadata**: Source account is preserved in `source_account` metadata for consistency

This guarantees that running `add_transaction_ids.py --force-recalculate` on OFX converter output produces identical transaction IDs and formatting.

## File Structure

```
ofx-to-beancount/
├── ofx_converter.py         # Top-level CLI entry point script
├── api/
│   ├── __init__.py
│   ├── main.py              # FastAPI app
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── session.py       # Session initialization endpoint
│   │   ├── transactions.py  # Transaction categorization and update endpoints
│   │   └── export.py        # Beancount export endpoint
│   ├── models/
│   │   ├── __init__.py
│   │   ├── transaction.py   # Transaction data models
│   │   ├── session.py       # Session data models
│   │   └── config.py        # Configuration models
│   └── services/
│       ├── __init__.py
│       ├── session_manager.py # Session state management
│       └── validator.py     # Data validation service
├── cli/
│   ├── __init__.py
│   ├── main.py              # CLI logic implementation
│   ├── interactive.py       # Interactive prompts
│   └── api_client.py        # API communication
├── core/
│   ├── __init__.py
│   ├── ofx_parser.py        # OFX file processing (produces API Transaction objects)
│   ├── account_mapper.py    # Account mapping logic
│   ├── classifier.py        # ML categorization
│   ├── beancount_converter.py # API ↔ Beancount object conversion
│   ├── transaction_id_generator.py # SHA256-based transaction ID generation
│   ├── beancount_generator.py # Legacy output generation (file operations)
│   └── duplicate_detector.py # Duplicate detection
├── config/
│   └── example_config.yaml  # Sample configuration
├── tests/
│   ├── test_parser.py
│   ├── test_classifier.py
│   └── test_integration.py
└── requirements.txt
```

## Validation Rules

### Account Name Validation
- Must exist in provided account file (parsed from open directives, extracting account names and currencies only)
- Must follow Beancount account naming conventions
- Account type must match expected posting sign
- Configuration validation: All configured account mappings must reference existing accounts or program stops with warning
- **Account File Parsing**: 
  - Extract account names and currencies from open directives only
  - Use USD as default currency if no currency specified in open directive
  - Ignore closed accounts and duplicate open directives for same account

### Transaction Validation  
- Date must be valid ISO format (YYYY-MM-DD)
- All postings must balance to zero
- Currency must be specified for all postings
- Expense accounts: positive amounts (usually. But there can be exceptions e.g. in case purchased items are returned and the vendor returns the amount to the financial institution)
- Income accounts: negative amounts (usually)
- Asset/Liability accounts: signs based on transaction type

### ML Categorization Failures
- **Complete failure**: Keep category as "Expenses:Unknown" for interactive user input
- **Low confidence**: Transactions below 70% confidence threshold flagged for manual review

### Duplicate Detection Criteria
Two transactions are considered duplicates if they match:
- Date (exact match)
- Source account (exact match)  
- Amount (exact match)
- Payee (fuzzy match > 90% similarity using rapidfuzz library)

### Duplicate Detection Errors
- **Output file not found**: Silently skip duplicate detection, include system message "Note: Duplicate detection unavailable"
- **File parsing errors**: Silently skip duplicate detection, include system message with error details
- **Detection process failure**: Continue processing, include system message with error information

## Error Handling

### Comprehensive File Error Handling

The system implements robust error handling for all file operations with specific behaviors for each file type and error condition.

### Output File Error Handling

#### Output File Not Specified
- **Server Response**: Send error message "Output file not specified"
- **Client Behavior**: Display message instructing user to specify output file using `-o` option, then terminate

#### Output File Missing
- **Server Behavior**: Send info message "Output file not found, creating new file", create empty output file, proceed normally
- **Client Behavior**: Display info message, continue processing

#### Output File Not Writable
- **Server Response**: Send error message "Output file not writable" with specific reason (permissions, disk space, etc.)
- **Client Behavior**: Display error message, terminate program

### Training Data File Error Handling

#### Training File Missing or Unreadable
- **Server Behavior**: 
  - Send warning message "Training data file not available" or "Training data file not readable"
  - Set default category from config: `default_account_when_training_unavailable` (default: "Expenses:Unknown")
  - Send confirmation_required response asking user to continue with degraded functionality
- **Client Behavior**: 
  - Display warning message
  - Prompt user: "Continue without ML categorization? All transactions will use [default_account]. (y/n)"
  - If user selects 'n', terminate program
  - If user selects 'y', continue with degraded functionality

#### Training File Invalid Content
- **Server Behavior**: 
  - Send warning message "Training data file does not contain valid Beancount transactions"
  - Apply same degraded functionality as missing file
- **Client Behavior**: Same as missing file scenario

### Accounts File Error Handling

#### Accounts File Missing or Unreadable
- **Server Behavior**: 
  - Send warning message "Accounts file not present" or "Accounts file not readable"
  - Use default category from config for all transactions
  - Disable account name validation
  - Send confirmation_required response asking user to continue with degraded functionality
- **Client Behavior**: 
  - Display warning message
  - Prompt user: "Continue without account validation? Fuzzy completion will be limited. (y/n)"
  - Handle user response (continue or terminate)

#### Accounts File Invalid Content
- **Server Behavior**: 
  - Send warning message "Accounts file does not contain valid Beancount account definitions"
  - Apply same degraded functionality as missing file
- **Client Behavior**: Same as missing file scenario

### Configuration File Error Handling

#### Config File Missing
- **Server Response**: Send error message "Configuration file not found: [file_path]"
- **Client Behavior**: Display error message, terminate program

#### Config File Unreadable
- **Server Response**: Send error message "Configuration file not readable: [file_path] - [specific_reason]"
- **Client Behavior**: Display error message, terminate program

#### Config File Invalid YAML
- **Server Response**: Send error message "Configuration file contains invalid YAML: [specific_yaml_error_details]"
- **Client Behavior**: Display error message with parsing details, terminate program

### Input (OFX) File Error Handling

#### Input File Missing or Unreadable
- **Server Response**: Send error message "Input OFX file not found" or "Input OFX file not readable: [specific_reason]"
- **Client Behavior**: Display error message, terminate program

#### Input File Invalid OFX Format
- **Server Response**: Send error message "Input file does not appear to be a valid OFX file: [parsing_error_details]"
- **Client Behavior**: Display error message, terminate program

### API Response Model Extensions

#### Confirmation Required Response
For scenarios requiring user confirmation to continue with degraded functionality:

```json
{
  "response_type": "confirmation_required",
  "confirmation_message": "Training data file not available. Continue without ML categorization? All transactions will use Expenses:Unknown.",
  "confirmation_type": "training_data_unavailable",
  "fallback_account": "Expenses:Unknown",
  "system_messages": [
    {
      "level": "warning",
      "message": "Training data file not found: /path/to/training.beancount"
    }
  ]
}
```

#### Confirmation Response from Client
```json
{
  "session_id": "uuid-string",
  "confirmation_type": "training_data_unavailable",
  "user_choice": "continue" // or "abort"
}
```

### System Message Framework
All API responses include optional `system_messages` field:
```json
"system_messages": [
  {
    "level": "info|warning|error",
    "message": "Human-readable message"
  }
]
```
- **info**: Informational messages (e.g., "Output file created successfully")
- **warning**: Non-blocking issues requiring user awareness (e.g., "Training data unavailable")
- **error**: Critical issues preventing processing (e.g., "Configuration file not readable")
- **CLI Handling**: All system messages displayed to user, processing continues based on error severity

### Error Handling Implementation Notes

#### File Operation Error Types
The system distinguishes between specific error conditions:
- **File Not Found**: `FileNotFoundError`
- **Permission Denied**: `PermissionError` 
- **File is Directory**: `IsADirectoryError`
- **System/IO Errors**: `OSError`, `IOError`
- **Encoding Errors**: `UnicodeDecodeError`
- **Format/Parsing Errors**: Format-specific exceptions (YAML, OFX, Beancount)

#### Graceful Degradation Strategy
1. **Non-Essential Files** (training data, accounts): Allow user to continue with reduced functionality
2. **Essential Files** (config, input OFX): Require resolution before proceeding
3. **Output Files**: Create if missing, fail if not writable

#### User Interaction Flow
1. Server detects file error during processing
2. Server sends appropriate response (error or confirmation_required)
3. Client displays message and either terminates or prompts user
4. For confirmation scenarios, client sends user choice back to server
5. Server continues with appropriate functionality level

### Edge Cases Not Considered
**Note**: The following edge cases have been intentionally excluded from the current specification and may be addressed in future versions:
- Disk space exhaustion during file operations
- Network drive timeout and connectivity issues
- Memory limitations with very large files
- File locking conflicts (files open in other applications)
- Path length limitations and invalid path characters
- Atomic write operations and rollback mechanisms

## File Handling Architecture

### Consistent Server-Side Processing
All file operations are handled uniformly by the API server:
- **OFX Input Files**: Server reads and parses directly from file path
- **Configuration Files**: Server loads and validates YAML from file path
- **Training Data Files**: Server reads Beancount files for ML training from file path
- **Account Files**: Server loads account definitions from file path
- **Output Files**: Server writes results and reads for duplicate detection from file path

### Client-Server Interface
- **CLI sends**: File paths only (no file contents)
- **Server handles**: All file I/O, parsing, and validation
- **Benefits**: Consistent error handling, unified validation, simplified client
- **Requirement**: Client and server must run on same machine with shared filesystem

## Security Considerations

- Local-only API (no external network access)
- No authentication required (local use)
- File path validation to prevent directory traversal
- Input sanitization for all user data
- Safe parsing of financial data
- **Session Storage**: Sessions are stored in-memory only (no persistent storage)
- **Session Recovery**: If API restarts mid-session, return error indicating user must restart from beginning

## Performance Requirements

- Handle OFX files up to 10,000 transactions
- ML training completion within 30 seconds
- Interactive response time < 1 second per transaction
- Memory usage < 500MB for typical workloads

### Performance Implementation Notes
- **No streaming**: Process entire OFX files in memory (optimization deferred)
- **No caching**: Build all data structures at runtime
- **No progress indicators**: Keep implementation simple initially
- **Terminal handling**: No special handling for terminal resizing
- **Duplicate Detection Performance**: Parsing existing beancount files for duplicate detection may impact performance with large output files (optimization deferred)

## Testing Strategy

- **Testing approach**: Deferred until program matures
- **Test coverage**: Not specified for initial implementation
- **Integration tests**: Not required for initial version
- **Mock data**: Not specified for initial version

## Future Enhancements

1. **Web GUI Interface** - Vue.js frontend for browser-based interaction
2. **Batch Processing** - Process multiple OFX files simultaneously  
3. **Rule-Based Categorization** - User-defined rules supplement ML
4. **Transaction Templates** - Save common transaction patterns
5. **Import/Export** - Support additional file formats (QIF, CSV)
6. **Reporting** - Generate spending reports and analytics
7. **Cloud Storage** - Optional cloud backup of configurations
8. **Mobile App** - React Native mobile interface
9. **Performance Optimizations** - Streaming, caching, progress indicators
10. **Enhanced CLI** - Undo/redo functionality, improved terminal handling

## Success Criteria

- Successfully parse common OFX file formats from major financial institutions
- Achieve >80% accuracy in initial transaction categorization
- Provide intuitive CLI interface requiring minimal user training
- Generate valid Beancount output compatible with standard tools
- Process typical monthly statement (100-500 transactions) in <5 minutes
- Handle edge cases gracefully with clear error messages

This specification provides the foundation for implementing a robust, user-friendly OFX to Beancount converter that leverages machine learning for intelligent transaction categorization while maintaining full user control over the final output.