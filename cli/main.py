"""
Main CLI application for the OFX to Beancount converter.

This module provides the command-line interface and coordinates the entire
workflow including server management and user interaction.
"""

import os
import sys
import time
import signal
import subprocess
import threading
from pathlib import Path
from typing import Optional, Dict, Any
import yaml
import click

from cli.api_client import APIClient, APIClientError
from cli.interactive import (
    InteractiveProcessor, prompt_account_confirmation, 
    display_processing_summary, confirm_export
)


def display_system_messages(messages: list) -> None:
    """Display system messages from API response."""
    if not messages:
        return
        
    for msg in messages:
        level = msg.get('level', 'info')
        message = msg.get('message', '')
        
        if level == 'error':
            click.echo(f"❌ Error: {message}")
        elif level == 'warning':
            click.echo(f"⚠️  Warning: {message}")
        else:  # info
            click.echo(f"ℹ️  {message}")
    click.echo()  # Add spacing after messages


def handle_confirmation_workflow(api_client: APIClient, response_data: dict) -> bool:
    """
    Handle confirmation workflow for degraded functionality scenarios.
    
    Returns True if user chose to continue, False if user chose to abort.
    """
    if not response_data.get('requires_confirmation', False):
        return True  # No confirmation needed
    
    confirmation_details = response_data.get('confirmation_details', {})
    confirmation_message = confirmation_details.get('confirmation_message', '')
    confirmation_type = confirmation_details.get('confirmation_type', '')
    session_id = response_data.get('session_id', '')
    
    # Display system messages first
    system_messages = confirmation_details.get('system_messages', [])
    display_system_messages(system_messages)
    
    # Show confirmation prompt
    click.echo(f"\n{confirmation_message}")
    click.echo("\nChoices:")
    click.echo("  y - Continue with degraded functionality") 
    click.echo("  n - Abort and exit program")
    
    while True:
        try:
            choice = click.prompt("\nYour choice", type=click.Choice(['y', 'n'], case_sensitive=False))
            if choice.lower() == 'y':
                user_choice = "continue"
                break
            elif choice.lower() == 'n':
                user_choice = "abort"
                break
        except click.Abort:
            click.echo("\nOperation cancelled by user.")
            return False
    
    # Send confirmation response to server
    try:
        confirm_response = api_client.confirm_degraded_functionality(
            session_id, confirmation_type, user_choice
        )
        
        # Display any system messages from confirmation
        display_system_messages(confirm_response.get('system_messages', []))
        
        return confirm_response.get('processing_continues', False)
        
    except Exception as e:
        click.echo(f"❌ Error processing confirmation: {e}")
        return False


class ServerManager:
    """Manages the API server lifecycle for CLI operations."""
    
    def __init__(self, host: str = "127.0.0.1", port: int = 8000):
        self.host = host
        self.port = port
        self.process: Optional[subprocess.Popen] = None
        self.api_client = APIClient(f"http://{host}:{port}")
    
    def start_server(self) -> bool:
        """
        Start the API server and wait for it to be ready.
        
        Returns:
            True if server started successfully, False otherwise
        """
        print(f"Starting API server on {self.host}:{self.port}...")
        
        # Start server process
        try:
            # Get the path to the API main module
            api_main_path = Path(__file__).parent.parent / "api" / "main.py"
            
            self.process = subprocess.Popen([
                sys.executable, "-m", "uvicorn", 
                "api.main:app",
                "--host", self.host,
                "--port", str(self.port),
                "--log-level", "warning"
            ], 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            cwd=Path(__file__).parent.parent
            )
            
            # Wait for server to be ready
            print("Waiting for server to start...", end="", flush=True)
            
            if self.api_client.wait_for_server(max_attempts=30, delay=1.0):
                print(" Server ready!")
                return True
            else:
                print(" ❌ Server failed to start!")
                self.stop_server()
                return False
                
        except Exception as e:
            print(f"❌ Failed to start server: {e}")
            return False
    
    def stop_server(self) -> None:
        """Stop the API server."""
        if self.process:
            print("Stopping API server...")
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.process = None
    
    def is_server_running(self) -> bool:
        """Check if the server is running and responsive."""
        try:
            self.api_client.get_health_status()
            return True
        except APIClientError:
            return False


class OFXConverter:
    """Main application class for OFX to Beancount conversion."""
    
    def __init__(self):
        self.server_manager: Optional[ServerManager] = None
        self.api_client: Optional[APIClient] = None
        self.session_id: Optional[str] = None
    
    def run_interactive_mode(self, input_file: str, config_file: str,
                           learning_data: Optional[str] = None,
                           account_file: Optional[str] = None,
                           output_file: Optional[str] = None,
                           port: int = 8000) -> int:
        """
        Run the interactive CLI workflow.
        
        Returns:
            Exit code (0 for success, non-zero for error)
        """
        try:
            # Start API server
            self.server_manager = ServerManager(port=port)
            if not self.server_manager.start_server():
                click.echo("❌ Failed to start API server", err=True)
                return 1
            
            self.api_client = self.server_manager.api_client
            
            # Initialize session
            session_data = self._initialize_session(
                input_file, config_file, learning_data, account_file, output_file
            )
            if not session_data:
                return 1
            
            self.session_id = session_data['session_id']
            
            # Display OFX statistics
            self._display_ofx_stats(session_data['ofx_stats'])
            
            # Confirm account mapping
            confirmed_account, confirmed_currency = self._confirm_account_mapping(
                session_data['detected_account'],
                session_data['valid_accounts']
            )
            
            # Categorize transactions
            categorized_data = self._categorize_transactions(confirmed_account, confirmed_currency)
            if not categorized_data:
                return 1
            
            # Interactive review
            updates = self._interactive_review(categorized_data['transactions'], session_data['valid_accounts'])
            
            # Apply updates
            if updates:
                self._apply_transaction_updates(updates)
            
            # Display summary
            click.echo()  # Empty line before summary
            self._display_session_summary()
            
            # Export results
            if output_file and self._confirm_export():
                click.echo()  # Empty line before export
                self._export_results(output_file)
            
            click.echo("\nProcessing completed successfully!")
            return 0
            
        except KeyboardInterrupt:
            click.echo("\n⚠️ Processing interrupted by user", err=True)
            return 130
        except Exception as e:
            click.echo(f"❌ Error during processing: {e}", err=True)
            return 1
        finally:
            if self.server_manager:
                self.server_manager.stop_server()
    
    def run_server_only_mode(self, port: int = 8000) -> int:
        """
        Run in server-only mode for GUI clients.
        
        Returns:
            Exit code (0 for success, non-zero for error)
        """
        try:
            self.server_manager = ServerManager(port=port)
            
            if not self.server_manager.start_server():
                click.echo("❌ Failed to start API server", err=True)
                return 1
            
            click.echo(f"🌐 API server running at http://127.0.0.1:{port}")
            click.echo("📖 API documentation: http://127.0.0.1:{port}/docs")
            click.echo("🏥 Health check: http://127.0.0.1:{port}/health")
            click.echo("\nPress Ctrl+C to stop the server...")
            
            # Wait for interrupt
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                click.echo("\n🛑 Shutting down server...")
                return 0
                
        except Exception as e:
            click.echo(f"❌ Server error: {e}", err=True)
            return 1
        finally:
            if self.server_manager:
                self.server_manager.stop_server()
    
    def _initialize_session(self, input_file: str, config_file: str,
                          learning_data: Optional[str], account_file: Optional[str],
                          output_file: Optional[str]) -> Optional[Dict[str, Any]]:
        """Initialize processing session with confirmation workflow."""
        try:
            click.echo("🔄 Initializing session...")
            
            response = self.api_client.initialize_session(
                ofx_file_path=input_file,
                config_file_path=config_file,
                training_file_path=learning_data,
                account_file_path=account_file,
                output_file_path=output_file
            )
            
            # Display system messages
            display_system_messages(response.get('system_messages', []))
            
            # Handle confirmation workflow
            if not handle_confirmation_workflow(self.api_client, response):
                click.echo("Conversion cancelled.")
                return None
                
            # If we needed confirmation, get the updated session state
            if response.get('requires_confirmation', False):
                # The confirmation handler already processed the confirmation
                # Continue with normal workflow using the session_id
                pass
            
            click.echo("✅ Session initialized successfully")
            
            if response.get('classifier_trained'):
                click.echo(f"🤖 ML classifier trained on {response.get('training_data_count', 0)} transactions")
            else:
                click.echo("⚠️ ML classifier not trained - manual categorization required")
            
            return response
            
        except APIClientError as e:
            click.echo(f"❌ Session initialization failed: {e}", err=True)
            return None
    
    def _display_ofx_stats(self, ofx_stats: Dict[str, Any]) -> None:
        """Display OFX file statistics."""
        stats = ofx_stats
        click.echo(f"\n📊 OFX File Statistics")
        click.echo("─" * 40)
        click.echo(f"📈 Transactions: {stats['transaction_count']}")
        click.echo(f"📅 Date range: {stats['date_range']['start']} to {stats['date_range']['end']}")
        click.echo(f"💰 Balance: ${stats['balance']:,.2f} {stats['currency']}")
        click.echo(f"💱 Currency: {stats['currency']}")
    
    def _confirm_account_mapping(self, detected_account: Dict[str, Any],
                               valid_accounts: list) -> tuple:
        """Confirm or correct account mapping."""
        return prompt_account_confirmation(
            detected_account['account'],
            detected_account['currency'], 
            detected_account['confidence'],
            valid_accounts
        )
    
    def _categorize_transactions(self, confirmed_account: str, confirmed_currency: str) -> Optional[Dict[str, Any]]:
        """Categorize transactions using ML."""
        try:
            click.echo("Categorizing transactions...")
            
            response = self.api_client.categorize_transactions(
                session_id=self.session_id,
                confirmed_account=confirmed_account,
                confirmed_currency=confirmed_currency
            )
            
            # Display system messages from categorization
            display_system_messages(response.get('system_messages', []))
            
            total = response['total_count']
            high_conf = response['high_confidence_count']
            duplicates = response['duplicate_count']
            
            
            click.echo(f"Categorized {total} transactions")
            if total > 0:
                if duplicates > 0:
                    click.echo(f"⚠️ Potential duplicates: {duplicates}")
            else:
                click.echo("❌ No transactions found in OFX file!")
                click.echo("This could be due to:")
                click.echo("  • OFX file format not supported")
                click.echo("  • Empty or corrupted OFX file") 
                click.echo("  • Non-banking transactions (investments, etc.)")
                return None
            
            return response
            
        except APIClientError as e:
            click.echo(f"❌ Categorization failed: {e}", err=True)
            return None
    
    def _interactive_review(self, transactions: list, valid_accounts: list) -> list:
        """Run interactive transaction review."""
        processor = InteractiveProcessor(valid_accounts)
        return processor.review_transactions_interactively(transactions)
    
    def _apply_transaction_updates(self, updates: list) -> None:
        """Apply transaction updates from interactive review."""
        if not updates:
            click.echo("No transaction updates to apply")
            return
        
        try:
            response = self.api_client.update_transactions_batch(
                session_id=self.session_id,
                updates=updates
            )
            
            # Display system messages from updates
            display_system_messages(response.get('system_messages', []))
            
            updated = response['updated_count']
            skipped = response['skipped_count']
            split = response['split_count']
            errors = response.get('validation_errors', [])
            
            if errors:
                click.echo(f"⚠️ Validation errors: {len(errors)}")
                for error in errors[:5]:  # Show first 5 errors
                    click.echo(f"  • {error.get('error', 'Unknown error')}")
            
        except APIClientError as e:
            click.echo(f"❌ Failed to apply updates: {e}", err=True)
    
    def _display_session_summary(self) -> None:
        """Display session processing summary."""
        try:
            summary = self.api_client.get_transaction_summary(self.session_id)
            display_processing_summary(summary)
        except APIClientError as e:
            click.echo(f"⚠️ Could not get session summary: {e}")
    
    def _confirm_export(self) -> bool:
        """Confirm export operation."""
        try:
            preview = self.api_client.preview_export(self.session_id, max_transactions=3)
            return confirm_export(preview['preview'], preview['total_transactions'])
        except APIClientError as e:
            click.echo(f"⚠️ Could not get export preview: {e}")
            return click.confirm("Proceed with export?")
    
    def _export_results(self, output_file: str) -> None:
        """Export results to Beancount file."""
        try:
            click.echo(f"Exporting to {output_file}...")
            
            response = self.api_client.export_beancount(
                session_id=self.session_id,
                output_file_path=output_file,
                output_mode="append"
            )
            
            # Display system messages from export
            display_system_messages(response.get('system_messages', []))
            
            exported = response['transactions_exported']
            click.echo(f"Exported {exported} transactions")
            
        except APIClientError as e:
            click.echo(f"❌ Export failed: {e}", err=True)


@click.command()
@click.option('-i', '--input-file', required=True, type=click.Path(exists=True),
              help='OFX file to process')
@click.option('-l', '--learning-data', type=click.Path(exists=True),
              help='Beancount file for training data')
@click.option('-o', '--output-file', type=click.Path(),
              help='Output Beancount file (appends if exists)')
@click.option('-a', '--account-file', type=click.Path(exists=True),
              help='Full Beancount file with open directives for account validation')
@click.option('-c', '--config-file', required=True, type=click.Path(exists=True),
              help='YAML configuration file')
@click.option('-p', '--port-num', default=8000, type=int,
              help='Port number for API server (default: 8000)')
@click.option('-s', '--server-only', is_flag=True,
              help='Run only the API server (for GUI client use)')
def main(input_file: str, learning_data: Optional[str], output_file: Optional[str],
         account_file: Optional[str], config_file: str, port_num: int, server_only: bool) -> None:
    """
    OFX to Beancount Converter
    
    Convert OFX files to Beancount format with intelligent ML-based categorization.
    """
    
    converter = OFXConverter()
    
    if server_only:
        # Validate required files even in server-only mode
        required_files = {
            'OFX file': input_file,
            'config file': config_file
        }
        
        if learning_data:
            required_files['learning data'] = learning_data
        if account_file:
            required_files['account file'] = account_file
        
        # Check file accessibility
        for name, path in required_files.items():
            if path and not os.path.exists(path):
                click.echo(f"❌ {name} not found: {path}", err=True)
                sys.exit(1)
        
        click.echo("✅ All required files validated")
        exit_code = converter.run_server_only_mode(port_num)
    else:
        exit_code = converter.run_interactive_mode(
            input_file, config_file, learning_data, 
            account_file, output_file, port_num
        )
    
    sys.exit(exit_code)


if __name__ == "__main__":
    main()