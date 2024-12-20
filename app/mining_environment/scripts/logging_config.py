# logging_config.py

import logging
import os
import sys
from logging import Logger
from pathlib import Path
from cryptography.fernet import Fernet
import random
import string

class ObfuscatedEncryptedFileHandler(logging.Handler):
    """Custom logging handler to encrypt and obfuscate logs before writing to file."""
    def __init__(self, filename, fernet, level=logging.NOTSET):
        super().__init__(level)
        self.filename = filename
        self.fernet = fernet
        self.file = open(filename, 'ab')  # Write in binary mode

    def emit(self, record):
        try:
            msg = self.format(record)
            # Add random string for obfuscation
            random_suffix = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
            obfuscated_msg = f"{msg} {random_suffix}"
            # Encrypt the message
            encrypted_msg = self.fernet.encrypt(obfuscated_msg.encode('utf-8'))
            # Write to file
            self.file.write(encrypted_msg + b'\n')
            self.file.flush()
        except Exception:
            self.handleError(record)

    def close(self):
        self.file.close()
        super().close()

def setup_logging(module_name: str, log_file: str, log_level: str = 'INFO') -> Logger:

    logger = logging.getLogger(module_name)
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Check if running in test environment
    in_test = "TESTING" in os.environ
    if in_test:
        logger.propagate = True
        print("Logger propagate set to True for testing")
    else:
        # Ensure logger doesn't propagate logs to parent loggers if not testing
        logger.propagate = False
        print("Logger propagate set to False")

    if not logger.handlers:
        if in_test:
            print("Not adding StreamHandler for testing to allow caplog to capture logs")
            # Don't add StreamHandler in test environment
            return logger

        # Use ObfuscatedEncryptedFileHandler in production environment
        log_path = Path(log_file).parent
        log_path.mkdir(parents=True, exist_ok=True)

        # Get encryption key from environment variable or create new one
        encryption_key = os.getenv('LOG_ENCRYPTION_KEY')
        if not encryption_key:
            # Generate new key and save to environment variable
            encryption_key = Fernet.generate_key().decode()
            os.environ['LOG_ENCRYPTION_KEY'] = encryption_key
            print(f"Generated new encryption key: {encryption_key} (Save this for future use)")

        try:
            fernet = Fernet(encryption_key.encode())
        except Exception as e:
            print(f"Error creating Fernet object with encryption key: {e}", file=sys.stderr)
            return None

        # Create ObfuscatedEncryptedFileHandler
        encrypted_handler = ObfuscatedEncryptedFileHandler(log_file, fernet)
        encrypted_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        encrypted_handler.setFormatter(formatter)
        logger.addHandler(encrypted_handler)

        # Optional: Add StreamHandler for console output in non-test environment
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    return logger
