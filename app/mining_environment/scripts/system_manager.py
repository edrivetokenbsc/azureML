# system_manager.py

import os
import sys
import json
from pathlib import Path
from time import sleep
from typing import Dict, Any

from .resource_manager import ResourceManager
from .anomaly_detector import AnomalyDetector
from .logging_config import setup_logging

# Define configuration and logs directories
CONFIG_DIR = Path(os.getenv('CONFIG_DIR', '/app/mining_environment/config'))
LOGS_DIR = Path(os.getenv('LOGS_DIR', '/app/mining_environment/logs'))

# Set up loggers for each system component
system_logger = setup_logging('system_manager', LOGS_DIR / 'system_manager.log', 'INFO')
resource_logger = setup_logging('resource_manager', LOGS_DIR / 'resource_manager.log', 'INFO')
anomaly_logger = setup_logging('anomaly_detector', LOGS_DIR / 'anomaly_detector.log', 'INFO')

# Global instance of SystemManager
_system_manager_instance = None

class SystemManager:
    """
    System management class that combines ResourceManager and AnomalyDetector.
    Ensures components operate synchronously and without conflicts when accessing shared resources.
    """
    def __init__(self, config: Dict[str, Any]):
        self.config = config  # Store system configuration

        # Assign loggers to each component
        self.system_logger = system_logger
        self.resource_logger = resource_logger
        self.anomaly_logger = anomaly_logger

        # Initialize ResourceManager and AnomalyDetector with corresponding loggers
        self.resource_manager = ResourceManager(config, resource_logger)
        self.anomaly_detector = AnomalyDetector(config, anomaly_logger)

        # Assign ResourceManager to AnomalyDetector to ensure component linkage
        self.anomaly_detector.set_resource_manager(self.resource_manager)

        # Log successful initialization
        self.system_logger.info("SystemManager has been successfully initialized.")

    def start(self):
        """
        Start running system components.
        """
        self.system_logger.info("Starting SystemManager...")
        try:
            # Start ResourceManager and AnomalyDetector
            self.resource_manager.start()
            self.anomaly_detector.start()
            self.system_logger.info("SystemManager has started successfully.")
        except Exception as e:
            self.system_logger.error(f"Error starting SystemManager: {e}")
            self.stop()  # Ensure the entire system stops if an error occurs
            raise

    def stop(self):
        """
        Stop all system components.
        """
        self.system_logger.info("Stopping SystemManager...")
        try:
            # Stop ResourceManager and AnomalyDetector
            self.resource_manager.stop()
            self.anomaly_detector.stop()
            self.system_logger.info("SystemManager has stopped successfully.")
        except Exception as e:
            self.system_logger.error(f"Error stopping SystemManager: {e}")
            raise

def load_config(config_path: Path) -> Dict[str, Any]:
    """
    Load configuration from JSON file.

    Args:
        config_path (Path): Path to configuration file.

    Returns:
        Dict[str, Any]: Loaded configuration content.
    """
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        system_logger.info(f"Configuration loaded from {config_path}")
        return config
    except FileNotFoundError:
        system_logger.error(f"Configuration file not found: {config_path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        system_logger.error(f"JSON syntax error in configuration file {config_path}: {e}")
        sys.exit(1)

def start():
    """
    Start the entire system.
    """
    global _system_manager_instance

    # Load configuration from single JSON file
    resource_config_path = CONFIG_DIR / "resource_config.json"
    config = load_config(resource_config_path)

    # Initialize SystemManager with configuration
    _system_manager_instance = SystemManager(config)

    # Start running SystemManager
    try:
        _system_manager_instance.start()

        # Log system running status
        system_logger.info("SystemManager is running. Press Ctrl+C to stop.")

        # Run continuously until stop signal is received
        while True:
            sleep(1)
    except KeyboardInterrupt:
        system_logger.info("Received stop signal from user. Stopping SystemManager...")
        _system_manager_instance.stop()
    except Exception as e:
        system_logger.error(f"Unexpected error in SystemManager: {e}")
        _system_manager_instance.stop()
        sys.exit(1)

def stop():
    global _system_manager_instance

    if _system_manager_instance:
        system_logger.info("Stopping SystemManager...")
        _system_manager_instance.stop()
        system_logger.info("SystemManager has stopped successfully.")
    else:
        system_logger.warning("SystemManager instance has not been initialized.")

if __name__ == "__main__":
    # Ensure script runs with root privileges
    if os.geteuid() != 0:
        print("Script must be run with root privileges.")
        sys.exit(1)

    # Start the system
    start()
