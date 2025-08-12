# OFX to Beancount Converter

Convert transactions in OFX (Open Financial Exchange) files to [Beancount](https://github.com/beancount/beancount) format with ML-based transaction categorization. All data processing happens locally. No external services or Internet connection are needed.

Inspired by [Reckon](https://github.com/cantino/reckon).

DISCLAIMER: Has _ONLY_ been tested on a couple of financial institutions that I personally use for bank accounts and credit cards.

## Features

- **Machine Learning Categorization** - Locally trains on your existing Beancount data to automatically categorize transactions (Determine the accounts to which postings should be made)
- **Interactive Review** - Rich CLI interface for reviewing and correcting predicted categorizations
- **Duplicate Detection** - Identifies potential duplicates using fuzzy string matching
- **Transaction Splitting** - Split transactions across multiple categories
- **Transaction Skipping** - Skip transactions if needed so they are not included in the output

## Installation

### Prerequisites

- Python 3.8 or higher
- pip package manager

### Install Dependencies

It's recommended to do the installation in a **Python virtual environment**.

```bash
git clone git@github.com:sagarbehere/ofx-to-beancount.git
cd ofx-to-beancount
pip install -r requirements.txt
```

### Required Dependencies

The main dependencies are:
- `fastapi` - Web framework for API server
- `uvicorn` - ASGI server for running the API
- `ofxparse` - OFX file parsing and validation
- `scikit-learn` - Machine learning for transaction categorization
- `pandas` - Data manipulation and analysis
- `beancount` - Beancount parsing, validation, and file operations
- `pydantic` - Data validation and serialization for API models
- `PyYAML` - YAML configuration file parsing
- `prompt_toolkit` - Interactive CLI with rich user interface
- `requests` - HTTP client for API communication
- `click` - Command-line interface framework
- `rapidfuzz` - Fuzzy string matching for duplicate detection

## Quick Start

### 1. Create Configuration File

Copy and adjust the example file found in `config/example_config.yaml`.

To help the program guess the right Beancount account and currency from the OFX file, you should provide account mapping configuration in the config file. For example, if you have downloaded OFX statements from American Express and Bank of America, let's call them `amex.ofx` and `bofa-checking.ofx`, you could do a one-time interactive exploration of those files in a Python REPL as shown below. The resulting information will help you to create the correct config file, as shown further below.

```
(beancount) sagar@Sagars-MacBook-Pro Downloads % python3
Python 3.13.5 (main, Jun 11 2025, 15:36:57) [Clang 17.0.0 (clang-1700.0.13.3)] on darwin
Type "help", "copyright", "credits" or "license" for more information.
>>> import codecs
>>> from ofxparse import OfxParser
>>> fileobj = codecs.open("amex.ofx")
>>> ofx = OfxParser.parse(fileobj)
>>> account = ofx.account
>>> account.institution.organization
'AMEX'
>>> account.account_type
''
>>> account.account_id
'123ABCD456EFGHI|12345'
>>> account.curdef
'USD'
>>> fileobj = codecs.open("bofa-checking.ofx")
>>> ofx = OfxParser.parse(fileobj)
>>> account = ofx.account
>>> account.institution.organization
'Bank of America'
>>> account.account_type
'CHECKING'
>>> account.account_id
'123456789012'
>>> account.curdef
'USD'
>>> 
```

This will then correspond to the following account mappings in your config file

```yaml
# config.yaml

# Required account mappings
accounts:
  mappings:
    # American Express Blue Cash Preferred card
    - institution: "AMEX"
      account_type: ""
      account_id: "123ABCD456EFGHI|12345"
      beancount_account: "Liabilities:Amex:BlueCashPreferred"
      currency: "USD"
    
    # BofA checking account
    - institution: "Bank of America"
      account_type: "CHECKING"
      account_id: "123456789012"
      beancount_account: "Assets:BofA:Checking"
      currency: "USD"

```

NOTE: You'll need to decide the value of `beancount_account` to whatever account name string you are using.

### 2. Create Accounts File

Create a Beancount file with your account definitions, if you don't have one already:

```beancount
; accounts.beancount
2020-01-01 open Assets:Chase:Checking USD
2020-01-01 open Liabilities:Amex:BlueCashPreferred USD
2020-01-01 open Expenses:Food:Groceries USD
2020-01-01 open Expenses:Transportation:Gas USD
2020-01-01 open Expenses:Entertainment USD
2020-01-01 open Expenses:Unknown USD
```

### 3. Run the Converter

```bash
python ofx_converter.py \
  -i statement.ofx \
  -c config.yaml \
  -a accounts.beancount \
  -l training.beancount \
  -o output.beancount
```

## Usage

### Command Line Options

```bash
python ofx_converter.py [OPTIONS]

Options:
  -i, --input-file PATH        OFX file to process [required if not in config file]
  -l, --learning-data-file PATH Beancount file for training data [optional, can be in config file]
  -o, --output-file PATH       Output Beancount file (appends if exists) [required, can be in config file]
  -a, --account-file PATH      Full Beancount file with open directives [optional, can be in config file]
  -c, --config-file PATH       YAML configuration file [required]
  -p, --port-num INTEGER       Port number for API server (default: 8000, can be in config file)
  -s, --server-only            Run only the API server (for GUI client use) [can be in config file]
  --help                       Show this message and exit
```

**Note:** All arguments except `-c/--config-file` can be specified in the configuration file. Command line arguments always take precedence over config file values.

### Training the ML Classifier

The ML Classifier learns from a file containing Beancount transactions, which is provided to the program via the `-l filename.beancount` option. This can just be your existing Beancount ledger with your past transactions.

## ML Categorization

### How It Works

The system trains on existing Beancount transactions. It extracts:
- Payee and narration as features
- Accounts in the transaction postings as labels
- Uses TF-IDF Vectorization and a Random Forest Classifier
- Predictions with a confidence of >= 90% are displayed in green color. Predictions with a confidence <= 20% are displayed in red color. The rest are shown in yellow-ish/orange color

## Duplicate Detection

If the output file you are writing (appending) to already has Beancount transactions, the program will try to detect if any new transactions in the OFX file closely match those existing transactions. Transactions are flagged as potential duplicates if they match:
- Date (exact match)
- Source account (exact match)
- Amount (exact match)
- Payee (>90% fuzzy similarity using rapidfuzz)

A transaction flagged as a duplicate can be skipped, which will prevent it from appearing in the output.

## API Mode

Run in server-only mode for integration with GUI applications (that may be built in the future to complement the current CLI client): For example

```bash
python ofx_converter.py -s -i file.ofx -c config.yaml -a accounts.beancount
```

The API will be available at (assuming default port number 8000, adjust according to your usage):
- **Base URL**: http://localhost:8000
- **Documentation**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health

## License

This project is licensed under the GPLv2 License.
