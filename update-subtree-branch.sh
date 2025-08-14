#!/bin/bash
# update-subtree-branch.sh
# Updates the transaction-id-generator-only branch after changes to main
#
# Usage: ./update-subtree-branch.sh
#
# This script should be run after making changes to the transaction ID generator
# in the main branch to update the distribution branch that other projects pull from.

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}📦 Updating transaction-id-generator-only branch...${NC}"
echo ""

# Ensure we're in the right repository
if [ ! -d ".git" ]; then
    echo -e "${RED}❌ Error: Not in a git repository${NC}"
    exit 1
fi

# Check if we have uncommitted changes
if [ -n "$(git status --porcelain)" ]; then
    echo -e "${YELLOW}⚠️  Warning: You have uncommitted changes${NC}"
    echo "Please commit or stash your changes before updating the subtree branch."
    echo ""
    git status --short
    echo ""
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${RED}Aborted${NC}"
        exit 1
    fi
fi

# Ensure we're on main branch
echo "→ Switching to main branch..."
git checkout main

# Pull latest changes
echo "→ Pulling latest changes from origin..."
git pull origin main

# Delete old branch locally (ignore error if it doesn't exist)
echo "→ Deleting old local branch (if exists)..."
git branch -D transaction-id-generator-only 2>/dev/null || true

# Recreate from current main
echo "→ Creating new subtree branch from shared_libs/transaction_id_generator/..."
COMMIT_HASH=$(git subtree split --prefix=shared_libs/transaction_id_generator -b transaction-id-generator-only)

echo -e "${GREEN}✓ Created branch at commit: ${COMMIT_HASH:0:8}${NC}"

# Push to origin (force push is OK for this read-only branch)
echo "→ Pushing to origin..."
if git push origin transaction-id-generator-only --force-with-lease; then
    echo -e "${GREEN}✅ Distribution branch updated successfully!${NC}"
else
    echo -e "${YELLOW}⚠️  Push failed. Trying with --force...${NC}"
    git push origin transaction-id-generator-only --force
    echo -e "${GREEN}✅ Distribution branch updated (force pushed)${NC}"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}Other projects can now update with:${NC}"
echo ""
echo "  git subtree pull --prefix=shared/transaction-id-generator \\"
echo "    https://github.com/sagarbehere/ofx-to-beancount.git transaction-id-generator-only \\"
echo "    --squash"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"