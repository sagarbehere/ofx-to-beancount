#!/usr/bin/env python3
"""
OFX to Beancount Converter - Main Entry Point

This script serves as the main entry point for the OFX to Beancount converter.
It can run in interactive CLI mode or server-only mode for GUI clients.
"""
import warnings
warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")
import sys
from cli.main import main

if __name__ == "__main__":
    sys.exit(main())