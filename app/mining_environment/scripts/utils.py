# utils.py

import psutil
import functools
import logging
from time import sleep
from typing import Any, Dict, Optional, List
import pynvml
from threading import Lock

def retry(ExceptionToCheck, tries=4, delay=3, backoff=2):
    """
    Decorator to automatically retry a function if an exception occurs.

    :param ExceptionToCheck: Exception to check. Can be a tuple of exceptions.
    :param tries: Number of attempts (not retries) before giving up.
    :param delay: Initial delay between attempts (seconds).
    :param backoff: Multiplier applied to delay between attempts.
    """
    def deco_retry(f):
        @functools.wraps(f)
        def f_retry(*args, **kwargs):
            mtries, mdelay = tries, delay
            while mtries > 1:
                try:
                    return f(*args, **kwargs)
                except ExceptionToCheck as e:
                    logging.getLogger(__name__).warning(f"Error '{e}' occurred in '{f.__name__}'. Retrying in {mdelay} seconds...")
                    sleep(mdelay)
                    mtries -= 1
                    mdelay *= backoff
            return f(*args, **kwargs)
        return f_retry
    return deco_retry

class GPUManager:
    """
    GPU management class, including NVML initialization and GPU information collection.
    """
    _instance = None
    _lock = Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(GPUManager, cls).__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.gpu_initialized = False
        self.logger = logging.getLogger(__name__)
        self.initialize_nvml()

    def initialize_nvml(self):
        """Initialize NVML for GPU management."""
        try:
            pynvml.nvmlInit()
            self.gpu_count = pynvml.nvmlDeviceGetCount()
            self.gpu_initialized = True
            self.logger.info("NVML initialized successfully. Detected {0} GPUs.".format(self.gpu_count))
        except pynvml.NVMLError as e:
            self.gpu_initialized = False
            self.logger.warning(f"Cannot initialize NVML: {e}. GPU management functionality will be disabled.")

    def shutdown_nvml(self):
        """Shutdown NVML."""
        if self.gpu_initialized:
            try:
                pynvml.nvmlShutdown()
                self.logger.info("NVML has been shut down successfully.")
            except pynvml.NVMLError as e:
                self.logger.error(f"Error shutting down NVML: {e}")

    def get_total_gpu_memory(self) -> float:
        """Get total GPU memory (MB)."""
        if not self.gpu_initialized:
            return 0.0
        total_memory = 0.0
        try:
            for i in range(self.gpu_count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                total_memory += mem_info.total / (1024 ** 2)  # Convert to MB
            return total_memory
        except pynvml.NVMLError as e:
            self.logger.error(f"Error getting total GPU memory: {e}")
            return 0.0

    def get_used_gpu_memory(self) -> float:
        """Get used GPU memory (MB)."""
        if not self.gpu_initialized:
            return 0.0
        used_memory = 0.0
        try:
            for i in range(self.gpu_count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                used_memory += mem_info.used / (1024 ** 2)  # Convert to MB
            return used_memory
        except pynvml.NVMLError as e:
            self.logger.error(f"Error getting used GPU memory: {e}")
            return 0.0

class MiningProcess:
    """
    Represents a mining process with resource usage metrics.
    """
    def __init__(self, pid: int, name: str, priority: int = 1, network_interface: str = 'eth0', logger: Optional[logging.Logger] = None):
        self.pid = pid
        self.name = name
        self.priority = priority  # Priority value (1 is lowest)
        self.cpu_usage = 0.0  # In percentage
        self.gpu_usage = 0.0  # In percentage
        self.memory_usage = 0.0  # In percentage
        self.disk_io = 0.0  # MB
        self.network_io = 0.0  # MB since last update
        self.mark = pid % 65535  # Unique network identifier, 16-bit limited
        self.network_interface = network_interface
        self._prev_bytes_sent = None
        self._prev_bytes_recv = None
        self.is_cloaked = False  # Process cloaking status
        self.logger = logger or logging.getLogger(__name__)

        # Use GPUManager to check GPU
        self.gpu_manager = GPUManager()
        self.gpu_initialized = self.gpu_manager.gpu_initialized

    @retry(pynvml.NVMLError, tries=3, delay=2, backoff=2)
    def get_gpu_usage(self) -> float:
        """
        Get GPU usage for the process.
        Note: NVML doesn't provide per-process GPU usage directly.
        This method estimates GPU usage based on used GPU memory.
        """
        if not self.gpu_manager.gpu_initialized:
            return 0.0
        try:
            total_gpu_memory = self.gpu_manager.get_total_gpu_memory()
            used_gpu_memory = self.gpu_manager.get_used_gpu_memory()
            if total_gpu_memory == 0:
                return 0.0
            gpu_usage_percent = (used_gpu_memory / total_gpu_memory) * 100
            return gpu_usage_percent
        except Exception as e:
            self.logger.error(f"Error getting GPU usage for process {self.name} (PID: {self.pid}): {e}")
            return 0.0

    def is_gpu_process(self) -> bool:
        """
        Determine if the process uses GPU.
        Can be extended based on specific criteria or configurations.
        """
        # Perform check based on process name or other criteria
        gpu_process_keywords = ['llmsengen', 'gpu_miner']  # Extend this list as needed
        return any(keyword in self.name.lower() for keyword in gpu_process_keywords)

    def update_resource_usage(self):
        """
        Update resource usage metrics for the mining process.
        """
        try:
            proc = psutil.Process(self.pid)
            self.cpu_usage = proc.cpu_percent(interval=0.1)
            self.memory_usage = proc.memory_percent()

            # Update Disk I/O
            io_counters = proc.io_counters()
            self.disk_io = (io_counters.read_bytes + io_counters.write_bytes) / (1024 * 1024)  # Convert to MB

            # Update Network I/O
            net_io = psutil.net_io_counters(pernic=True)
            if self.network_interface in net_io:
                current_bytes_sent = net_io[self.network_interface].bytes_sent
                current_bytes_recv = net_io[self.network_interface].bytes_recv

                if self._prev_bytes_sent is not None and self._prev_bytes_recv is not None:
                    sent_diff = current_bytes_sent - self._prev_bytes_sent
                    recv_diff = current_bytes_recv - self._prev_bytes_recv
                    self.network_io = (sent_diff + recv_diff) / (1024 * 1024)  # MB
                else:
                    self.network_io = 0.0  # Initial measurement

                # Update previous bytes
                self._prev_bytes_sent = current_bytes_sent
                self._prev_bytes_recv = current_bytes_recv
            else:
                self.logger.warning(f"Network interface '{self.network_interface}' not found for process {self.name} (PID: {self.pid}).")
                self.network_io = 0.0

            # Update GPU Usage if initialized and applicable
            if self.gpu_initialized and self.is_gpu_process():
                self.gpu_usage = self.get_gpu_usage()
            else:
                self.gpu_usage = 0.0  # Not applicable

            self.logger.debug(f"Updated resource usage for process {self.name} (PID: {self.pid}): CPU {self.cpu_usage}%, GPU {self.gpu_usage}%, RAM {self.memory_usage}%, Disk I/O {self.disk_io} MB, Network I/O {self.network_io} MB.")
        except psutil.NoSuchProcess:
            self.logger.error(f"Process {self.name} (PID: {self.pid}) does not exist.")
            self.cpu_usage = self.memory_usage = self.disk_io = self.network_io = self.gpu_usage = 0.0
        except Exception as e:
            self.logger.error(f"Error updating resource usage for process {self.name} (PID: {self.pid}): {e}")
            self.cpu_usage = self.memory_usage = self.disk_io = self.network_io = self.gpu_usage = 0.0

    def reset_network_io(self):
        """
        Reset Network I/O values to prepare for next measurement.
        """
        self._prev_bytes_sent = None
        self._prev_bytes_recv = None
        self.network_io = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert MiningProcess attributes to a dictionary.
        """
        return {
            'pid': self.pid,
            'name': self.name,
            'priority': self.priority,
            'cpu_usage': self.cpu_usage,
            'gpu_usage': self.gpu_usage,
            'memory_usage': self.memory_usage,
            'disk_io': self.disk_io,
            'network_io': self.network_io,
            'mark': self.mark,
            'network_interface': self.network_interface,
            'is_cloaked': self.is_cloaked
        }
