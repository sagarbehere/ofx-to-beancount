"""
Interactive CLI interface for transaction review and processing.

This module provides the interactive user interface for reviewing and 
correcting transaction categorizations using prompt_toolkit.
"""

from typing import List, Dict, Any, Optional, Tuple
from decimal import Decimal
from prompt_toolkit import prompt
from prompt_toolkit.completion import FuzzyWordCompleter, Completer, Completion
from prompt_toolkit.shortcuts import yes_no_dialog
from prompt_toolkit.formatted_text import HTML
import re
import click


class TransactionCompleter(Completer):
    """Custom completer for transaction accounts with fuzzy matching."""
    
    def __init__(self, accounts: List[str]):
        self.accounts = accounts
        self.fuzzy_completer = FuzzyWordCompleter(accounts)
        # Define single-letter commands that should not trigger completion
        self.commands = {'s', 'k', 'p', 'q'}
    
    def get_completions(self, document, complete_event):
        """Get completions for account names, but not for single-letter commands."""
        current_text = document.text.strip().lower()
        
        # Don't provide completions for single-letter commands
        if len(current_text) == 1 and current_text in self.commands:
            return []
        
        # Don't provide completions for empty input
        if not current_text:
            return []
            
        # Only provide fuzzy account completions for multi-character input
        if len(current_text) > 1:
            return self.fuzzy_completer.get_completions(document, complete_event)
        
        # Default: return empty list for any other cases
        return []


class InteractiveProcessor:
    """Interactive processor for transaction review and correction."""
    
    def __init__(self, valid_accounts: List[str]):
        self.valid_accounts = valid_accounts
        self.completer = TransactionCompleter(valid_accounts)
        self.transaction_updates = []
        self.current_index = 0
        self.transactions = []
    
    def review_transactions_interactively(self, transactions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Interactively review and correct transactions.
        
        Args:
            transactions: List of transaction data from API
            
        Returns:
            List of transaction updates for API
        """
        self.transactions = transactions
        self.transaction_updates = []
        self.current_index = 0
        
        
        while self.current_index < len(self.transactions):
            transaction = self.transactions[self.current_index]
            
            try:
                should_continue = self._review_single_transaction(transaction)
                if should_continue:
                    self.current_index += 1
                # If should_continue is False, stay at current transaction (for navigation)
            except KeyboardInterrupt:
                if self._confirm_quit():
                    break
        
        return self.transaction_updates
    
    def _review_single_transaction(self, transaction: Dict[str, Any]) -> bool:
        """
        Review a single transaction interactively.
        
        Returns:
            bool: True if should continue to next transaction, False if should stay at current
        """
        
        # Display transaction details
        self._display_transaction_summary(transaction)
        
        
        # Get user input for category
        suggested_category = transaction.get('suggested_category', 'Expenses:Unknown')
        confidence = transaction.get('confidence', 0.0)
        
        # Display suggested category with confidence-based coloring
        if confidence >= 0.9:
            category_display = click.style(suggested_category, fg='green')
        elif confidence < 0.2:
            category_display = click.style(suggested_category, fg='red')
        else:
            category_display = click.style(suggested_category, fg='yellow')
        
        print(f"Suggested category: {category_display}")
        
        # Get user input
        user_action = self._get_user_action()
        
        if user_action == 'accept':
            # Prompt for note, then accept suggestion
            narration = self._prompt_for_note()
            self._accept_suggestion_with_note(transaction, suggested_category, narration)
            return True  # Move to next transaction
        elif user_action == 'custom':
            # This is handled in _get_user_action, but we still need to prompt for note
            narration = self._prompt_for_note()
            self._accept_custom_category_with_note(transaction, transaction.get('_temp_category'), narration)
            return True  # Move to next transaction
        elif user_action == 'split':
            self._handle_split_transaction(transaction)
            return True  # Move to next transaction
        elif user_action == 'skip':
            self._handle_skip_transaction(transaction)
            return True  # Move to next transaction
        elif user_action == 'previous':
            self._go_to_previous()
            return False  # Stay at current (now previous) transaction to review it
        elif user_action == 'quit':
            if self._confirm_quit():
                self.current_index = len(self.transactions)  # Exit loop
            return False  # Don't continue
        
        return True  # Default: continue to next transaction
    
    def _display_transaction_summary(self, transaction: Dict[str, Any]) -> None:
        """Display a summary of the transaction."""
        index = self.current_index + 1
        total = len(self.transactions)
        
        # Main transaction line
        print(f"\n[{index}/{total}] {transaction['date']} | {transaction['payee']} | {transaction['amount']:,.2f} {transaction['currency']}")
        
        # Duplicate warning (only if duplicate detected)
        if transaction.get('is_potential_duplicate'):
            duplicate_details = transaction.get('duplicate_details', {})
            existing_date = duplicate_details.get('existing_transaction_date', 'Unknown')
            existing_payee = duplicate_details.get('existing_transaction_payee', 'Unknown')
            existing_amount = duplicate_details.get('existing_transaction_amount', 0)
            print(f"🚨 POTENTIAL DUPLICATE of {existing_date} {existing_payee} {existing_amount:,.2f} {transaction['currency']}")
        
        print()  # Empty line for spacing
    
    def _get_user_action(self) -> str:
        """Get user action for the transaction."""
        
        prompt_text = "Enter category [Enter=accept, s=split, k=skip, p=previous, q=quit]: "
        
        try:
            user_input = prompt(
                HTML(prompt_text),
                completer=self.completer,
                complete_while_typing=True
            ).strip()
            
            if not user_input:
                return 'accept'
            elif user_input.lower() == 's':
                return 'split'
            elif user_input.lower() == 'k':
                return 'skip'
            elif user_input.lower() == 'p':
                return 'previous'
            elif user_input.lower() == 'q':
                return 'quit'
            else:
                # Check if it's a valid account name
                if user_input in self.valid_accounts:
                    # Store the custom category temporarily for later use
                    self.transactions[self.current_index]['_temp_category'] = user_input
                    return 'custom'
                else:
                    print(f"❌ Invalid account: {user_input}")
                    return self._get_user_action(suggested_category)
        
        except KeyboardInterrupt:
            return 'quit'
    
    def _prompt_for_note(self) -> str:
        """Prompt user to enter a note/narration."""
        narration = prompt("Enter note (or press Enter to skip): ").strip()
        return narration
    
    def _accept_suggestion_with_note(self, transaction: Dict[str, Any], category: str, narration: str) -> None:
        """Accept the suggested category with narration."""
        update = {
            'transaction_id': transaction['id'],
            'confirmed_category': category,
            'narration': narration
        }
        self.transaction_updates.append(update)
        print(f"Accepted: {category}")
    
    def _accept_custom_category_with_note(self, transaction: Dict[str, Any], category: str, narration: str) -> None:
        """Accept a custom category with narration."""
        update = {
            'transaction_id': transaction['id'],
            'confirmed_category': category,
            'narration': narration
        }
        self.transaction_updates.append(update)
        print(f"Set category: {category}")
    
    def _handle_custom_category(self, transaction: Dict[str, Any]) -> None:
        """Handle user entering a custom category."""
        # This case is handled in _get_user_action
        pass
    
    def _handle_split_transaction(self, transaction: Dict[str, Any]) -> None:
        """Handle splitting a transaction into multiple categories."""
        print(f"\nSplitting transaction: {transaction['amount']:,.2f} {transaction['currency']}")
        
        splits = []
        remaining_amount = abs(float(transaction['amount']))
        
        while remaining_amount > 0.01:  # Continue until fully allocated
            print(f"\nRemaining amount: {remaining_amount:.2f} {transaction['currency']}")
            
            # Get category
            category = prompt(
                "Enter account for this split: ",
                completer=self.completer,
                complete_while_typing=True
            ).strip()
            
            if not category:
                break
            
            if category not in self.valid_accounts:
                print(f"❌ Invalid account: {category}")
                continue
            
            # Get amount
            try:
                amount_str = prompt(f"Enter amount for {category} ({transaction['currency']}): ").strip()
                amount = float(amount_str)
                
                if amount <= 0 or amount > remaining_amount:
                    print(f"Invalid amount. Must be between 0 and {remaining_amount:.2f} {transaction['currency']}")
                    continue
                
                splits.append({
                    'account': category,
                    'amount': amount,
                    'currency': transaction['currency']
                })
                
                remaining_amount -= amount
                print(f"Added split: {category} {amount:.2f} {transaction['currency']}")
                
            except ValueError:
                print("❌ Invalid amount format")
                continue
        
        if splits and remaining_amount <= 0.01:
            # Get narration for split transaction
            narration = prompt("Enter note for split transaction (optional): ").strip()
            
            update = {
                'transaction_id': transaction['id'],
                'confirmed_category': None,  # No single category for splits
                'narration': narration or '',  # Only use user-entered narration
                'splits': splits
            }
            self.transaction_updates.append(update)
            print(f"Split transaction into {len(splits)} categories")
        else:
            print("❌ Split cancelled - amounts don't balance")
    

    def _handle_skip_transaction(self, transaction: Dict[str, Any]) -> None:
        """Handle skipping a transaction (exclude from output)."""
        update = {
            'transaction_id': transaction['id'],
            'action': 'skip',
            'reason': 'user_skip'
        }
        self.transaction_updates.append(update)
        print("Transaction skipped (excluded from output)")
    
    
    def _go_to_previous(self) -> None:
        """Go back to the previous transaction."""
        if self.current_index > 0:
            self.current_index -= 1
            
            # Remove the last update for this transaction if it exists
            current_transaction = self.transactions[self.current_index]
            self.transaction_updates = [
                update for update in self.transaction_updates 
                if update.get('transaction_id') != current_transaction['id']
            ]
            
            print("⬅️  Going back to previous transaction")
        else:
            print("❌ Already at first transaction")
    
    def _confirm_quit(self) -> bool:
        """Confirm if user wants to quit the review process."""
        remaining = len(self.transactions) - self.current_index
        
        return yes_no_dialog(
            title="Quit Review",
            text=f"Are you sure you want to quit?\n\n"
                 f"Transactions reviewed: {self.current_index}\n"
                 f"Transactions remaining: {remaining}\n\n"
                 f"Reviewed transactions will be processed."
        ).run()


def prompt_account_confirmation(detected_account: str, detected_currency: str, 
                               confidence: float, valid_accounts: List[str]) -> Tuple[str, str]:
    """
    Prompt user to confirm or correct the detected account and currency.
    
    Args:
        detected_account: Auto-detected account name
        detected_currency: Auto-detected currency
        confidence: Confidence score for detection
        valid_accounts: List of valid account names
        
    Returns:
        Tuple of (confirmed_account, confirmed_currency)
    """
    # Confirm account
    completer = TransactionCompleter(valid_accounts)
    
    account_prompt = f"\nConfirm account [{detected_account}]: "
    confirmed_account = prompt(
        account_prompt,
        completer=completer,
        complete_while_typing=True,
        default=detected_account
    ).strip()
    
    if not confirmed_account:
        confirmed_account = detected_account
    
    # Confirm currency
    currency_prompt = f"Confirm currency [{detected_currency}]: "
    confirmed_currency = prompt(currency_prompt, default=detected_currency).strip()
    
    if not confirmed_currency:
        confirmed_currency = detected_currency
    
    
    return confirmed_account, confirmed_currency


def display_processing_summary(session_summary: Dict[str, Any]) -> None:
    """Display a summary of the processing results."""
    print(f"\n📊 Processing Summary")
    print("="*50)
    print(f"📈 Total transactions: {session_summary.get('total_transactions', 0)}")
    print(f"✅ Categorized: {session_summary.get('categorized_transactions', 0)}")
    print(f"🔄 Split transactions: {session_summary.get('split_transactions', 0)}")
    print(f"⏭️  Skipped: {session_summary.get('skipped_transactions', 0)}")
    


def confirm_export(export_preview: str, transaction_count: int) -> bool:
    """
    Confirm export operation by showing preview.
    
    Args:
        export_preview: Preview of Beancount output
        transaction_count: Number of transactions to export
        
    Returns:
        True if user confirms export, False otherwise
    """
    return yes_no_dialog(
        title="Confirm Export",
        text=f"Export {transaction_count} transactions to Beancount file?"
    ).run()