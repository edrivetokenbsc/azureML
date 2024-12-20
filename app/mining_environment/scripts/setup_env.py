# setup_env.py

import os
import sys
import json
import subprocess
import locale
import psutil  # Added psutil for resource monitoring
from pathlib import Path

# Import common logging configuration
from .logging_config import setup_logging

def load_json_config(config_path, logger):
    """
    Read the JSON configuration file and return a Python object.

    Args:
        config_path (str): Path to the JSON file.
        logger (Logger): Logger object for logging.

    Returns:
        dict: Contents of the JSON file as a dictionary.
    """
    try:
        with open(config_path, 'r') as file:
            config = json.load(file)
        logger.info(f"Loaded configuration from {config_path}")
        return config
    except FileNotFoundError:
        logger.error(f"Configuration file does not exist: {config_path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.error(f"JSON syntax error in file {config_path}: {e}")
        sys.exit(1)

def configure_system(system_params, logger):
    """
    Set system parameters such as timezone and locale.

    Args:
        system_params (dict): System configuration parameters.
        logger (Logger): Logger object for logging.
    """
    try:
        # Set timezone
        timezone = system_params.get('timezone', 'UTC')
        os.environ['TZ'] = timezone
        subprocess.run(['ln', '-snf', f'/usr/share/zoneinfo/{timezone}', '/etc/localtime'], check=True)
        subprocess.run(['dpkg-reconfigure', '-f', 'noninteractive', 'tzdata'], check=True)
        logger.info(f"System timezone set to: {timezone}")

        # Set locale
        locale_setting = system_params.get('locale', 'en_US.UTF-8')
        try:
            locale.setlocale(locale.LC_ALL, locale_setting)
            logger.info(f"System locale set to: {locale_setting}")
        except locale.Error:
            logger.warning(f"Locale {locale_setting} not generated. Generating locale...")
            subprocess.run(['locale-gen', locale_setting], check=True)
            locale.setlocale(locale.LC_ALL, locale_setting)
            logger.info(f"System locale set to: {locale_setting}")

        subprocess.run(['update-locale', f'LANG={locale_setting}'], check=True)
        logger.info(f"System locale updated to: {locale_setting}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Error configuring system: {e}")
        sys.exit(1)
    except locale.Error as e:
        logger.error(f"Error setting locale: {e}")
        sys.exit(1)

def setup_environment_variables(environmental_limits, logger):
    """
    Set environment variables based on environmental limits.

    Args:
        environmental_limits (dict): Environmental limits from the configuration file.
        logger (Logger): Logger object for logging.
    """
    try:
        # Handle memory_limits
        memory_limits = environmental_limits.get('memory_limits', {})
        ram_percent_threshold = memory_limits.get('ram_percent_threshold')
        if ram_percent_threshold is not None:
            os.environ['RAM_PERCENT_THRESHOLD'] = str(ram_percent_threshold)
            logger.info(f"Set environment variable RAM_PERCENT_THRESHOLD: {ram_percent_threshold}%")
        else:
            # Remove environment variable if not present in config
            if 'RAM_PERCENT_THRESHOLD' in os.environ:
                del os.environ['RAM_PERCENT_THRESHOLD']
                logger.info("Removed environment variable RAM_PERCENT_THRESHOLD as it is not in the configuration.")
            logger.warning("`ram_percent_threshold` not found in `memory_limits`.")

        # Handle gpu_optimization
        gpu_optimization = environmental_limits.get('gpu_optimization', {})
        gpu_util_min = gpu_optimization.get('gpu_utilization_percent_optimal', {}).get('min')
        gpu_util_max = gpu_optimization.get('gpu_utilization_percent_optimal', {}).get('max')
        if gpu_util_min is not None and gpu_util_max is not None:
            os.environ['GPU_UTIL_MIN'] = str(gpu_util_min)
            os.environ['GPU_UTIL_MAX'] = str(gpu_util_max)
            logger.info(f"Set environment variables GPU_UTIL_MIN: {gpu_util_min}%, GPU_UTIL_MAX: {gpu_util_max}%")
        else:
            # Optionally remove GPU environment variables if not needed
            if 'GPU_UTIL_MIN' in os.environ:
                del os.environ['GPU_UTIL_MIN']
                logger.info("Removed environment variable GPU_UTIL_MIN as it is not in the configuration.")
            if 'GPU_UTIL_MAX' in os.environ:
                del os.environ['GPU_UTIL_MAX']
                logger.info("Removed environment variable GPU_UTIL_MAX as it is not in the configuration.")
            logger.warning("`gpu_utilization_percent_optimal.min` or `max` not found in `gpu_optimization`.")
    except Exception as e:
        logger.error(f"Error setting environment variables: {e}")
        sys.exit(1)

def configure_security(logger):
    """
    Start stunnel using the stunnel.conf copied into the container.

    Args:
        logger (Logger): Logger object for logging.
    """
    try:
        stunnel_conf_path = '/etc/stunnel/stunnel.conf'
        if not os.path.exists(stunnel_conf_path):
            logger.error(f"Stunnel configuration file does not exist at: {stunnel_conf_path}")
            sys.exit(1)

        # Check if stunnel is already running
        result = subprocess.run(['pgrep', '-f', 'stunnel'], stdout=subprocess.PIPE)
        if result.returncode != 0:
            # Start stunnel with the pre-configured configuration file
            subprocess.Popen(['stunnel', stunnel_conf_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
            logger.info("Stunnel started successfully.")
        else:
            logger.info("Stunnel is already running.")
    except subprocess.CalledProcessError as e:
        logger.error(f"Error checking or starting stunnel: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error when starting stunnel: {e}")
        sys.exit(1)

def validate_configs(resource_config, system_params, environmental_limits, logger):
    """
    Validate the configuration files.

    Args:
        resource_config (dict): Resource configuration.
        system_params (dict): System parameters.
        environmental_limits (dict): Environmental limits.
        logger (Logger): Logger object for logging.
    """
    try:
        # 1. Check RAM
        ram_allocation = resource_config.get('resource_allocation', {}).get('ram', {})
        ram_max_mb = ram_allocation.get('max_allocation_mb')
        if ram_max_mb is None:
            logger.error("Missing `max_allocation_mb` in `resource_allocation.ram`.")
            sys.exit(1)
        if not (1024 <= ram_max_mb <= 200000):
            logger.error("Invalid `ram_max_allocation_mb` value. Must be between 1024 MB and 131072 MB.")
            sys.exit(1)
        else:
            logger.info(f"RAM limit: {ram_max_mb} MB")

        # 2. Check CPU Percent Threshold
        baseline_monitoring = environmental_limits.get('baseline_monitoring', {})
        cpu_percent_threshold = baseline_monitoring.get('cpu_percent_threshold')
        if cpu_percent_threshold is None:
            logger.error("Missing `cpu_percent_threshold` in `environmental_limits.baseline_monitoring`.")
            sys.exit(1)
        if not (1 <= cpu_percent_threshold <= 100):
            logger.error("Invalid `cpu_percent_threshold` value. Must be between 1% and 100%.")
            sys.exit(1)
        else:
            logger.info(f"CPU percent threshold limit: {cpu_percent_threshold}%")

        # 3. Check CPU Max Threads
        cpu_allocation = resource_config.get('resource_allocation', {}).get('cpu', {})
        cpu_max_threads = cpu_allocation.get('max_threads')
        if cpu_max_threads is None:
            logger.error("Missing `max_threads` in `resource_allocation.cpu`.")
            sys.exit(1)
        if not (1 <= cpu_max_threads <= 64):
            logger.error("Invalid `cpu_max_threads` value. Must be between 1 and 64.")
            sys.exit(1)
        else:
            logger.info(f"CPU threads limit: {cpu_max_threads}")

        # 4. Check GPU Percent Threshold
        gpu_percent_threshold = baseline_monitoring.get('gpu_percent_threshold')
        if gpu_percent_threshold is None:
            logger.error("Missing `gpu_percent_threshold` in `environmental_limits.baseline_monitoring`.")
            sys.exit(1)
        if not (1 <= gpu_percent_threshold <= 100):
            logger.error("Invalid `gpu_percent_threshold` value. Must be between 1% and 100%.")
            sys.exit(1)
        else:
            logger.info(f"GPU percent threshold limit: {gpu_percent_threshold}%")

        # 5. Check GPU Usage Percent Max
        gpu_usage_max_percent = resource_config.get('resource_allocation', {}).get('gpu', {}).get('usage_percent_range', {}).get('max')
        if gpu_usage_max_percent is None:
            logger.error("Missing `resource_allocation.gpu.usage_percent_range.max` in `resource_allocation.gpu`.")
            sys.exit(1)
        if not (1 <= gpu_usage_max_percent <= 100):
            logger.error("Invalid `gpu_usage_percent_range.max` value. Must be between 1% and 100%.")
            sys.exit(1)
        else:
            logger.info(f"GPU usage percent limit: {gpu_usage_max_percent}%")

        # 6. Check Cache Percent Threshold
        cache_percent_threshold = baseline_monitoring.get('cache_percent_threshold')
        if cache_percent_threshold is None:
            logger.error("Missing `cache_percent_threshold` in `environmental_limits.baseline_monitoring`.")
            sys.exit(1)
        if not (10 <= cache_percent_threshold <= 100):
            logger.error("Invalid `cache_percent_threshold` value. Must be between 10% and 100%.")
            sys.exit(1)
        else:
            logger.info(f"Cache percent threshold limit: {cache_percent_threshold}%")

        # 7. Check Network Bandwidth Threshold
        network_bandwidth_threshold = baseline_monitoring.get('network_bandwidth_threshold_mbps')
        if network_bandwidth_threshold is None:
            logger.error("Missing `network_bandwidth_threshold_mbps` in `environmental_limits.baseline_monitoring`.")
            sys.exit(1)
        if not (1 <= network_bandwidth_threshold <= 10000):
            logger.error("Invalid `network_bandwidth_threshold_mbps` value. Must be between 1 Mbps and 10000 Mbps.")
            sys.exit(1)
        else:
            logger.info(f"Network bandwidth threshold limit: {network_bandwidth_threshold} Mbps")

        # 8. Check Disk I/O Threshold
        disk_io_threshold_mbps = baseline_monitoring.get('disk_io_threshold_mbps')
        if disk_io_threshold_mbps is None:
            logger.error("Missing `disk_io_threshold_mbps` in `environmental_limits.baseline_monitoring`.")
            sys.exit(1)
        if not (1 <= disk_io_threshold_mbps <= 10000):
            logger.error("Invalid `disk_io_threshold_mbps` value. Must be between 1 Mbps and 10000 Mbps.")
            sys.exit(1)
        else:
            logger.info(f"Disk I/O threshold limit: {disk_io_threshold_mbps} Mbps")

        # 9. Check Power Consumption Threshold
        power_consumption_threshold = baseline_monitoring.get('power_consumption_threshold_watts')
        if power_consumption_threshold is None:
            logger.error("Missing `power_consumption_threshold_watts` in `environmental_limits.baseline_monitoring`.")
            sys.exit(1)
        if not (50 <= power_consumption_threshold <= 10000):
            logger.error("Invalid `power_consumption_threshold_watts` value. Must be between 50 W and 10000 W.")
            sys.exit(1)
        else:
            logger.info(f"Power consumption limit: {power_consumption_threshold} W")

        # 10. Check CPU Temperature
        cpu_temperature = environmental_limits.get('temperature_limits', {}).get('cpu', {})
        cpu_max_celsius = cpu_temperature.get('max_celsius')
        if cpu_max_celsius is None:
            logger.error("Missing `temperature_limits.cpu.max_celsius` in `environmental_limits.temperature_limits`.")
            sys.exit(1)
        if not (50 <= cpu_max_celsius <= 100):
            logger.error("Invalid `temperature_limits.cpu.max_celsius` value. Must be between 50°C and 100°C.")
            sys.exit(1)
        else:
            logger.info(f"CPU temperature limit: {cpu_max_celsius}°C")

        # 11. Check GPU Temperature
        gpu_temperature = environmental_limits.get('temperature_limits', {}).get('gpu', {})
        gpu_max_celsius = gpu_temperature.get('max_celsius')
        if gpu_max_celsius is None:
            logger.error("Missing `temperature_limits.gpu.max_celsius` in `environmental_limits.temperature_limits`.")
            sys.exit(1)
        if not (40 <= gpu_max_celsius <= 100):
            logger.error("Invalid `temperature_limits.gpu.max_celsius` value. Must be between 40°C and 100°C.")
            sys.exit(1)
        else:
            logger.info(f"GPU temperature limit: {gpu_max_celsius}°C")

        # 12. Check Power Consumption
        power_limits = environmental_limits.get('power_limits', {})
        total_power_max = power_limits.get('total_power_watts', {}).get('max')
        if total_power_max is None:
            logger.error("Missing `power_limits.total_power_watts.max` in `environmental_limits.power_limits.total_power_watts`.")
            sys.exit(1)
        if not (100 <= total_power_max <= 300):
            logger.error("Invalid `power_limits.total_power_watts.max` value. Must be between 100 W and 300 W.")
            sys.exit(1)
        else:
            logger.info(f"Total power consumption limit: {total_power_max} W")

        per_device_power_watts = power_limits.get('per_device_power_watts', {})
        per_device_power_cpu_max = per_device_power_watts.get('cpu', {}).get('max')
        if per_device_power_cpu_max is None:
            logger.error("Missing `power_limits.per_device_power_watts.cpu.max` in `environmental_limits.power_limits.per_device_power_watts.cpu`.")
            sys.exit(1)
        if not (50 <= per_device_power_cpu_max <= 150):
            logger.error("Invalid `power_limits.per_device_power_watts.cpu.max` value. Must be between 50 W and 150 W.")
            sys.exit(1)
        else:
            logger.info(f"CPU power consumption limit: {per_device_power_cpu_max} W")

        per_device_power_gpu_max = per_device_power_watts.get('gpu', {}).get('max')
        if per_device_power_gpu_max is None:
            logger.error("Missing `power_limits.per_device_power_watts.gpu.max` in `environmental_limits.power_limits.per_device_power_watts.gpu`.")
            sys.exit(1)
        if not (50 <= per_device_power_gpu_max <= 150):
            logger.error("Invalid `power_limits.per_device_power_watts.gpu.max` value. Must be between 50 W and 150 W.")
            sys.exit(1)
        else:
            logger.info(f"GPU power consumption limit: {per_device_power_gpu_max} W")

        # 13. Check Memory Limits
        memory_limits = environmental_limits.get('memory_limits', {})
        ram_percent_threshold = memory_limits.get('ram_percent_threshold')
        if ram_percent_threshold is None:
            logger.error("Missing `ram_percent_threshold` in `environmental_limits.memory_limits`.")
            sys.exit(1)
        if not (50 <= ram_percent_threshold <= 100):
            logger.error("Invalid `ram_percent_threshold` value. Must be between 50% and 100%.")
            sys.exit(1)
        else:
            logger.info(f"RAM percent threshold limit: {ram_percent_threshold}%")

        # 14. Check GPU Optimization
        gpu_optimization = environmental_limits.get('gpu_optimization', {})
        gpu_util_min = gpu_optimization.get('gpu_utilization_percent_optimal', {}).get('min')
        gpu_util_max = gpu_optimization.get('gpu_utilization_percent_optimal', {}).get('max')
        if gpu_util_min is None or gpu_util_max is None:
            logger.error("Missing `gpu_utilization_percent_optimal.min` or `gpu_utilization_percent_optimal.max` in `environmental_limits.gpu_optimization`.")
            sys.exit(1)
        if not (0 <= gpu_util_min < gpu_util_max <= 100):
            logger.error("Invalid `gpu_utilization_percent_optimal.min` and `gpu_utilization_percent_optimal.max` values. Must be 0 <= min < max <= 100.")
            sys.exit(1)
        else:
            logger.info(f"GPU optimization utilization limits: min={gpu_util_min}%, max={gpu_util_max}%")

        logger.info("Configuration files have been fully validated.")
    except Exception as e:
        logger.error(f"Error during configuration validation: {e}")
        sys.exit(1)

def setup_gpu_optimization(environmental_limits, logger):
    """
    Set up GPU optimization based on utilization thresholds.

    Args:
        environmental_limits (dict): Environmental limits from the configuration file.
        logger (Logger): Logger object for logging.
    """
    # Placeholder for GPU optimization setup steps.
    # In practice, you need to integrate with other tools or scripts to adjust GPU.
    logger.info("Setting up GPU optimization based on configured thresholds.")
    # Implement additional necessary steps here if any

def setup():
    """
    Main function to set up the mining environment.
    """
    # Define paths to log directories and files
    CONFIG_DIR = os.getenv('CONFIG_DIR', '/app/mining_environment/config')
    LOGS_DIR = os.getenv('LOGS_DIR', '/app/mining_environment/logs')
    os.makedirs(LOGS_DIR, exist_ok=True)

    # Set up logging with logging_config.py
    logger = setup_logging('setup_env', Path(LOGS_DIR) / 'setup_env.log', 'INFO')

    logger.info("Starting cryptocurrency mining environment setup.")

    # Define paths to configuration files
    system_params_path = os.path.join(CONFIG_DIR, 'system_params.json')
    environmental_limits_path = os.path.join(CONFIG_DIR, 'environmental_limits.json')
    resource_config_path = os.path.join(CONFIG_DIR, 'resource_config.json')

    # Load configuration files
    system_params = load_json_config(system_params_path, logger)
    environmental_limits = load_json_config(environmental_limits_path, logger)
    resource_config = load_json_config(resource_config_path, logger)

    # Validate configurations
    validate_configs(resource_config, system_params, environmental_limits, logger)

    # Set environment variables based on environmental limits
    setup_environment_variables(environmental_limits, logger)

    # Configure system
    configure_system(system_params, logger)

    # Set up GPU optimization if needed
    setup_gpu_optimization(environmental_limits, logger)

    # Configure security (start stunnel)
    configure_security(logger)

    # Additional setups if needed
    logger.info("Mining environment has been fully set up.")

if __name__ == "__main__":
    # Ensure the script runs with root privileges
    if os.geteuid() != 0:
        print("Script must be run with root privileges.")
        sys.exit(1)

    setup()
