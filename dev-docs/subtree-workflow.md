# Git Subtree Workflow for Transaction ID Generator

This document explains how to manage and distribute the transaction ID generator to other projects using git subtree.

## Overview

The transaction ID generator lives in the main branch at `shared_libs/transaction_id_generator/` but is distributed to other projects via a special branch called `transaction-id-generator-only` that contains ONLY the generator files.

## Architecture

```
ofx-to-beancount repository:

main branch (development):
├── api/
├── core/
├── shared_libs/
│   └── transaction_id_generator/    ← Development happens here
│       ├── __init__.py
│       ├── transaction_id_generator.py
│       └── README.md
├── utils/
└── ... other files

transaction-id-generator-only branch (distribution):
├── __init__.py
├── transaction_id_generator.py
└── README.md
(just these 3 files!)
```

## For Users of the Transaction ID Generator

### Initial Setup in Your Project

To add the transaction ID generator to your project:

```bash
# In your project directory
git subtree add --prefix=shared/transaction-id-generator \
  https://github.com/sagarbehere/ofx-to-beancount.git transaction-id-generator-only \
  --squash
```

This creates:
```
your-project/
├── shared/
│   └── transaction-id-generator/
│       ├── __init__.py
│       ├── transaction_id_generator.py
│       └── README.md
└── ... your other files
```

### Using in Your Code

```python
from shared.transaction_id_generator import TransactionIdGenerator

generator = TransactionIdGenerator()
txn_id = generator.generate_id(date, payee, amount, account)
```

### Pulling Updates

When updates are available:

```bash
git subtree pull --prefix=shared/transaction-id-generator \
  https://github.com/sagarbehere/ofx-to-beancount.git transaction-id-generator-only \
  --squash
```

## For Maintainers of ofx-to-beancount

### Development Workflow

1. **All development happens on the main branch**
   - Edit files in `shared_libs/transaction_id_generator/`
   - Test your changes
   - Commit and push to main as usual

2. **The subtree branch is ONLY for distribution**
   - Never checkout or edit the `transaction-id-generator-only` branch directly
   - It's automatically generated from main

### Updating the Distribution Branch

After making changes to the transaction ID generator in main:

#### Method 1: Force Recreate (Recommended - Simplest)

```bash
# Make sure you're on main with latest changes
git checkout main
git pull

# Delete old branch
git branch -D transaction-id-generator-only 2>/dev/null

# Recreate from main
git subtree split --prefix=shared_libs/transaction_id_generator \
  -b transaction-id-generator-only

# Push to GitHub (force push is OK - this branch is read-only)
git push origin transaction-id-generator-only --force-with-lease
```

#### Method 2: Update Existing Branch

```bash
# Make sure you're on main
git checkout main

# Update the subtree branch
git subtree split --prefix=shared_libs/transaction_id_generator \
  --onto=transaction-id-generator-only -b transaction-id-generator-only

# Push (force needed because history changes)
git push origin transaction-id-generator-only --force-with-lease
```

### Complete Example Workflow

```bash
# 1. Make changes on main
git checkout main
vim shared_libs/transaction_id_generator/transaction_id_generator.py
# ... edit code ...

# 2. Test your changes
python -c "from shared_libs.transaction_id_generator import TransactionIdGenerator; print('✅ Works')"

# 3. Commit to main
git add shared_libs/transaction_id_generator/
git commit -m "Fix: Handle edge case in amount parsing"
git push origin main

# 4. Update distribution branch
git branch -D transaction-id-generator-only
git subtree split --prefix=shared_libs/transaction_id_generator -b transaction-id-generator-only
git push origin transaction-id-generator-only --force-with-lease

# 5. Announce to users
echo "✅ Transaction ID generator updated! Other projects can now pull the changes."
```

### Automation Script

Save this as `update-subtree-branch.sh`:

```bash
#!/bin/bash
# update-subtree-branch.sh
# Updates the transaction-id-generator-only branch after changes to main

set -e

echo "📦 Updating transaction-id-generator-only branch..."

# Ensure we're on main
git checkout main

# Delete old branch
git branch -D transaction-id-generator-only 2>/dev/null || true

# Recreate from current main
git subtree split --prefix=shared_libs/transaction_id_generator \
  -b transaction-id-generator-only

# Push to origin
git push origin transaction-id-generator-only --force-with-lease

echo "✅ Distribution branch updated successfully!"
echo ""
echo "Other projects can now update with:"
echo "  git subtree pull --prefix=shared/transaction-id-generator \\"
echo "    https://github.com/sagarbehere/ofx-to-beancount.git transaction-id-generator-only \\"
echo "    --squash"
```

Make it executable:
```bash
chmod +x update-subtree-branch.sh
```

Then use it after any changes:
```bash
./update-subtree-branch.sh
```

### GitHub Actions Automation (Optional)

Create `.github/workflows/update-subtree.yml`:

```yaml
name: Update Subtree Distribution Branch

on:
  push:
    branches: [main]
    paths:
      - 'shared_libs/transaction_id_generator/**'

jobs:
  update-subtree:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
        with:
          fetch-depth: 0  # Need full history for subtree
      
      - name: Configure Git
        run: |
          git config user.name "GitHub Actions Bot"
          git config user.email "actions@github.com"
      
      - name: Update subtree branch
        run: |
          # Delete old branch if exists
          git push origin --delete transaction-id-generator-only 2>/dev/null || true
          
          # Create new subtree branch
          git subtree split --prefix=shared_libs/transaction_id_generator \
            -b transaction-id-generator-only
          
          # Push to origin
          git push origin transaction-id-generator-only
      
      - name: Create summary
        run: |
          echo "✅ Updated transaction-id-generator-only branch" >> $GITHUB_STEP_SUMMARY
          echo "" >> $GITHUB_STEP_SUMMARY
          echo "Other projects can pull updates with:" >> $GITHUB_STEP_SUMMARY
          echo '```bash' >> $GITHUB_STEP_SUMMARY
          echo "git subtree pull --prefix=shared/transaction-id-generator \\" >> $GITHUB_STEP_SUMMARY
          echo "  https://github.com/sagarbehere/ofx-to-beancount.git transaction-id-generator-only \\" >> $GITHUB_STEP_SUMMARY
          echo "  --squash" >> $GITHUB_STEP_SUMMARY
          echo '```' >> $GITHUB_STEP_SUMMARY
```

## Important Notes

1. **The subtree branch is read-only** - Never edit it directly
2. **Always regenerate from main** - It's a snapshot, not a working branch
3. **Force push is normal** - The branch is recreated each time
4. **Users should use --squash** - Keeps their history clean
5. **The main branch is unaffected** - This is just for distribution

## Troubleshooting

### "Updates were rejected because the tip of your current branch is behind"

This is normal! The subtree branch history changes. Use:
```bash
git push origin transaction-id-generator-only --force-with-lease
```

### "fatal: ambiguous argument 'transaction-id-generator-only'"

The branch doesn't exist yet. Create it:
```bash
git subtree split --prefix=shared_libs/transaction_id_generator -b transaction-id-generator-only
```

### Consumer project has conflicts during pull

The consumer should reset and pull fresh:
```bash
# In consumer project
git subtree pull --prefix=shared/transaction-id-generator \
  https://github.com/sagarbehere/ofx-to-beancount.git transaction-id-generator-only \
  --squash --strategy=theirs
```

## Quick Reference

| Action | Command |
|--------|---------|
| Create distribution branch | `git subtree split --prefix=shared_libs/transaction_id_generator -b transaction-id-generator-only` |
| Push distribution branch | `git push origin transaction-id-generator-only --force-with-lease` |
| Add to new project | `git subtree add --prefix=shared/transaction-id-generator https://github.com/sagarbehere/ofx-to-beancount.git transaction-id-generator-only --squash` |
| Pull updates | `git subtree pull --prefix=shared/transaction-id-generator https://github.com/sagarbehere/ofx-to-beancount.git transaction-id-generator-only --squash` |

## See Also

- [Git Subtree Documentation](https://github.com/git/git/blob/master/contrib/subtree/git-subtree.txt)
- [Transaction ID Generator README](../shared_libs/transaction_id_generator/README.md)