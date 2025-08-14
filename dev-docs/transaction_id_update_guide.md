# Transaction ID Generator v2.0 - Migration Guide

## Overview

The `transaction_id_generator.py` module has been significantly improved to ensure perfect consistency across all codebases using it. This guide helps developers migrate from the legacy API to the new streamlined interface and explains how to obtain the generator for your projects.

## Getting the Transaction ID Generator

### New Distribution Method: Git Subtree

The transaction ID generator is now distributed via git subtree, allowing you to include it directly in your project while keeping it updatable from the source.

#### Initial Setup in Your Project

```bash
# Add the transaction ID generator to your project
git subtree add --prefix=shared/transaction_id_generator \
  https://github.com/sagarbehere/ofx-to-beancount.git transaction-id-generator-only \
  --squash

# Create __init__.py to make shared a Python package
echo "# Shared modules package" > shared/__init__.py

# Commit the changes
git add .
git commit -m "Add transaction ID generator via git subtree"
```

This creates the following structure in your project:
```
your-project/
├── shared/
│   ├── __init__.py
│   └── transaction_id_generator/
│       ├── __init__.py
│       ├── transaction_id_generator.py
│       └── README.md
└── ... your other files
```

#### Pulling Updates

When updates are available:

```bash
git subtree pull --prefix=shared/transaction_id_generator \
  https://github.com/sagarbehere/ofx-to-beancount.git transaction-id-generator-only \
  --squash
```

## Key Changes in v2.0

### Before (Legacy API):
- Callers manually extracted individual fields (date, payee, amount, account)
- Callers handled account selection logic themselves
- Different codebases implemented different account selection strategies
- Risk of inconsistent transaction IDs across tools

### After (New API):
- **Single entry point**: Pass complete Beancount transaction objects
- **Centralized logic**: All account selection and field extraction handled internally
- **Perfect consistency**: All codebases using the same Beancount objects get identical transaction IDs
- **Future-proof**: Changes to transaction ID logic are centralized

## Migration Steps

### 1. Add the Transaction ID Generator to Your Project

```bash
# If you haven't already, add via git subtree
git subtree add --prefix=shared/transaction_id_generator \
  https://github.com/sagarbehere/ofx-to-beancount.git transaction-id-generator-only \
  --squash
```

### 2. Update Your Imports

**Old Import (if you had a local copy):**
```python
from core.transaction_id_generator import generate_single_transaction_id
# or
from utils.transaction_id_generator import TransactionIdGenerator
# or any other local path
```

**New Import (from git subtree):**
```python
from shared.transaction_id_generator import (
    TransactionIdGenerator,
    add_transaction_id_to_beancount_transaction,
    generate_single_transaction_id  # Still available but deprecated
)
```

### 3. Update Dependencies

Ensure you have access to the Beancount library:
```python
from beancount.core.data import Transaction as BeancountTransaction
```

### 4. Use the New Primary Function

**Old Way:**
```python
from shared.transaction_id_generator import generate_single_transaction_id

# Manual field extraction and account selection
transaction_id = generate_single_transaction_id(
    date=txn.date.strftime('%Y-%m-%d'),
    payee=txn.payee or "",
    amount=f"{txn.amount} USD",
    mapped_account=manually_selected_account,  # ❌ Manual selection
    narration=txn.narration or ""
)
```

**New Way:**
```python
from shared.transaction_id_generator import add_transaction_id_to_beancount_transaction

# Pass complete Beancount transaction - everything is handled internally
transaction_with_id = add_transaction_id_to_beancount_transaction(
    transaction=beancount_transaction,  # ✅ Standard Beancount object
    force_recalculate=False,
    strict_validation=True
)

# Access the generated ID
transaction_id = transaction_with_id.meta['transaction_id']
```

### 5. Account Selection is Now Automatic

The new API automatically selects the appropriate account using standardized priority logic:

1. **Source Account Metadata**: If `source_account` metadata exists, uses that account
2. **Assets/Liabilities**: First Assets or Liabilities account found in postings
3. **Income Accounts**: First Income account found in postings  
4. **Fallback**: First posting account

This ensures all codebases use identical account selection logic.

### 6. Batch Processing

For processing multiple transactions with collision tracking:

**Old Way:**
```python
generator = TransactionIdGenerator()
for txn in transactions:
    # Manual collision tracking
    id = generator.generate_id(date, payee, amount, account, narration)
```

**New Way:**
```python
from shared.transaction_id_generator import (
    TransactionIdGenerator,
    add_transaction_id_to_beancount_transaction
)

generator = TransactionIdGenerator()
processed_transactions = []

for beancount_txn in beancount_transactions:
    txn_with_id = add_transaction_id_to_beancount_transaction(
        transaction=beancount_txn,
        id_generator=generator  # ✅ Shared collision tracking
    )
    processed_transactions.append(txn_with_id)
```

## Complete Example Migration

### Before: Manual Processing with Local Copy
```python
# Legacy approach - manual field extraction
from my_utils.transaction_id_generator import generate_single_transaction_id
from decimal import Decimal

def process_transaction_legacy(api_transaction):
    # Manual account selection (different across codebases)
    if api_transaction.categorized_accounts:
        account = api_transaction.categorized_accounts[0].account
    else:
        account = api_transaction.source_account
    
    # Manual field extraction
    transaction_id = generate_single_transaction_id(
        date=api_transaction.date,
        payee=api_transaction.payee,
        amount=f"{api_transaction.amount} {api_transaction.currency}",
        mapped_account=account,
        narration=api_transaction.narration
    )
    
    return transaction_id
```

### After: Beancount-Based Processing with Git Subtree  
```python
# New approach - Beancount objects ensure consistency
from shared.transaction_id_generator import add_transaction_id_to_beancount_transaction
from beancount.core.data import Transaction, Posting, Amount
from decimal import Decimal
from datetime import datetime

def process_transaction_new(api_transaction):
    # Convert to standard Beancount format
    beancount_txn = api_to_beancount_transaction(api_transaction)
    
    # Generate transaction ID using centralized logic
    txn_with_id = add_transaction_id_to_beancount_transaction(
        transaction=beancount_txn,
        strict_validation=True
    )
    
    return txn_with_id.meta['transaction_id']

def api_to_beancount_transaction(api_txn):
    """Convert API transaction to Beancount format"""
    # Create postings
    postings = []
    for posting in api_txn.categorized_accounts:
        postings.append(Posting(
            account=posting.account,
            units=Amount(Decimal(str(posting.amount)), posting.currency),
            cost=None, price=None, flag=None, meta=None
        ))
    
    # Add source posting
    source_amount = -sum(p.units.number for p in postings)
    postings.append(Posting(
        account=api_txn.source_account,
        units=Amount(source_amount, api_txn.currency),
        cost=None, price=None, flag=None, meta=None
    ))
    
    # Create Beancount transaction
    return Transaction(
        meta={'source_account': api_txn.source_account},
        date=datetime.strptime(api_txn.date, '%Y-%m-%d').date(),
        flag='*',
        payee=api_txn.payee,
        narration=api_txn.narration,
        tags=frozenset(),
        links=frozenset(),
        postings=postings
    )
```

## For Projects Not Using Beancount

If your project doesn't use Beancount, you can still use the basic generator:

```python
from shared.transaction_id_generator import TransactionIdGenerator

# Create generator instance
generator = TransactionIdGenerator()

# Generate IDs without Beancount objects
txn_id = generator.generate_id(
    date="2024-01-15",
    payee="STORE NAME",
    amount="-100.00 USD",
    mapped_account="Expenses:Shopping",
    narration="Purchase description"
)
```

## Core Benefits

### 1. Perfect Consistency
All codebases using Beancount objects will generate **identical transaction IDs** for the same financial data.

### 2. Centralized Logic
- Account selection rules are standardized
- Field extraction is consistent
- Future improvements benefit all users

### 3. Automatic Updates
- Pull latest improvements with git subtree
- No manual copying of files
- Version controlled distribution

### 4. Source Account Preservation
The `source_account` metadata ensures that the original OFX source account is preserved and used consistently.

### 5. Backward Compatibility
Legacy functions still exist but are deprecated. The new API is the recommended approach.

## API Reference

### Primary Function (Beancount)
```python
def add_transaction_id_to_beancount_transaction(
    transaction: BeancountTransaction,
    force_recalculate: bool = False,
    strict_validation: bool = True,
    id_generator: Optional[TransactionIdGenerator] = None
) -> BeancountTransaction
```

**Parameters:**
- `transaction`: Standard `beancount.core.data.Transaction` object
- `force_recalculate`: If True, recalculate even if transaction already has transaction_id  
- `strict_validation`: If True, enforce strict field validation
- `id_generator`: Optional generator instance for collision tracking

**Returns:**
- New Beancount transaction with `transaction_id` metadata added

### Basic Generator Class
```python
class TransactionIdGenerator:
    def generate_id(self, 
                   date: str, 
                   payee: str, 
                   amount: Union[str, Decimal, float], 
                   mapped_account: str, 
                   narration: str = "",
                   is_kept_duplicate: bool = False,
                   strict_validation: bool = False) -> str
```

### Account Selection Logic
The function automatically selects accounts using this priority:

1. **`source_account` metadata** (if present) - ensures consistency with original processing
2. **Assets/Liabilities accounts** (first found in postings)
3. **Income accounts** (first found in postings)
4. **First posting account** (fallback)

### Metadata Added
The function adds/preserves these metadata fields:
- `transaction_id`: Generated SHA256 hash
- `source_account`: Identified source account for future consistency
- Other existing metadata is preserved

## Testing Your Migration

Verify your migration works correctly:

```python
def test_transaction_id_consistency():
    from shared.transaction_id_generator import add_transaction_id_to_beancount_transaction
    
    # Create identical Beancount transactions
    txn1 = create_test_transaction()
    txn2 = create_test_transaction()
    
    # Generate IDs
    result1 = add_transaction_id_to_beancount_transaction(txn1)
    result2 = add_transaction_id_to_beancount_transaction(txn2)
    
    # Should be identical
    assert result1.meta['transaction_id'] == result2.meta['transaction_id']
    
    # Should match legacy computation (if same inputs)
    from shared.transaction_id_generator import generate_single_transaction_id
    
    legacy_id = generate_single_transaction_id(
        date=result1.date.strftime('%Y-%m-%d'),
        payee=result1.payee,
        amount=f"{result1.postings[0].units.number} {result1.postings[0].units.currency}",
        mapped_account=result1.meta['source_account'],
        narration=result1.narration
    )
    assert result1.meta['transaction_id'] == legacy_id
```

## Migration Checklist

- [ ] Add transaction ID generator via git subtree to your project
- [ ] Create `shared/__init__.py` file
- [ ] Update imports to use `shared.transaction_id_generator`
- [ ] Convert your transaction data to `beancount.core.data.Transaction` objects (if using Beancount)
- [ ] Remove manual account selection logic
- [ ] Remove manual field extraction code
- [ ] Use shared `TransactionIdGenerator` instance for batch processing
- [ ] Test that transaction IDs are consistent with other tools
- [ ] Verify that `source_account` metadata is preserved (if applicable)
- [ ] Update your documentation to reflect new import paths

## Keeping Your Copy Updated

To get the latest improvements:

```bash
# Check for updates periodically
git subtree pull --prefix=shared/transaction_id_generator \
  https://github.com/sagarbehere/ofx-to-beancount.git transaction-id-generator-only \
  --squash

# Resolve any conflicts if necessary
git add .
git commit -m "Update transaction ID generator to latest version"
```

## Support

For questions about migration or issues with the new API, refer to:
- `shared/transaction_id_generator/README.md` in your project for usage instructions
- [ofx-to-beancount repository](https://github.com/sagarbehere/ofx-to-beancount) for source code
- `dev-docs/subtree-workflow.md` in the source repository for distribution details

The new API ensures perfect transaction ID consistency across all tools while simplifying the integration process.