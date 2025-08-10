"""
Centralized file validation utilities for robust error handling.

This module provides comprehensive file validation with specific error types
and graceful degradation scenarios as specified in the project requirements.
"""

import os
from typing import List, Optional, Tuple
from enum import Enum
from dataclasses import dataclass


class FileErrorType(Enum):
    """Types of file operation errors."""
    FILE_NOT_FOUND = "file_not_found"
    PERMISSION_DENIED = "permission_denied" 
    IS_DIRECTORY = "is_directory"
    SYSTEM_ERROR = "system_error"
    ENCODING_ERROR = "encoding_error"
    EMPTY_FILE = "empty_file"
    INVALID_FORMAT = "invalid_format"


@dataclass
class FileValidationError:
    """Represents a file validation error."""
    error_type: FileErrorType
    file_path: str
    message: str
    details: Optional[str] = None


class FileValidator:
    """Comprehensive file validation with specific error handling."""
    
    @staticmethod
    def validate_input_file(file_path: str, min_size: int = 1) -> List[FileValidationError]:
        """Validate input file (OFX) - must exist and be readable."""
        errors = []
        
        if not file_path:
            errors.append(FileValidationError(
                FileErrorType.FILE_NOT_FOUND,
                file_path or "",
                "Input file path not specified"
            ))
            return errors
        
        # Check existence
        if not os.path.exists(file_path):
            errors.append(FileValidationError(
                FileErrorType.FILE_NOT_FOUND,
                file_path,
                f"Input file not found: {file_path}"
            ))
            return errors
            
        # Check if it's a file (not directory)
        if not os.path.isfile(file_path):
            errors.append(FileValidationError(
                FileErrorType.IS_DIRECTORY,
                file_path,
                f"Path is a directory, not a file: {file_path}"
            ))
            return errors
            
        # Check readability
        if not os.access(file_path, os.R_OK):
            errors.append(FileValidationError(
                FileErrorType.PERMISSION_DENIED,
                file_path,
                f"Input file is not readable: {file_path}"
            ))
            return errors
            
        # Check file size
        try:
            file_size = os.path.getsize(file_path)
            if file_size < min_size:
                errors.append(FileValidationError(
                    FileErrorType.EMPTY_FILE,
                    file_path,
                    f"Input file is empty or too small ({file_size} bytes): {file_path}"
                ))
        except OSError as e:
            errors.append(FileValidationError(
                FileErrorType.SYSTEM_ERROR,
                file_path,
                f"Cannot access file size: {e}",
                str(e)
            ))
            
        return errors
    
    @staticmethod
    def validate_optional_file(file_path: Optional[str]) -> List[FileValidationError]:
        """Validate optional files (training, accounts) - may be missing."""
        if not file_path:
            return []  # Optional file not specified is OK
            
        return FileValidator.validate_input_file(file_path)
    
    @staticmethod
    def validate_output_file(file_path: Optional[str]) -> List[FileValidationError]:
        """Validate output file - must be writable if specified."""
        errors = []
        
        if not file_path:
            errors.append(FileValidationError(
                FileErrorType.FILE_NOT_FOUND,
                "",
                "Output file path not specified"
            ))
            return errors
            
        # If file exists, check if writable
        if os.path.exists(file_path):
            if not os.path.isfile(file_path):
                errors.append(FileValidationError(
                    FileErrorType.IS_DIRECTORY,
                    file_path,
                    f"Output path is a directory, not a file: {file_path}"
                ))
                return errors
                
            if not os.access(file_path, os.W_OK):
                errors.append(FileValidationError(
                    FileErrorType.PERMISSION_DENIED,
                    file_path,
                    f"Output file is not writable: {file_path}"
                ))
                return errors
        else:
            # File doesn't exist - check if directory is writable
            parent_dir = os.path.dirname(file_path) or '.'
            if not os.path.exists(parent_dir):
                errors.append(FileValidationError(
                    FileErrorType.FILE_NOT_FOUND,
                    file_path,
                    f"Output directory does not exist: {parent_dir}"
                ))
            elif not os.access(parent_dir, os.W_OK):
                errors.append(FileValidationError(
                    FileErrorType.PERMISSION_DENIED,
                    file_path,
                    f"Output directory is not writable: {parent_dir}"
                ))
                
        return errors
    
    @staticmethod
    def safe_file_read(file_path: str, encoding: str = 'utf-8') -> Tuple[Optional[str], List[FileValidationError]]:
        """Safely read file content with comprehensive error handling."""
        errors = FileValidator.validate_input_file(file_path)
        if errors:
            return None, errors
            
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                return f.read(), []
        except PermissionError:
            return None, [FileValidationError(
                FileErrorType.PERMISSION_DENIED,
                file_path,
                f"Permission denied reading file: {file_path}"
            )]
        except UnicodeDecodeError as e:
            return None, [FileValidationError(
                FileErrorType.ENCODING_ERROR,
                file_path,
                f"File encoding error in {file_path}: {e}",
                str(e)
            )]
        except OSError as e:
            return None, [FileValidationError(
                FileErrorType.SYSTEM_ERROR,
                file_path,
                f"System error reading {file_path}: {e}",
                str(e)
            )]
    
    @staticmethod
    def safe_file_write(file_path: str, content: str, encoding: str = 'utf-8', create_dirs: bool = True) -> List[FileValidationError]:
        """Safely write file content with comprehensive error handling."""
        errors = FileValidator.validate_output_file(file_path)
        if errors:
            return errors
            
        # Create parent directories if requested and needed
        if create_dirs:
            parent_dir = os.path.dirname(file_path)
            if parent_dir and not os.path.exists(parent_dir):
                try:
                    os.makedirs(parent_dir, exist_ok=True)
                except OSError as e:
                    return [FileValidationError(
                        FileErrorType.SYSTEM_ERROR,
                        file_path,
                        f"Cannot create directory {parent_dir}: {e}",
                        str(e)
                    )]
        
        try:
            with open(file_path, 'w', encoding=encoding) as f:
                f.write(content)
            return []
        except PermissionError:
            return [FileValidationError(
                FileErrorType.PERMISSION_DENIED,
                file_path,
                f"Permission denied writing to file: {file_path}"
            )]
        except OSError as e:
            return [FileValidationError(
                FileErrorType.SYSTEM_ERROR,
                file_path,
                f"System error writing to {file_path}: {e}",
                str(e)
            )]