"""
Machine learning classifier for transaction categorization.

This module implements ML-based transaction categorization using Random Forest
with TF-IDF vectorization as specified in the requirements.
"""

import os
import re
from typing import List, Tuple, Optional, Any
from decimal import Decimal
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import Pipeline
from sklearn.model_selection import cross_val_score
import numpy as np
from beancount import loader
from beancount.core import data

from api.models.transaction import Transaction


class ClassifierError(Exception):
    """Exception raised when classifier operations fail."""
    pass


class TrainingDataError(Exception):
    """Exception raised when training data is insufficient or invalid."""
    pass


def preprocess_description(text: str) -> str:
    """
    Preprocess transaction description text for ML training.
    
    Based on specification requirements:
    - Remove all special characters (replace with spaces)
    - Remove all words containing numbers  
    - Remove all single characters
    - Substitute multiple spaces with single space
    - Convert to lowercase
    - Remove specific terms: "aplpay", "com"
    
    Args:
        text: Raw description text (payee + memo)
        
    Returns:
        Preprocessed text ready for vectorization
    """
    if not text:
        return ""
    
    # Convert to lowercase
    text = text.lower()
    
    # Remove specific terms
    text = text.replace("aplpay", " ").replace("com", " ")
    
    # Replace all special characters with spaces
    text = re.sub(r'[^a-zA-Z0-9\s]', ' ', text)
    
    # Split into words
    words = text.split()
    
    # Remove words containing numbers and single characters
    filtered_words = []
    for word in words:
        if not re.search(r'\d', word) and len(word) > 1:
            filtered_words.append(word)
    
    # Join back and normalize spaces
    result = ' '.join(filtered_words)
    result = re.sub(r'\s+', ' ', result).strip()
    
    return result


def train_classifier(training_data: List[Transaction]) -> Optional[Pipeline]:
    """
    Train a Random Forest classifier on transaction data.
    
    Args:
        training_data: List of transactions with known categories
        
    Returns:
        Trained sklearn Pipeline or None if insufficient data
        
    Raises:
        TrainingDataError: If training data is insufficient or invalid
    """
    if not training_data:
        raise TrainingDataError("No training data provided")
    
    if len(training_data) < 10:
        raise TrainingDataError(f"Insufficient training data: {len(training_data)} transactions (minimum: 10)")
    
    # Prepare features and labels
    features = []
    labels = []
    
    for transaction in training_data:
        # Combine payee and memo for feature
        description = f"{transaction.payee} {transaction.memo}".strip()
        processed_description = preprocess_description(description)
        
        if not processed_description:
            continue  # Skip empty descriptions
        
        features.append(processed_description)
        
        # Extract category from categorized accounts
        if transaction.categorized_accounts:
            # Use first categorized account as label
            labels.append(transaction.categorized_accounts[0].account)
        else:
            labels.append("Expenses:Unknown")
    
    if len(features) < 5:
        raise TrainingDataError(f"Insufficient valid training features: {len(features)}")
    
    # Check for minimum category diversity
    unique_categories = set(labels)
    if len(unique_categories) < 2:
        raise TrainingDataError("Training data must have at least 2 different categories")
    
    try:
        # Create pipeline with TF-IDF and Random Forest
        # Use simple reference implementation approach - proven to work well  
        pipeline = Pipeline([
            ('tfidf', TfidfVectorizer()),    # Use sklearn defaults like reference
            ('classifier', RandomForestClassifier(
                n_estimators=100,            # Reference implementation value
                random_state=42,
                n_jobs=-1                    # Use all CPU cores
            ))
        ])
        
        # Train the model
        pipeline.fit(features, labels)
        
        # Validate with cross-validation if enough data
        if len(features) >= 10:
            cv_scores = cross_val_score(pipeline, features, labels, cv=3, scoring='accuracy')
            print(f"Cross-validation accuracy: {cv_scores.mean():.3f} (+/- {cv_scores.std() * 2:.3f})")
        
        return pipeline
    
    except Exception as e:
        raise ClassifierError(f"Failed to train classifier: {e}")


def categorize_transaction(transaction: Transaction, classifier: Pipeline) -> Tuple[str, float]:
    """
    Categorize a transaction using the trained classifier.
    
    Args:
        transaction: Transaction to categorize
        classifier: Trained classifier pipeline
        
    Returns:
        Tuple of (predicted_category, confidence_score)
    """
    if not classifier:
        return "Expenses:Unknown", 0.0
    
    try:
        # Prepare feature
        description = f"{transaction.payee} {transaction.memo}".strip()
        processed_description = preprocess_description(description)
        
        if not processed_description:
            return "Expenses:Unknown", 0.0
        
        # Get prediction and probability
        prediction = classifier.predict([processed_description])[0]
        probabilities = classifier.predict_proba([processed_description])[0]
        
        # Get confidence (max probability)
        confidence = float(np.max(probabilities))
        
        return prediction, confidence
    
    except Exception as e:
        print(f"Error categorizing transaction: {e}")
        return "Expenses:Unknown", 0.0


def extract_training_data_from_beancount(file_path: str, target_account: Optional[str] = None) -> List[Transaction]:
    """
    Extract training data from a Beancount file by parsing transaction directives.
    
    Args:
        file_path: Path to Beancount file
        target_account: Optional account to filter transactions (e.g., 'Liabilities:Amex:BlueCashPreferred')
                       If provided, only transactions involving this account are included
        
    Returns:
        List of Transaction objects for training
        
    Raises:
        FileNotFoundError: If file doesn't exist
        TrainingDataError: If file cannot be parsed or has no transactions
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Training file not found: {file_path}")
    
    try:
        entries, errors, options_map = loader.load_file(file_path)
        
        if errors:
            print(f"Warning: {len(errors)} parsing errors in training file")
        
        transactions = []
        
        for entry in entries:
            if isinstance(entry, data.TxnPosting):
                # Skip non-transaction entries
                continue
            elif hasattr(entry, 'postings') and hasattr(entry, 'date'):
                # If target_account is specified, check if this transaction involves it
                if target_account:
                    has_target_account = False
                    for posting in entry.postings:
                        if posting.account == target_account:
                            has_target_account = True
                            break
                    
                    if not has_target_account:
                        continue
                
                # This is a transaction directive
                txn_date = entry.date.strftime('%Y-%m-%d')
                payee = getattr(entry, 'payee', '') or ''
                narration = getattr(entry, 'narration', '') or ''
                
                # Create postings for categorization
                postings = []
                for posting in entry.postings:
                    if posting.units and posting.units.number:
                        postings.append({
                            'account': posting.account,
                            'amount': posting.units.number,
                            'currency': posting.units.currency
                        })
                
                # Skip if no valid postings
                if not postings:
                    continue
                
                # Create transaction for training
                # Use narration as memo for feature extraction
                transaction = Transaction(
                    date=txn_date,
                    payee=payee,
                    memo=narration,
                    amount=Decimal('0'),  # Not used for training
                    currency=postings[0]['currency'] if postings else 'USD',
                    account='',  # Not used for training
                    categorized_accounts=[],  # Will be populated below
                    narration='',
                    transaction_id="",  # Not used for training
                    ofx_id=None,  # Not used for training
                    is_split=len(postings) > 2,
                    original_ofx_id=f"training_{hash(f'{txn_date}_{payee}_{narration}')}"
                )
                
                # Add expense/income accounts as categories
                for posting_data in postings:
                    account = posting_data['account']
                    # Only use expense and income accounts for training
                    if account.startswith(('Expenses:', 'Income:')):
                        from api.models.transaction import Posting
                        posting = Posting(
                            account=account,
                            amount=abs(posting_data['amount']),  # Use absolute value
                            currency=posting_data['currency']
                        )
                        transaction.categorized_accounts.append(posting)
                
                # Only include transactions with expense/income categories
                if transaction.categorized_accounts:
                    transactions.append(transaction)
        
        if not transactions:
            raise TrainingDataError("No valid transactions found in training file")
        
        print(f"Extracted {len(transactions)} training transactions from Beancount file")
        return transactions
    
    except Exception as e:
        if isinstance(e, (FileNotFoundError, TrainingDataError)):
            raise
        raise TrainingDataError(f"Failed to parse training file: {e}")


def validate_classifier_training(training_file_path: str, target_account: Optional[str] = None) -> List[str]:
    """
    Validate that a file can be used for classifier training.
    
    Args:
        training_file_path: Path to potential training file
        target_account: Optional account to filter transactions
        
    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []
    
    if not os.path.exists(training_file_path):
        errors.append(f"Training file not found: {training_file_path}")
        return errors
    
    try:
        training_data = extract_training_data_from_beancount(training_file_path, target_account)
        
        if len(training_data) < 10:
            errors.append(f"Insufficient training data: {len(training_data)} transactions (minimum: 10)")
        
        # Check for category diversity
        categories = set()
        for transaction in training_data:
            for posting in transaction.categorized_accounts:
                categories.add(posting.account)
        
        if len(categories) < 2:
            errors.append("Training data must have at least 2 different expense/income categories")
        
        # Check for valid descriptions
        valid_descriptions = 0
        for transaction in training_data:
            description = f"{transaction.payee} {transaction.memo}".strip()
            if preprocess_description(description):
                valid_descriptions += 1
        
        if valid_descriptions < 5:
            errors.append(f"Too few transactions with valid descriptions: {valid_descriptions}")
    
    except Exception as e:
        errors.append(f"Training file validation failed: {e}")
    
    return errors


def get_confidence_threshold() -> float:
    """Get the confidence threshold for auto-categorization."""
    return 0.7  # 70% as specified in requirements