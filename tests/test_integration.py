"""
Integration tests for the OFX to Beancount converter.

These tests verify that all components work together correctly
in an end-to-end workflow.
"""

import os
import tempfile
import time
from pathlib import Path
import yaml
import pytest
from decimal import Decimal

# Add parent directory to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from cli.api_client import APIClient, APIClientError
from api.main import app
from core.ofx_parser import parse_ofx_file, AccountInfo, FileStats
from core.account_mapper import map_account, AccountMappingResult
from core.classifier import preprocess_description, extract_training_data_from_beancount
from api.models.config import Config


class TestIntegration:
    """Integration tests for the complete workflow."""
    
    def setup_method(self):
        """Set up test environment."""
        self.test_dir = Path(__file__).parent
        self.temp_dir = tempfile.mkdtemp()
        
        # Create sample configuration
        self.config_data = {
            'accounts': {
                'mappings': [
                    {
                        'institution': 'TEST_BANK',
                        'account_type': 'CHECKING',
                        'account_id': '12345',
                        'beancount_account': 'Assets:TestBank:Checking',
                        'currency': 'USD'
                    }
                ]
            },
            'default_currency': 'USD'
        }
        
        # Create sample accounts file
        self.accounts_content = """
2020-01-01 open Assets:TestBank:Checking USD
2020-01-01 open Expenses:Food:Groceries USD
2020-01-01 open Expenses:Transportation:Gas USD
2020-01-01 open Expenses:Entertainment USD
2020-01-01 open Income:Salary USD
"""
        
        # Create sample training data
        self.training_content = """
2023-01-15 * "GROCERY STORE" "Weekly groceries"
  Expenses:Food:Groceries           85.50 USD
  Assets:TestBank:Checking         -85.50 USD

2023-01-20 * "GAS STATION" "Fill up tank"
  Expenses:Transportation:Gas       45.00 USD
  Assets:TestBank:Checking         -45.00 USD

2023-01-25 * "RESTAURANT" "Dinner out"
  Expenses:Entertainment           65.75 USD
  Assets:TestBank:Checking         -65.75 USD
"""
    
    def create_test_ofx(self) -> str:
        """Create a minimal test OFX file."""
        ofx_content = """<?xml version="1.0" encoding="UTF-8" ?>
<OFX>
<SIGNONMSGSRSV1>
<SONRS>
<STATUS>
<CODE>0</CODE>
<SEVERITY>INFO</SEVERITY>
</STATUS>
<DTSERVER>20231215120000</DTSERVER>
<LANGUAGE>ENG</LANGUAGE>
</SONRS>
</SIGNONMSGSRSV1>
<BANKMSGSRSV1>
<STMTTRNRS>
<STMTRS>
<CURDEF>USD</CURDEF>
<BANKACCTFROM>
<BANKID>123456789</BANKID>
<ACCTID>12345</ACCTID>
<ACCTTYPE>CHECKING</ACCTTYPE>
</BANKACCTFROM>
<BANKTRANLIST>
<DTSTART>20231201000000</DTSTART>
<DTEND>20231215000000</DTEND>
<STMTTRN>
<TRNTYPE>DEBIT</TRNTYPE>
<DTPOSTED>20231205120000</DTPOSTED>
<TRNAMT>-85.50</TRNAMT>
<FITID>202312051</FITID>
<NAME>GROCERY STORE</NAME>
<MEMO>Weekly groceries</MEMO>
</STMTTRN>
<STMTTRN>
<TRNTYPE>DEBIT</TRNTYPE>
<DTPOSTED>20231210150000</DTPOSTED>
<TRNAMT>-45.00</TRNAMT>
<FITID>202312102</FITID>
<NAME>GAS STATION</NAME>
<MEMO>Fill up tank</MEMO>
</STMTTRN>
</BANKTRANLIST>
<LEDGERBAL>
<BALAMT>1234.56</BALAMT>
<DTASOF>20231215120000</DTASOF>
</LEDGERBAL>
</STMTRS>
</STMTTRNRS>
</BANKMSGSRSV1>
</OFX>"""
        
        ofx_file = os.path.join(self.temp_dir, "test.ofx")
        with open(ofx_file, 'w') as f:
            f.write(ofx_content)
        return ofx_file
    
    def create_test_files(self) -> dict:
        """Create all test files needed for integration testing."""
        files = {}
        
        # OFX file
        files['ofx'] = self.create_test_ofx()
        
        # Config file
        config_file = os.path.join(self.temp_dir, "config.yaml")
        with open(config_file, 'w') as f:
            yaml.dump(self.config_data, f)
        files['config'] = config_file
        
        # Accounts file
        accounts_file = os.path.join(self.temp_dir, "accounts.beancount")
        with open(accounts_file, 'w') as f:
            f.write(self.accounts_content)
        files['accounts'] = accounts_file
        
        # Training file
        training_file = os.path.join(self.temp_dir, "training.beancount")
        with open(training_file, 'w') as f:
            f.write(self.training_content)
        files['training'] = training_file
        
        # Output file
        files['output'] = os.path.join(self.temp_dir, "output.beancount")
        
        return files
    
    def test_ofx_parsing(self):
        """Test OFX file parsing functionality."""
        files = self.create_test_files()
        
        # Test OFX parsing
        transactions, account_info, file_stats = parse_ofx_file(files['ofx'])
        
        # Verify results
        assert len(transactions) == 2
        assert account_info.institution == ""  # May be empty in test OFX
        assert account_info.account_id == "12345"
        assert file_stats.transaction_count == 2
        assert file_stats.currency == "USD"
        
        # Check transaction details
        first_transaction = transactions[0]
        assert first_transaction.payee == "GROCERY STORE"
        assert first_transaction.amount == Decimal('-85.50')
        assert first_transaction.memo == "Weekly groceries"
    
    def test_account_mapping(self):
        """Test account mapping functionality."""
        config = Config.from_dict(self.config_data)
        
        # Create test account info
        account_info = AccountInfo(
            institution="TEST_BANK",
            account_type="CHECKING", 
            account_id="12345",
            currency="USD"
        )
        
        # Test mapping
        result = map_account(account_info, config)
        
        assert result.account == "Assets:TestBank:Checking"
        assert result.currency == "USD"
        assert result.confidence == 1.0  # Should be exact match
    
    def test_ml_preprocessing(self):
        """Test ML text preprocessing."""
        test_texts = [
            "GROCERY STORE #123 - WEEKLY FOOD",
            "Gas Station 456 com",
            "Restaurant aplpay payment"
        ]
        
        expected_results = [
            "grocery store weekly food",
            "gas station",
            "restaurant payment"
        ]
        
        for text, expected in zip(test_texts, expected_results):
            result = preprocess_description(text)
            assert result == expected
    
    def test_training_data_extraction(self):
        """Test extraction of training data from Beancount file."""
        files = self.create_test_files()
        
        # Extract training data
        training_data = extract_training_data_from_beancount(files['training'])
        
        # Verify results
        assert len(training_data) == 3
        
        # Check first transaction
        first_txn = training_data[0]
        assert first_txn.payee == "GROCERY STORE"
        assert first_txn.memo == "Weekly groceries"
        assert len(first_txn.categorized_accounts) == 1
        assert first_txn.categorized_accounts[0].account == "Expenses:Food:Groceries"
    
    def test_config_validation(self):
        """Test configuration validation."""
        from core.account_mapper import validate_config_accounts, load_accounts_from_file
        
        files = self.create_test_files()
        config = Config.from_dict(self.config_data)
        valid_accounts = load_accounts_from_file(files['accounts'])
        
        # Test valid configuration
        errors = validate_config_accounts(config, files['accounts'])
        assert len(errors) == 0
        
        # Test invalid configuration
        invalid_config_data = self.config_data.copy()
        invalid_config_data['accounts']['mappings'][0]['beancount_account'] = 'Invalid:Account'
        invalid_config = Config.from_dict(invalid_config_data)
        
        errors = validate_config_accounts(invalid_config, files['accounts'])
        assert len(errors) > 0
        assert "not found in accounts file" in errors[0]
    
    @pytest.mark.skip(reason="Requires running API server - integration test")
    def test_api_integration(self):
        """Test API integration (requires manual server setup)."""
        # This test would require starting the API server
        # and testing the full API workflow
        files = self.create_test_files()
        
        api_client = APIClient()
        
        # Test would include:
        # 1. Initialize session
        # 2. Categorize transactions  
        # 3. Update transactions
        # 4. Export results
        
        pass
    
    def teardown_method(self):
        """Clean up test environment."""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)


def test_basic_imports():
    """Test that all modules can be imported without errors."""
    # Core modules
    from core import ofx_parser, account_mapper, classifier, duplicate_detector, beancount_generator
    
    # API modules  
    from api import main
    from api.models import transaction, session, config
    from api.routers import session as session_router, transactions, export
    from api.services import session_manager, validator
    
    # CLI modules
    from cli import main as cli_main, api_client, interactive
    
    # All imports successful
    assert True


def test_data_model_validation():
    """Test data model validation and serialization."""
    from api.models.transaction import TransactionAPI, PostingAPI
    from api.models.config import AccountMappingAPI, ConfigAPI
    
    # Test transaction model
    transaction_data = {
        'id': 'test_123',
        'date': '2023-12-05',
        'payee': 'Test Payee',
        'memo': 'Test memo',
        'amount': 85.50,
        'currency': 'USD',
        'suggested_category': 'Expenses:Food',
        'confidence': 0.85
    }
    
    transaction = TransactionAPI(**transaction_data)
    assert transaction.id == 'test_123'
    assert transaction.confidence == 0.85
    
    # Test config model
    config_data = {
        'accounts': {
            'mappings': [{
                'institution': 'TEST',
                'account_id': '123',
                'beancount_account': 'Assets:Test'
            }]
        },
        'default_currency': 'USD'
    }
    
    config = ConfigAPI(**config_data)
    assert config.default_currency == 'USD'


if __name__ == "__main__":
    # Run basic tests
    test = TestIntegration()
    test.setup_method()
    
    try:
        print("Testing OFX parsing...")
        test.test_ofx_parsing()
        print("✅ OFX parsing test passed")
        
        print("Testing account mapping...")
        test.test_account_mapping()
        print("✅ Account mapping test passed")
        
        print("Testing ML preprocessing...")
        test.test_ml_preprocessing()
        print("✅ ML preprocessing test passed")
        
        print("Testing training data extraction...")
        test.test_training_data_extraction()
        print("✅ Training data extraction test passed")
        
        print("Testing configuration validation...")
        test.test_config_validation()
        print("✅ Configuration validation test passed")
        
        print("Testing basic imports...")
        test_basic_imports()
        print("✅ Import test passed")
        
        print("Testing data model validation...")
        test_data_model_validation()
        print("✅ Data model validation test passed")
        
        print("\n🎉 All integration tests passed!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        test.teardown_method()