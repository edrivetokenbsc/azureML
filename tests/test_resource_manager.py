# tests/test_shared_resource_manager.py

import os
import sys
import logging
import pytest
import subprocess
import pynvml
import torch
from unittest.mock import patch, MagicMock, mock_open, call
from pathlib import Path
from queue import PriorityQueue, Empty, Queue
from threading import Lock, Event
from typing import Any, Dict, List



# Thiết lập biến môi trường TESTING=1
os.environ["TESTING"] = "1"

# Định nghĩa các thư mục cần thiết
APP_DIR = Path("/home/llmss/llmsdeep/app")
CONFIG_DIR = APP_DIR / "mining_environment" / "config"
MODELS_DIR = APP_DIR / "mining_environment" / "models"
SCRIPTS_DIR = APP_DIR / "mining_environment" / "scripts"

# Thêm APP_DIR vào sys.path
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

# Import lớp cần kiểm thử
from mining_environment.scripts.resource_manager import SharedResourceManager, MiningProcess


@pytest.fixture
def mock_logger():
    """Fixture để tạo mock logger."""
    logger = MagicMock()
    logger.info = MagicMock()
    logger.error = MagicMock()
    return logger

@pytest.fixture
def shared_resource_manager(mock_logger):
    """Fixture để tạo instance của SharedResourceManager với cấu hình hợp nhất và logger mock."""
    config = {
        "optimization_parameters": {
            "gpu_power_adjustment_step": 10,
            "disk_io_limit_step_mbps": 5
        },
        "resource_allocation": {
            "disk_io": {
                "min_limit_mbps": 10,
                "max_limit_mbps": 100
            },
            "ram": {
                "max_allocation_mb": 2048
            },
            "gpu": {
                "max_usage_percent": [50, 75, 100]
            },
            "network": {
                "bandwidth_limit_mbps": 100
            }
        },
        "processes": {
            "CPU": "cpu_miner",
            "GPU": "gpu_miner"
        }
    }

    # Khởi tạo instance của SharedResourceManager với mock logger
    return SharedResourceManager(config=config, logger=mock_logger)

# ----------------------------
# Kiểm thử SharedResourceManager
# ----------------------------

@patch('mining_environment.scripts.resource_manager.assign_process_to_cgroups')
def test_adjust_cpu_threads(mock_assign, shared_resource_manager):
    """Kiểm thử phương thức adjust_cpu_threads."""
    pid = 1234
    cpu_threads = 4
    process_name = "test_process"

    shared_resource_manager.adjust_cpu_threads(pid, cpu_threads, process_name)

    mock_assign.assert_called_once_with(pid, {'cpu_threads': cpu_threads}, process_name, shared_resource_manager.logger)
    shared_resource_manager.logger.info.assert_called_with(
        f"Điều chỉnh số luồng CPU xuống {cpu_threads} cho tiến trình {process_name} (PID: {pid})."
    )

@patch('mining_environment.scripts.resource_manager.assign_process_to_cgroups', side_effect=Exception("Error adjusting CPU threads"))
def test_adjust_cpu_threads_exception(mock_assign, shared_resource_manager):
    """Kiểm thử phương thức adjust_cpu_threads khi có ngoại lệ."""
    pid = 1234
    cpu_threads = 4
    process_name = "test_process"

    shared_resource_manager.adjust_cpu_threads(pid, cpu_threads, process_name)

    mock_assign.assert_called_once_with(pid, {'cpu_threads': cpu_threads}, process_name, shared_resource_manager.logger)
    shared_resource_manager.logger.error.assert_called_with(
        f"Lỗi khi điều chỉnh số luồng CPU cho tiến trình {process_name} (PID: {pid}): Error adjusting CPU threads"
    )

@patch('mining_environment.scripts.resource_manager.assign_process_to_cgroups')
def test_adjust_ram_allocation(mock_assign, shared_resource_manager):
    """Kiểm thử phương thức adjust_ram_allocation."""
    pid = 5678
    ram_allocation_mb = 1024
    process_name = "test_process_ram"

    shared_resource_manager.adjust_ram_allocation(pid, ram_allocation_mb, process_name)

    mock_assign.assert_called_once_with(pid, {'memory': ram_allocation_mb}, process_name, shared_resource_manager.logger)
    shared_resource_manager.logger.info.assert_called_with(
        f"Điều chỉnh giới hạn RAM xuống {ram_allocation_mb}MB cho tiến trình {process_name} (PID: {pid})."
    )

@patch('mining_environment.scripts.resource_manager.assign_process_to_cgroups', side_effect=Exception("Error adjusting RAM"))
def test_adjust_ram_allocation_exception(mock_assign, shared_resource_manager):
    """Kiểm thử phương thức adjust_ram_allocation khi có ngoại lệ."""
    pid = 5678
    ram_allocation_mb = 1024
    process_name = "test_process_ram"

    shared_resource_manager.adjust_ram_allocation(pid, ram_allocation_mb, process_name)

    mock_assign.assert_called_once_with(pid, {'memory': ram_allocation_mb}, process_name, shared_resource_manager.logger)
    shared_resource_manager.logger.error.assert_called_with(
        f"Lỗi khi điều chỉnh RAM cho tiến trình {process_name} (PID: {pid}): Error adjusting RAM"
    )

@patch('mining_environment.scripts.resource_manager.set_gpu_usage')
def test_adjust_gpu_usage(mock_set_gpu_usage, shared_resource_manager):
    """Kiểm thử phương thức adjust_gpu_usage sử dụng fixture shared_resource_manager."""

    # Tạo một process giả
    process = MagicMock()
    process.pid = 12345
    process.name = "gpu_miner"

    # Dữ liệu đầu vào giả lập cho GPU usage
    gpu_usage_percent = [50.0, 60.0]

    # Gọi phương thức cần kiểm thử
    shared_resource_manager.adjust_gpu_usage(process, gpu_usage_percent)

    # Kỳ vọng mức GPU usage mới
    expected_new_gpu_usage = [60.0, 70.0]  # Mỗi giá trị cộng thêm 10 từ gpu_power_adjustment_step

    # Kiểm tra set_gpu_usage được gọi với đúng tham số
    mock_set_gpu_usage.assert_called_once_with(process.pid, expected_new_gpu_usage)

    # Kiểm tra logger có ghi log đúng không
    shared_resource_manager.logger.info.assert_called_with(
        f"Điều chỉnh mức sử dụng GPU xuống {expected_new_gpu_usage} cho tiến trình {process.name} (PID: {process.pid})."
    )

@patch('mining_environment.scripts.resource_manager.set_gpu_usage', side_effect=Exception("Error adjusting GPU usage"))
def test_adjust_gpu_usage_exception(mock_set_gpu_usage, shared_resource_manager):
    """Kiểm thử phương thức adjust_gpu_usage khi có ngoại lệ sử dụng fixture shared_resource_manager."""

    # Tạo một process giả
    process = MagicMock()
    process.pid = 91011
    process.name = "gpu_miner"

    # Dữ liệu đầu vào giả lập cho GPU usage
    gpu_usage_percent = [50.0, 60.0]

    # Gọi phương thức cần kiểm thử
    shared_resource_manager.adjust_gpu_usage(process, gpu_usage_percent)

    # Kỳ vọng mức GPU usage mới
    expected_new_gpu_usage = [60.0, 70.0]  # Mỗi giá trị cộng thêm 10 từ gpu_power_adjustment_step

    # Kiểm tra set_gpu_usage được gọi với đúng tham số
    mock_set_gpu_usage.assert_called_once_with(process.pid, expected_new_gpu_usage)

    # Kiểm tra logger có ghi log lỗi đúng không
    shared_resource_manager.logger.error.assert_called_with(
        f"Lỗi khi điều chỉnh mức sử dụng GPU cho tiến trình {process.name} (PID: {process.pid}): Error adjusting GPU usage"
    )

@patch('mining_environment.scripts.resource_manager.temperature_monitor.get_current_disk_io_limit')
@patch('mining_environment.scripts.resource_manager.assign_process_to_cgroups')
def test_adjust_disk_io_limit(mock_assign, mock_get_disk_io, shared_resource_manager):
    """Kiểm thử phương thức adjust_disk_io_limit."""
    process = MagicMock()
    process.pid = 1212
    process.name = "disk_io_process"
    disk_io_limit_mbps = 50.0

    mock_get_disk_io.return_value = 55.0  # current_limit > disk_io_limit_mbps
    shared_resource_manager.adjust_disk_io_limit(process, disk_io_limit_mbps)

    new_limit = 55.0 - 5  # adjustment_step = 5
    new_limit = max(10, min(new_limit, 100))  # min_limit=10, max_limit=100

    mock_assign.assert_called_once_with(process.pid, {'disk_io_limit_mbps': new_limit}, process.name, shared_resource_manager.logger)
    shared_resource_manager.logger.info.assert_called_with(
        f"Điều chỉnh giới hạn Disk I/O xuống {new_limit} Mbps cho tiến trình {process.name} (PID: {process.pid})."
    )

@patch('mining_environment.scripts.resource_manager.temperature_monitor.get_current_disk_io_limit', side_effect=Exception("Disk I/O Error"))
@patch('mining_environment.scripts.resource_manager.assign_process_to_cgroups')
def test_adjust_disk_io_limit_exception(mock_assign, mock_get_disk_io, shared_resource_manager):
    """Kiểm thử phương thức adjust_disk_io_limit khi có ngoại lệ."""
    process = MagicMock()
    process.pid = 1212
    process.name = "disk_io_process"
    disk_io_limit_mbps = 50.0

    shared_resource_manager.adjust_disk_io_limit(process, disk_io_limit_mbps)

    mock_assign.assert_not_called()
    shared_resource_manager.logger.error.assert_called_with(
        f"Lỗi khi điều chỉnh Disk I/O cho tiến trình {process.name} (PID: {process.pid}): Disk I/O Error"
    )

@patch('mining_environment.scripts.resource_manager.SharedResourceManager.apply_network_cloaking')
def test_adjust_network_bandwidth(mock_apply_cloaking, shared_resource_manager):
    """Kiểm thử phương thức adjust_network_bandwidth."""
    process = MagicMock()
    process.name = "network_process"
    process.pid = 1313
    process.network_interface = "eth0"
    bandwidth_limit_mbps = 80.0

    shared_resource_manager.adjust_network_bandwidth(process, bandwidth_limit_mbps)

    mock_apply_cloaking.assert_called_once_with("eth0", bandwidth_limit_mbps, process)
    shared_resource_manager.logger.info.assert_called_with(
        f"Điều chỉnh giới hạn băng thông mạng xuống {bandwidth_limit_mbps} Mbps cho tiến trình {process.name} (PID: {process.pid})."
    )

@patch('mining_environment.scripts.resource_manager.SharedResourceManager.apply_network_cloaking', side_effect=Exception("Network Cloaking Error"))
def test_adjust_network_bandwidth_exception(mock_apply_cloaking, shared_resource_manager):
    """Kiểm thử phương thức adjust_network_bandwidth khi có ngoại lệ."""
    process = MagicMock()
    process.name = "network_process"
    process.pid = 1313
    process.network_interface = "eth0"
    bandwidth_limit_mbps = 80.0

    shared_resource_manager.adjust_network_bandwidth(process, bandwidth_limit_mbps)

    mock_apply_cloaking.assert_called_once_with("eth0", bandwidth_limit_mbps, process)
    shared_resource_manager.logger.error.assert_called_with(
        f"Lỗi khi điều chỉnh Mạng cho tiến trình {process.name} (PID: {process.pid}): Network Cloaking Error"
    )

@patch('mining_environment.scripts.resource_manager.assign_process_to_cgroups')
def test_adjust_cpu_frequency(mock_assign, shared_resource_manager):
    """Kiểm thử phương thức adjust_cpu_frequency."""
    pid = 1414
    frequency = 2500
    process_name = "cpu_process"

    shared_resource_manager.adjust_cpu_frequency(pid, frequency, process_name)

    mock_assign.assert_called_once_with(pid, {'cpu_freq': frequency}, process_name, shared_resource_manager.logger)
    shared_resource_manager.logger.info.assert_called_with(
        f"Đặt tần số CPU xuống {frequency}MHz cho tiến trình {process_name} (PID: {pid})."
    )

@patch('mining_environment.scripts.resource_manager.assign_process_to_cgroups', side_effect=Exception("CPU Frequency Error"))
def test_adjust_cpu_frequency_exception(mock_assign, shared_resource_manager):
    """Kiểm thử phương thức adjust_cpu_frequency khi có ngoại lệ."""
    pid = 1414
    frequency = 2500
    process_name = "cpu_process"

    shared_resource_manager.adjust_cpu_frequency(pid, frequency, process_name)

    mock_assign.assert_called_once_with(pid, {'cpu_freq': frequency}, process_name, shared_resource_manager.logger)
    shared_resource_manager.logger.error.assert_called_with(
        f"Lỗi khi điều chỉnh tần số CPU cho tiến trình {process_name} (PID: {pid}): CPU Frequency Error"
    )



@patch('mining_environment.scripts.resource_manager.pynvml.nvmlDeviceSetPowerManagementLimit')
@patch('mining_environment.scripts.resource_manager.pynvml.nvmlDeviceGetHandleByIndex', return_value=MagicMock())
@patch('mining_environment.scripts.resource_manager.pynvml.nvmlInit')
@patch('mining_environment.scripts.resource_manager.pynvml.nvmlShutdown')
def test_adjust_gpu_power_limit(mock_shutdown, mock_init, mock_get_handle, mock_set_power_limit, shared_resource_manager):
    """Kiểm thử phương thức adjust_gpu_power_limit."""
    pid = 1515
    power_limit = 200
    process_name = "gpu_power_process"

    shared_resource_manager.adjust_gpu_power_limit(pid, power_limit, process_name)

    mock_init.assert_called_once()
    mock_get_handle.assert_called_once_with(0)
    mock_set_power_limit.assert_called_once_with(mock_get_handle.return_value, power_limit * 1000)
    mock_shutdown.assert_called_once()
    shared_resource_manager.logger.info.assert_called_with(
        f"Đặt giới hạn công suất GPU xuống {power_limit}W cho tiến trình {process_name} (PID: {pid})."
    )


@patch('mining_environment.scripts.resource_manager.subprocess.run')
def test_adjust_disk_io_priority(mock_subprocess_run, shared_resource_manager):
    """Kiểm thử phương thức adjust_disk_io_priority."""
    pid = 1616
    ionice_class = 2
    process_name = "disk_io_priority_process"

    shared_resource_manager.adjust_disk_io_priority(pid, ionice_class, process_name)

    mock_subprocess_run.assert_called_once_with(['ionice', '-c', '2', '-p', '1616'], check=True)
    shared_resource_manager.logger.info.assert_called_with(
        f"Đặt ionice class thành {ionice_class} cho tiến trình {process_name} (PID: {pid})."
    )

@patch('mining_environment.scripts.resource_manager.subprocess.run', side_effect=subprocess.CalledProcessError(1, 'ionice'))
def test_adjust_disk_io_priority_subprocess_error(mock_subprocess_run, shared_resource_manager):
    """Kiểm thử phương thức adjust_disk_io_priority khi subprocess gặp lỗi."""
    pid = 1616
    ionice_class = 2
    process_name = "disk_io_priority_process"

    shared_resource_manager.adjust_disk_io_priority(pid, ionice_class, process_name)

    mock_subprocess_run.assert_called_once_with(['ionice', '-c', '2', '-p', '1616'], check=True)
    shared_resource_manager.logger.error.assert_called_with(
        f"Lỗi khi thực hiện ionice: Command 'ionice' returned non-zero exit status 1."
    )

@patch('mining_environment.scripts.resource_manager.subprocess.run', side_effect=Exception("Unknown Error"))
def test_adjust_disk_io_priority_generic_exception(mock_subprocess_run, shared_resource_manager):
    """Kiểm thử phương thức adjust_disk_io_priority khi có ngoại lệ khác."""
    pid = 1616
    ionice_class = 2
    process_name = "disk_io_priority_process"

    shared_resource_manager.adjust_disk_io_priority(pid, ionice_class, process_name)

    mock_subprocess_run.assert_called_once_with(['ionice', '-c', '2', '-p', '1616'], check=True)
    shared_resource_manager.logger.error.assert_called_with(
        f"Lỗi khi điều chỉnh ưu tiên Disk I/O cho tiến trình {process_name} (PID: {pid}): Unknown Error"
    )

@patch('builtins.open', new_callable=mock_open)
def test_drop_caches(mock_file, shared_resource_manager):
    """Kiểm thử phương thức drop_caches."""
    shared_resource_manager.drop_caches()

    mock_file.assert_called_once_with('/proc/sys/vm/drop_caches', 'w')
    mock_file().write.assert_called_once_with('3\n')
    shared_resource_manager.logger.info.assert_called_with("Đã giảm sử dụng cache bằng cách drop_caches.")

def test_drop_caches_exception(shared_resource_manager):
    """Kiểm thử trường hợp lỗi khi gọi drop_caches."""
    # Mô phỏng lỗi khi ghi tệp
    def raise_io_error(*args, **kwargs):
        raise IOError("Lỗi giả lập khi ghi vào /proc/sys/vm/drop_caches")

    with patch("builtins.open", mock_open()) as mocked_open:
        mocked_open.side_effect = raise_io_error  # Gây lỗi IOError khi mở tệp
        shared_resource_manager.drop_caches()
    
    # Xác minh rằng logger ghi nhận lỗi
    shared_resource_manager.logger.error.assert_called_with("Lỗi khi giảm sử dụng cache: Lỗi giả lập khi ghi vào /proc/sys/vm/drop_caches")

@patch('mining_environment.scripts.resource_manager.SharedResourceManager.apply_network_cloaking')
def test_apply_network_cloaking(mock_apply_cloaking, shared_resource_manager):
    """Kiểm thử phương thức apply_network_cloaking."""
    interface = "eth0"
    bandwidth_limit = 50.0
    process = MagicMock()
    process.name = "network_cloak_process"
    process.pid = 1717

    shared_resource_manager.apply_network_cloaking(interface, bandwidth_limit, process)

    mock_apply_cloaking.assert_called_once_with(interface, bandwidth_limit, process)
    # Vì phương thức chưa thực hiện gì, chỉ kiểm tra gọi hàm cloaking và log lỗi nếu có



@patch('mining_environment.scripts.resource_manager.SharedResourceManager.configure_network_interface', side_effect=Exception("Network Cloaking Exception"))
def test_apply_network_cloaking_exception(mock_configure_network, shared_resource_manager):
    """Kiểm thử phương thức apply_network_cloaking khi có ngoại lệ."""
    interface = "eth0"
    bandwidth_limit = 50.0
    process = MagicMock(spec=MiningProcess)
    process.name = "network_cloak_process"
    process.pid = 1717

    # Gọi phương thức và kiểm tra ngoại lệ
    with pytest.raises(Exception) as exc_info:
        shared_resource_manager.apply_network_cloaking(interface, bandwidth_limit, process)
    assert str(exc_info.value) == "Network Cloaking Exception"

    # Kiểm tra logger đã ghi log lỗi đúng cách
    shared_resource_manager.logger.error.assert_called_once_with(
        "Lỗi khi áp dụng cloaking mạng cho tiến trình network_cloak_process (PID: 1717): Network Cloaking Exception"
    )


@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_cpu_frequency')
def test_throttle_cpu_based_on_load_high_load(mock_adjust_cpu_freq, shared_resource_manager):
    """Kiểm thử phương thức throttle_cpu_based_on_load với load > 80%."""
    process = MagicMock()
    process.pid = 1818
    process.name = "high_load_process"
    load_percent = 85.0

    shared_resource_manager.throttle_cpu_based_on_load(process, load_percent)

    mock_adjust_cpu_freq.assert_called_once_with(process.pid, 2000, process.name)
    shared_resource_manager.logger.info.assert_called_with(
        f"Điều chỉnh tần số CPU xuống 2000MHz cho tiến trình {process.name} (PID: {process.pid}) dựa trên tải {load_percent}%."
    )

@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_cpu_frequency')
def test_throttle_cpu_based_on_load_medium_load(mock_adjust_cpu_freq, shared_resource_manager):
    """Kiểm thử phương thức throttle_cpu_based_on_load với 50% < load <= 80%."""
    process = MagicMock()
    process.pid = 1818
    process.name = "medium_load_process"
    load_percent = 65.0

    shared_resource_manager.throttle_cpu_based_on_load(process, load_percent)

    mock_adjust_cpu_freq.assert_called_once_with(process.pid, 2500, process.name)
    shared_resource_manager.logger.info.assert_called_with(
        f"Điều chỉnh tần số CPU xuống 2500MHz cho tiến trình {process.name} (PID: {process.pid}) dựa trên tải {load_percent}%."
    )

@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_cpu_frequency')
def test_throttle_cpu_based_on_load_low_load(mock_adjust_cpu_freq, shared_resource_manager):
    """Kiểm thử phương thức throttle_cpu_based_on_load với load <= 50%."""
    process = MagicMock()
    process.pid = 1818
    process.name = "low_load_process"
    load_percent = 30.0

    shared_resource_manager.throttle_cpu_based_on_load(process, load_percent)

    mock_adjust_cpu_freq.assert_called_once_with(process.pid, 3000, process.name)
    shared_resource_manager.logger.info.assert_called_with(
        f"Điều chỉnh tần số CPU xuống 3000MHz cho tiến trình {process.name} (PID: {process.pid}) dựa trên tải {load_percent}%."
    )

@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_cpu_frequency', side_effect=Exception("CPU Throttle Error"))
def test_throttle_cpu_based_on_load_exception(mock_adjust_cpu_freq, shared_resource_manager):
    """Kiểm thử phương thức throttle_cpu_based_on_load khi có ngoại lệ."""
    process = MagicMock()
    process.pid = 1818
    process.name = "exception_load_process"
    load_percent = 85.0

    shared_resource_manager.throttle_cpu_based_on_load(process, load_percent)

    mock_adjust_cpu_freq.assert_called_once_with(process.pid, 2000, process.name)
    shared_resource_manager.logger.error.assert_called_with(
        f"Lỗi khi điều chỉnh tần số CPU dựa trên tải cho tiến trình {process.name} (PID: {process.pid}): CPU Throttle Error"
    )

@patch('mining_environment.scripts.resource_manager.CloakStrategyFactory.create_strategy')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.execute_adjustments')
def test_apply_cloak_strategy(mock_execute_adjustments, mock_create_strategy, shared_resource_manager):
    """Kiểm thử phương thức apply_cloak_strategy trong trường hợp thành công."""
    strategy_name = "test_strategy"
    process = MagicMock()
    process.pid = 1919
    process.name = "cloak_process"

    mock_strategy = MagicMock()
    mock_strategy.apply.return_value = {
        'cpu_freq': 2500,
        'gpu_power_limit': 200,
        'network_bandwidth_limit_mbps': 80.0,
        'ionice_class': 2
    }
    mock_create_strategy.return_value = mock_strategy

    # Giả lập các phương thức get_current_*
    with patch.object(shared_resource_manager, 'get_current_cpu_frequency', return_value=3000):
        with patch.object(shared_resource_manager, 'get_current_gpu_power_limit', return_value=250):
            with patch.object(shared_resource_manager, 'get_current_network_bandwidth_limit', return_value=100.0):
                with patch.object(shared_resource_manager, 'get_current_ionice_class', return_value=1):
                    shared_resource_manager.apply_cloak_strategy(strategy_name, process)

    mock_create_strategy.assert_called_once_with(strategy_name, shared_resource_manager.config, shared_resource_manager.logger, shared_resource_manager.is_gpu_initialized())
    mock_strategy.apply.assert_called_once_with(process)
    shared_resource_manager.logger.info.assert_called_with(
        f"Áp dụng điều chỉnh {strategy_name} cho tiến trình {process.name} (PID: {process.pid}): {{'cpu_freq': 2500, 'gpu_power_limit': 200, 'network_bandwidth_limit_mbps': 80.0, 'ionice_class': 2}}"
    )
    mock_execute_adjustments.assert_called_once_with(mock_strategy.apply.return_value, process)
    assert shared_resource_manager.original_resource_limits[process.pid] == {
        'cpu_freq': 3000,
        'gpu_power_limit': 250,
        'network_bandwidth_limit_mbps': 100.0,
        'ionice_class': 1
    }

@patch('mining_environment.scripts.resource_manager.CloakStrategyFactory.create_strategy')
def test_apply_cloak_strategy_no_adjustments(mock_create_strategy, shared_resource_manager):
    """Kiểm thử phương thức apply_cloak_strategy khi chiến lược không trả về điều chỉnh nào."""
    strategy_name = "empty_strategy"
    process = MagicMock()
    process.pid = 2020
    process.name = "empty_cloak_process"

    mock_strategy = MagicMock()
    mock_strategy.apply.return_value = None
    mock_create_strategy.return_value = mock_strategy

    shared_resource_manager.apply_cloak_strategy(strategy_name, process)

    mock_create_strategy.assert_called_once_with(strategy_name, shared_resource_manager.config, shared_resource_manager.logger, shared_resource_manager.is_gpu_initialized())
    mock_strategy.apply.assert_called_once_with(process)
    shared_resource_manager.logger.warning.assert_called_with(
        f"Không có điều chỉnh nào được áp dụng cho chiến lược {strategy_name} cho tiến trình {process.name} (PID: {process.pid})."
    )

@patch('mining_environment.scripts.resource_manager.CloakStrategyFactory.create_strategy', return_value=None)
def test_apply_cloak_strategy_strategy_creation_failure(mock_create_strategy, shared_resource_manager):
    """Kiểm thử phương thức apply_cloak_strategy khi tạo chiến lược thất bại."""
    strategy_name = "invalid_strategy"
    process = MagicMock()
    process.pid = 2021
    process.name = "invalid_cloak_process"

    shared_resource_manager.apply_cloak_strategy(strategy_name, process)

    mock_create_strategy.assert_called_once_with(strategy_name, shared_resource_manager.config, shared_resource_manager.logger, shared_resource_manager.is_gpu_initialized())
    shared_resource_manager.logger.warning.assert_called_with(
        f"Chiến lược cloaking {strategy_name} không được tạo thành công cho tiến trình {process.name} (PID: {process.pid})."
    )

@patch('mining_environment.scripts.resource_manager.SharedResourceManager.execute_adjustments')
@patch('mining_environment.scripts.resource_manager.CloakStrategyFactory.create_strategy', side_effect=Exception("Strategy Creation Error"))
def test_apply_cloak_strategy_creation_exception(mock_create_strategy, mock_execute_adjustments, shared_resource_manager):
    """Kiểm thử phương thức apply_cloak_strategy khi tạo chiến lược ném ra ngoại lệ."""
    strategy_name = "error_strategy"
    process = MagicMock()
    process.pid = 2022
    process.name = "error_cloak_process"

    shared_resource_manager.apply_cloak_strategy(strategy_name, process)

    mock_create_strategy.assert_called_once_with(strategy_name, shared_resource_manager.config, shared_resource_manager.logger, shared_resource_manager.is_gpu_initialized())
    shared_resource_manager.logger.error.assert_called_with(
        f"Lỗi khi áp dụng chiến lược cloaking {strategy_name} cho tiến trình {process.name} (PID: {process.pid}): Strategy Creation Error"
    )
    mock_execute_adjustments.assert_not_called()

@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_cpu_frequency')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_cpu_threads')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_ram_allocation')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_gpu_power_limit')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_disk_io_priority')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_network_bandwidth')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.drop_caches')
def test_restore_resources(mock_drop_caches, mock_adjust_network_bw, mock_adjust_disk_io, mock_adjust_gpu_power, 
                          mock_adjust_ram, mock_adjust_cpu_threads, mock_adjust_cpu_freq, shared_resource_manager):
    """Kiểm thử phương thức restore_resources trong trường hợp thành công."""
    process = MagicMock()
    process.pid = 2121
    process.name = "restore_process"

    # Giả lập original_resource_limits
    shared_resource_manager.original_resource_limits = {
        process.pid: {
            'cpu_freq': 3000,
            'cpu_threads': 4,
            'ram_allocation_mb': 2048,
            'gpu_power_limit': 250,
            'ionice_class': 2,
            'network_bandwidth_limit_mbps': 100.0
        }
    }

    shared_resource_manager.restore_resources(process)

    mock_adjust_cpu_freq.assert_called_once_with(process.pid, 3000, process.name)
    mock_adjust_cpu_threads.assert_called_once_with(process.pid, 4, process.name)
    mock_adjust_ram.assert_called_once_with(process.pid, 2048, process.name)
    mock_adjust_gpu_power.assert_called_once_with(process.pid, 250, process.name)
    mock_adjust_disk_io.assert_called_once_with(process.pid, 2, process.name)
    mock_adjust_network_bw.assert_called_once_with(process, 100.0)
    mock_drop_caches.assert_not_called()  # Không có yêu cầu drop_caches trong restore

    shared_resource_manager.logger.info.assert_any_call(
        f"Đã khôi phục tần số CPU về 3000MHz cho tiến trình {process.name} (PID: {process.pid})."
    )
    shared_resource_manager.logger.info.assert_any_call(
        f"Đã khôi phục số luồng CPU về 4 cho tiến trình {process.name} (PID: {process.pid})."
    )
    shared_resource_manager.logger.info.assert_any_call(
        f"Đã khôi phục giới hạn RAM về 2048MB cho tiến trình {process.name} (PID: {process.pid})."
    )
    shared_resource_manager.logger.info.assert_any_call(
        f"Đã khôi phục giới hạn công suất GPU về 250W cho tiến trình {process.name} (PID: {process.pid})."
    )
    shared_resource_manager.logger.info.assert_any_call(
        f"Đã khôi phục lớp ionice về 2 cho tiến trình {process.name} (PID: {process.pid})."
    )
    shared_resource_manager.logger.info.assert_any_call(
        f"Đã khôi phục giới hạn băng thông mạng về 100.0 Mbps cho tiến trình {process.name} (PID: {process.pid})."
    )
    assert process.pid not in shared_resource_manager.original_resource_limits

@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_cpu_frequency', side_effect=Exception("Restore CPU Frequency Error"))
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_cpu_threads')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_ram_allocation')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_gpu_power_limit')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_disk_io_priority')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_network_bandwidth')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.drop_caches')
def test_restore_resources_exception(mock_drop_caches, mock_adjust_network_bw, mock_adjust_disk_io, mock_adjust_gpu_power, 
                                    mock_adjust_ram, mock_adjust_cpu_threads, mock_adjust_cpu_freq, shared_resource_manager):
    """Kiểm thử phương thức restore_resources khi có ngoại lệ trong quá trình khôi phục."""
    process = MagicMock()
    process.pid = 2121
    process.name = "restore_process_exception"

    # Giả lập original_resource_limits
    shared_resource_manager.original_resource_limits = {
        process.pid: {
            'cpu_freq': 3000,
            'cpu_threads': 4,
            'ram_allocation_mb': 2048,
            'gpu_power_limit': 250,
            'ionice_class': 2,
            'network_bandwidth_limit_mbps': 100.0
        }
    }

    shared_resource_manager.restore_resources(process)

    mock_adjust_cpu_freq.assert_called_once_with(process.pid, 3000, process.name)
    mock_adjust_cpu_threads.assert_called_once_with(process.pid, 4, process.name)
    mock_adjust_ram.assert_called_once_with(process.pid, 2048, process.name)
    mock_adjust_gpu_power.assert_called_once_with(process.pid, 250, process.name)
    mock_adjust_disk_io.assert_called_once_with(process.pid, 2, process.name)
    mock_adjust_network_bw.assert_called_once_with(process, 100.0)
    mock_drop_caches.assert_not_called()  # Không có yêu cầu drop_caches trong restore

    shared_resource_manager.logger.error.assert_called_with(
        f"Lỗi khi khôi phục tài nguyên cho tiến trình {process.name} (PID: {process.pid}): Restore CPU Frequency Error"
    )

@patch('mining_environment.scripts.resource_manager.psutil.cpu_freq')
def test_get_current_cpu_frequency(mock_cpu_freq, shared_resource_manager):
    """Kiểm thử phương thức get_current_cpu_frequency."""
    pid = 5555
    mock_cpu_freq.return_value.current = 2500

    freq = shared_resource_manager.get_current_cpu_frequency(pid)

    mock_cpu_freq.assert_called_once()
    assert freq == 2500

@patch('mining_environment.scripts.resource_manager.psutil.cpu_freq', side_effect=Exception("CPU Frequency Error"))
def test_get_current_cpu_frequency_exception(mock_cpu_freq, shared_resource_manager):
    """Kiểm thử phương thức get_current_cpu_frequency khi có ngoại lệ."""
    pid = 5555

    freq = shared_resource_manager.get_current_cpu_frequency(pid)

    mock_cpu_freq.assert_called_once()
    shared_resource_manager.logger.error.assert_called_with(
        f"Lỗi khi lấy tần số CPU hiện tại cho PID {pid}: CPU Frequency Error"
    )
    assert freq is None

@patch('mining_environment.scripts.resource_manager.pynvml.nvmlDeviceGetPowerManagementLimit', return_value=250000)
@patch('mining_environment.scripts.resource_manager.pynvml.nvmlDeviceGetHandleByIndex', return_value=MagicMock())
@patch('mining_environment.scripts.resource_manager.pynvml.nvmlInit')
@patch('mining_environment.scripts.resource_manager.pynvml.nvmlShutdown')
def test_get_current_gpu_power_limit(mock_shutdown, mock_init, mock_get_handle, mock_get_limit, shared_resource_manager):
    """Kiểm thử phương thức get_current_gpu_power_limit."""
    pid = 4444

    power_limit = shared_resource_manager.get_current_gpu_power_limit(pid)

    mock_init.assert_called_once()
    mock_get_handle.assert_called_once_with(0)
    mock_get_limit.assert_called_once_with(mock_get_handle.return_value)
    mock_shutdown.assert_called_once()
    assert power_limit == 250  # Chuyển đổi từ mW sang W

@patch('mining_environment.scripts.resource_manager.pynvml.nvmlDeviceGetPowerManagementLimit', side_effect=pynvml.NVMLError("NVML Error"))
@patch('mining_environment.scripts.resource_manager.pynvml.nvmlDeviceGetHandleByIndex', return_value=MagicMock())
@patch('mining_environment.scripts.resource_manager.pynvml.nvmlInit')
@patch('mining_environment.scripts.resource_manager.pynvml.nvmlShutdown')
def test_get_current_gpu_power_limit_exception(mock_shutdown, mock_init, mock_get_handle, mock_get_limit, shared_resource_manager):
    """Kiểm thử phương thức get_current_gpu_power_limit khi có ngoại lệ."""
    pid = 4444

    power_limit = shared_resource_manager.get_current_gpu_power_limit(pid)

    mock_init.assert_called_once()
    mock_get_handle.assert_called_once_with(0)
    mock_get_limit.assert_called_once_with(mock_get_handle.return_value)
    mock_shutdown.assert_called_once()
    shared_resource_manager.logger.error.assert_called_with(
        f"Lỗi khi lấy giới hạn công suất GPU hiện tại cho PID {pid}: NVML Error"
    )
    assert power_limit is None

def test_get_current_network_bandwidth_limit(shared_resource_manager):
    """Kiểm thử phương thức get_current_network_bandwidth_limit."""
    pid = 6666
    bw_limit = shared_resource_manager.get_current_network_bandwidth_limit(pid)
    assert bw_limit is None  # Theo định nghĩa trong phương thức

@patch('mining_environment.scripts.resource_manager.psutil.Process')
def test_get_current_ionice_class(mock_process, shared_resource_manager):
    """Kiểm thử phương thức get_current_ionice_class."""
    pid = 6666
    mock_proc = MagicMock()
    mock_proc.ionice.return_value = 3
    mock_process.return_value = mock_proc

    ionice_class = shared_resource_manager.get_current_ionice_class(pid)

    mock_process.assert_called_once_with(pid)
    mock_proc.ionice.assert_called_once()
    assert ionice_class == 3

@patch('mining_environment.scripts.resource_manager.psutil.Process', side_effect=Exception("Process Error"))
def test_get_current_ionice_class_exception(mock_process, shared_resource_manager):
    """Kiểm thử phương thức get_current_ionice_class khi có ngoại lệ."""
    pid = 6666

    ionice_class = shared_resource_manager.get_current_ionice_class(pid)

    mock_process.assert_called_once_with(pid)
    shared_resource_manager.logger.error.assert_called_with(
        f"Lỗi khi lấy ionice class cho PID {pid}: Process Error"
    )
    assert ionice_class is None

@patch('mining_environment.scripts.resource_manager.pynvml.nvmlDeviceGetCount', return_value=1)
@patch('mining_environment.scripts.resource_manager.pynvml.nvmlInit')
@patch('mining_environment.scripts.resource_manager.pynvml.nvmlShutdown')
def test_is_gpu_initialized_true(mock_shutdown, mock_init, mock_get_count, shared_resource_manager):
    """Kiểm thử phương thức is_gpu_initialized khi GPU được khởi tạo thành công."""
    result = shared_resource_manager.is_gpu_initialized()
    mock_init.assert_called_once()
    mock_get_count.assert_called_once()
    mock_shutdown.assert_called_once()
    assert result is True

@patch('mining_environment.scripts.resource_manager.pynvml.nvmlDeviceGetCount', return_value=0)
@patch('mining_environment.scripts.resource_manager.pynvml.nvmlInit')
@patch('mining_environment.scripts.resource_manager.pynvml.nvmlShutdown')
def test_is_gpu_initialized_false(mock_shutdown, mock_init, mock_get_count, shared_resource_manager):
    """Kiểm thử phương thức is_gpu_initialized khi không có GPU nào được khởi tạo."""
    result = shared_resource_manager.is_gpu_initialized()
    mock_init.assert_called_once()
    mock_get_count.assert_called_once()
    mock_shutdown.assert_called_once()
    assert result is False

@patch('mining_environment.scripts.resource_manager.pynvml.nvmlDeviceGetCount', side_effect=pynvml.NVMLError("NVML Init Error"))
@patch('mining_environment.scripts.resource_manager.pynvml.nvmlInit')
def test_is_gpu_initialized_exception(mock_init, mock_get_count, shared_resource_manager):
    """Kiểm thử phương thức is_gpu_initialized khi có ngoại lệ."""
    result = shared_resource_manager.is_gpu_initialized()
    mock_init.assert_called_once()
    mock_get_count.assert_called_once()
    mock_shutdown = shared_resource_manager.logger
    mock_get_count.assert_called_once()
    shared_resource_manager.logger.error.assert_called_with(
        f"Lỗi khi kiểm tra GPU: NVML Init Error"
    )
    assert result is False

@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_cpu_frequency')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_gpu_power_limit')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_network_bandwidth')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_disk_io_priority')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_ram_allocation')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_cpu_threads')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.drop_caches')
def test_execute_adjustments(mock_drop_caches, mock_adjust_cpu_threads, mock_adjust_ram_allocation, 
                            mock_adjust_disk_io_priority, mock_adjust_network_bandwidth, 
                            mock_adjust_gpu_power_limit, mock_adjust_cpu_frequency, shared_resource_manager):
    """Kiểm thử phương thức execute_adjustments với các điều chỉnh hợp lệ."""
    adjustments = {
        'cpu_freq': 2500,
        'gpu_power_limit': 200,
        'network_bandwidth_limit_mbps': 80.0,
        'ionice_class': 2,
        'drop_caches': True,
        'unknown_adjust': 999
    }
    process = MagicMock()
    process.pid = 2323
    process.name = "execute_adjust_process"

    shared_resource_manager.execute_adjustments(adjustments, process)

    mock_adjust_cpu_frequency.assert_called_once_with(process.pid, 2500, process.name)
    mock_adjust_gpu_power_limit.assert_called_once_with(process.pid, 200, process.name)
    mock_adjust_network_bandwidth.assert_called_once_with(process, 80.0)
    mock_adjust_disk_io_priority.assert_called_once_with(process.pid, 2, process.name)
    mock_drop_caches.assert_called_once()
    # unknown_adjust should trigger a warning
    shared_resource_manager.logger.warning.assert_called_with("Không nhận dạng được điều chỉnh: unknown_adjust")

@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_cpu_frequency', side_effect=Exception("Adjustment Error"))
def test_execute_adjustments_exception(mock_adjust_cpu_freq, shared_resource_manager):
    """Kiểm thử phương thức execute_adjustments khi có ngoại lệ trong điều chỉnh."""
    adjustments = {
        'cpu_freq': 2500
    }
    process = MagicMock()
    process.pid = 2323
    process.name = "execute_adjust_exception_process"

    shared_resource_manager.execute_adjustments(adjustments, process)

    mock_adjust_cpu_freq.assert_called_once_with(process.pid, 2500, process.name)
    shared_resource_manager.logger.error.assert_called_with(
        f"Lỗi khi thực hiện các điều chỉnh cloaking cho tiến trình {process.name} (PID: {process.pid}): Adjustment Error"
    )

@patch('mining_environment.scripts.resource_manager.CloakStrategyFactory.create_strategy')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.execute_adjustments')
def test_apply_cloak_strategy_partial_adjustments(mock_execute_adjustments, mock_create_strategy, shared_resource_manager):
    """Kiểm thử phương thức apply_cloak_strategy với một số điều chỉnh."""
    strategy_name = "partial_strategy"
    process = MagicMock()
    process.pid = 2424
    process.name = "partial_cloak_process"

    mock_strategy = MagicMock()
    mock_strategy.apply.return_value = {
        'cpu_freq': 2600,
        'gpu_power_limit': 220
    }
    mock_create_strategy.return_value = mock_strategy

    # Giả lập các phương thức get_current_*
    with patch.object(shared_resource_manager, 'get_current_cpu_frequency', return_value=3000):
        with patch.object(shared_resource_manager, 'get_current_gpu_power_limit', return_value=250):

            shared_resource_manager.apply_cloak_strategy(strategy_name, process)

    mock_create_strategy.assert_called_once_with(strategy_name, shared_resource_manager.config, shared_resource_manager.logger, shared_resource_manager.is_gpu_initialized())
    mock_strategy.apply.assert_called_once_with(process)
    shared_resource_manager.logger.info.assert_called_with(
        f"Áp dụng điều chỉnh {strategy_name} cho tiến trình {process.name} (PID: {process.pid}): {{'cpu_freq': 2600, 'gpu_power_limit': 220}}"
    )
    mock_execute_adjustments.assert_called_once_with(mock_strategy.apply.return_value, process)
    assert shared_resource_manager.original_resource_limits[process.pid] == {
        'cpu_freq': 3000,
        'gpu_power_limit': 250
    }


@pytest.fixture
def mock_logger():
    """Fixture để tạo mock logger."""
    return MagicMock()

# ----------------------------------  Lớp ResourceManager ------------------------------------------


# @pytest.fixture
# def resource_manager(mock_logger):
#     """Fixture để tạo instance của ResourceManager với các tham số mock."""
#     config = {
#         "processes": {
#             "CPU": "cpu_miner",
#             "GPU": "gpu_miner"
#         },
#         "process_priority_map": {
#             "cpu_miner": 2,
#             "gpu_miner": 3
#         },
#         "monitoring_parameters": {
#             "temperature_monitoring_interval_seconds": 10,
#             "power_monitoring_interval_seconds": 10,
#             "azure_monitor_interval_seconds": 300,
#             "optimization_interval_seconds": 30
#         },
#         "temperature_limits": {
#             "cpu_max_celsius": 75,
#             "gpu_max_celsius": 85
#         },
#         "power_limits": {
#             "per_device_power_watts": {
#                 "cpu": 150,
#                 "gpu": 300
#             }
#         },
#         "resource_allocation": {
#             "ram": {
#                 "max_allocation_mb": 2048
#             },
#             "network": {
#                 "bandwidth_limit_mbps": 100
#             },
#             "cache": {
#                 "limit_percent": 50
#             },
#             "gpu": {
#                 "max_usage_percent": [50, 75, 100]
#             },
#             "disk_io": {
#                 "min_limit_mbps": 10,
#                 "max_limit_mbps": 100
#             }
#         },
#         "network_interface": "eth0"
#     }
#     model_path = Path("/path/to/model.pt")
#     return ResourceManager(config, model_path, mock_logger)

# ----------------------------
# Kiểm thử ResourceManager
# ----------------------------

@patch('mining_environment.scripts.resource_manager.ResourceManager.initialize_azure_clients')
@patch('mining_environment.scripts.resource_manager.ResourceManager.discover_azure_resources')
@patch('mining_environment.scripts.resource_manager.ResourceManager.initialize_threads')
@patch('mining_environment.scripts.resource_manager.ResourceManager.load_model', return_value=(MagicMock(), MagicMock()))
@patch('mining_environment.scripts.resource_manager.SharedResourceManager', autospec=True)
def test_resource_manager_initialization(mock_shared_resource_manager_class, mock_load_model, mock_init_threads, mock_discover_azure, mock_init_azure, resource_manager, mock_logger):
    """Kiểm thử khởi tạo ResourceManager."""
    assert resource_manager.config['processes']['CPU'] == "cpu_miner"
    assert resource_manager.config['process_priority_map']['gpu_miner'] == 3
    mock_load_model.assert_called_once_with(resource_manager.model_path)
    mock_init_azure.assert_called_once()
    mock_discover_azure.assert_called_once()
    mock_init_threads.assert_called_once()
    mock_shared_resource_manager_class.assert_called_once_with(resource_manager.config, resource_manager.logger)
    assert resource_manager.shared_resource_manager is not None

@patch('mining_environment.scripts.resource_manager.ResourceManager.discover_mining_processes')
@patch('mining_environment.scripts.resource_manager.ResourceManager.start_threads')
def test_resource_manager_start(mock_start_threads, mock_discover_mining_processes, resource_manager, mock_logger):
    """Kiểm thử phương thức start của ResourceManager."""
    resource_manager.start()
    mock_logger.info.assert_any_call("Bắt đầu ResourceManager...")
    mock_discover_mining_processes.assert_called_once()
    mock_start_threads.assert_called_once()
    mock_logger.info.assert_any_call("ResourceManager đã khởi động thành công.")

@patch('mining_environment.scripts.resource_manager.ResourceManager.shutdown_power_management')
@patch('mining_environment.scripts.resource_manager.ResourceManager.join_threads')
@patch('mining_environment.scripts.resource_manager.Event.set')
def test_resource_manager_stop(mock_event_set, mock_join_threads, mock_shutdown, resource_manager, mock_logger):
    """Kiểm thử phương thức stop của ResourceManager."""
    resource_manager.stop()
    mock_logger.info.assert_any_call("Dừng ResourceManager...")
    mock_event_set.assert_called_once()
    mock_join_threads.assert_called_once()
    mock_shutdown.assert_called_once()
    mock_logger.info.assert_any_call("ResourceManager đã dừng thành công.")

@patch('mining_environment.scripts.resource_manager.psutil.process_iter')
def test_discover_mining_processes(mock_process_iter, resource_manager, mock_logger):
    """Kiểm thử phương thức discover_mining_processes."""
    mock_proc1 = MagicMock()
    mock_proc1.info = {'pid': 101, 'name': 'cpu_miner'}
    mock_proc2 = MagicMock()
    mock_proc2.info = {'pid': 102, 'name': 'gpu_miner'}
    mock_process_iter.return_value = [mock_proc1, mock_proc2]
    
    with patch.object(resource_manager, 'get_process_priority', side_effect=lambda name: resource_manager.config['process_priority_map'][name.lower()]):
        resource_manager.discover_mining_processes()
    
    assert len(resource_manager.mining_processes) == 2
    assert resource_manager.mining_processes[0].pid == 101
    assert resource_manager.mining_processes[0].name == 'cpu_miner'
    assert resource_manager.mining_processes[0].priority == 2
    assert resource_manager.mining_processes[0].network_interface == "eth0"
    assert resource_manager.mining_processes[1].pid == 102
    assert resource_manager.mining_processes[1].name == 'gpu_miner'
    assert resource_manager.mining_processes[1].priority == 3
    assert resource_manager.mining_processes[1].network_interface == "eth0"
    mock_logger.info.assert_called_with(f"Khám phá 2 tiến trình khai thác.")

@patch('mining_environment.scripts.resource_manager.SharedResourceManager.is_gpu_initialized', return_value=True)
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_cpu_threads')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_gpu_usage')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_ram_allocation')
def test_allocate_resources_with_priority(mock_adjust_ram, mock_adjust_gpu_usage, mock_adjust_cpu_threads, mock_is_gpu_initialized, resource_manager, mock_logger):
    """Kiểm thử phương thức allocate_resources_with_priority."""
    # Giả lập các tiến trình với ưu tiên khác nhau
    process1 = MagicMock()
    process1.priority = 3
    process1.pid = 201
    process1.name = "gpu_miner"
    
    process2 = MagicMock()
    process2.priority = 2
    process2.pid = 202
    process2.name = "cpu_miner"
    
    resource_manager.mining_processes = [process1, process2]
    
    resource_manager.allocate_resources_with_priority()
    
    # Tổng số lõi CPU là giả lập thông qua psutil.cpu_count
    with patch('mining_environment.scripts.resource_manager.psutil.cpu_count', return_value=8):
        resource_manager.allocate_resources_with_priority()
    
    # Kiểm tra các gọi hàm điều chỉnh
    mock_adjust_cpu_threads.assert_any_call(201, 3, "gpu_miner")
    mock_adjust_gpu_usage.assert_any_call(process1, [])
    mock_adjust_ram.assert_any_call(201, 2048, "gpu_miner")
    
    mock_adjust_cpu_threads.assert_any_call(202, 2, "cpu_miner")
    mock_adjust_ram.assert_any_call(202, 2048, "cpu_miner")
    
    mock_logger.info.assert_any_call("Không còn lõi CPU để phân bổ cho tiến trình gpu_miner (PID: 201).")

@patch('mining_environment.scripts.resource_manager.temperature_monitor.get_cpu_temperature')
@patch('mining_environment.scripts.resource_manager.temperature_monitor.get_gpu_temperature')
def test_check_temperature_and_enqueue(mock_get_gpu_temp, mock_get_cpu_temp, resource_manager, mock_logger):
    """Kiểm thử phương thức check_temperature_and_enqueue."""
    process = MagicMock()
    process.pid = 303
    process.name = "test_process"
    
    mock_get_cpu_temp.return_value = 80
    mock_get_gpu_temp.return_value = 90
    
    resource_manager.shared_resource_manager.is_gpu_initialized.return_value = True
    
    with patch.object(resource_manager.resource_adjustment_queue, 'put') as mock_queue_put:
        resource_manager.check_temperature_and_enqueue(process, 75, 85)
    
        # Nhiệt độ CPU và GPU vượt ngưỡng
        adjustment_task = {
            'type': 'monitoring',
            'process': process,
            'adjustments': {
                'cpu_cloak': True,
                'gpu_cloak': True
            }
        }
        mock_queue_put.assert_called_once_with((2, adjustment_task))
        mock_logger.warning.assert_any_call("Nhiệt độ CPU 80°C của tiến trình test_process (PID: 303) vượt quá 75°C.")
        mock_logger.warning.assert_any_call("Nhiệt độ GPU 90°C của tiến trình test_process (PID: 303) vượt quá 85°C.")

@patch('mining_environment.scripts.resource_manager.get_cpu_power', return_value=160)
@patch('mining_environment.scripts.resource_manager.get_gpu_power', return_value=350)
def test_check_power_and_enqueue(mock_get_gpu_power, mock_get_cpu_power, resource_manager, mock_logger):
    """Kiểm thử phương thức check_power_and_enqueue."""
    process = MagicMock()
    process.pid = 404
    process.name = "power_process"
    
    resource_manager.shared_resource_manager.is_gpu_initialized.return_value = True
    
    with patch.object(resource_manager.resource_adjustment_queue, 'put') as mock_queue_put:
        resource_manager.check_power_and_enqueue(process, 150, 300)
    
        # Công suất CPU và GPU vượt ngưỡng
        adjustment_task = {
            'type': 'monitoring',
            'process': process,
            'adjustments': {
                'cpu_cloak': True,
                'gpu_cloak': True
            }
        }
        mock_queue_put.assert_called_once_with((2, adjustment_task))
        mock_logger.warning.assert_any_call("Công suất CPU 160W của tiến trình power_process (PID: 404) vượt quá 150W.")
        mock_logger.warning.assert_any_call("Công suất GPU 350W của tiến trình power_process (PID: 404) vượt quá 300W.")

@patch('mining_environment.scripts.resource_manager.time.time', return_value=1000)
def test_should_collect_azure_monitor_data_first_call(mock_time, resource_manager):
    """Kiểm thử phương thức should_collect_azure_monitor_data lần đầu tiên."""
    assert resource_manager.should_collect_azure_monitor_data() == True
    assert resource_manager._last_azure_monitor_time == 1000

@patch('mining_environment.scripts.resource_manager.time.time', side_effect=[1000, 1000 + 100, 1000 + 301])
def test_should_collect_azure_monitor_data(mock_time, resource_manager):
    """Kiểm thử phương thức should_collect_azure_monitor_data với các lần gọi khác nhau."""
    # Lần đầu tiên
    assert resource_manager.should_collect_azure_monitor_data() == True
    assert resource_manager._last_azure_monitor_time == 1000
    
    # Lần thứ hai, chưa đủ interval
    assert resource_manager.should_collect_azure_monitor_data() == False
    
    # Lần thứ ba, đủ interval
    assert resource_manager.should_collect_azure_monitor_data() == True
    assert resource_manager._last_azure_monitor_time == 1000 + 301

@patch('mining_environment.scripts.resource_manager.AzureMonitorClient.get_metrics')
def test_collect_azure_monitor_data(mock_get_metrics, resource_manager, mock_logger):
    """Kiểm thử phương thức collect_azure_monitor_data."""
    # Giả lập các VM
    resource_manager.vms = [
        {'id': 'vm1', 'name': 'VM1'},
        {'id': 'vm2', 'name': 'VM2'}
    ]
    
    mock_get_metrics.side_effect = [
        {'Percentage CPU': 50, 'Available Memory Bytes': 4000000000},
        {'Percentage CPU': 60, 'Available Memory Bytes': 3500000000}
    ]
    
    resource_manager.collect_azure_monitor_data()
    
    # Kiểm tra gọi get_metrics cho từng VM
    mock_get_metrics.assert_any_call('vm1', ['Percentage CPU', 'Available Memory Bytes'])
    mock_get_metrics.assert_any_call('vm2', ['Percentage CPU', 'Available Memory Bytes'])
    assert mock_get_metrics.call_count == 2
    
    # Kiểm tra logger.info được gọi với các chỉ số thu thập
    mock_logger.info.assert_any_call("Thu thập chỉ số từ Azure Monitor cho VM VM1: {'Percentage CPU': 50, 'Available Memory Bytes': 4000000000}")
    mock_logger.info.assert_any_call("Thu thập chỉ số từ Azure Monitor cho VM VM2: {'Percentage CPU': 60, 'Available Memory Bytes': 3500000000}")

@patch('mining_environment.scripts.resource_manager.SharedResourceManager.apply_cloak_strategy')
def test_apply_monitoring_adjustments(mock_apply_cloak, resource_manager, mock_logger):
    """Kiểm thử phương thức apply_monitoring_adjustments."""
    adjustments = {
        'cpu_cloak': True,
        'gpu_cloak': True
    }
    process = MagicMock()
    process.name = "monitor_process"
    process.pid = 505
    
    resource_manager.shared_resource_manager.apply_cloak_strategy.return_value = None
    
    resource_manager.apply_monitoring_adjustments(adjustments, process)
    
    mock_apply_cloak.assert_any_call('cpu', process)
    mock_apply_cloak.assert_any_call('gpu', process)
    mock_logger.info.assert_called_with(f"Áp dụng điều chỉnh từ MonitorThread cho tiến trình {process.name} (PID: {process.pid}).")

@patch('mining_environment.scripts.resource_manager.SharedResourceManager.apply_cloak_strategy', side_effect=Exception("Cloak Strategy Error"))
def test_apply_monitoring_adjustments_exception(mock_apply_cloak, resource_manager, mock_logger):
    """Kiểm thử phương thức apply_monitoring_adjustments khi có ngoại lệ."""
    adjustments = {
        'cpu_cloak': True,
        'gpu_cloak': True
    }
    process = MagicMock()
    process.name = "monitor_process_exception"
    process.pid = 506
    
    resource_manager.apply_monitoring_adjustments(adjustments, process)
    
    mock_apply_cloak.assert_any_call('cpu', process)
    mock_apply_cloak.assert_any_call('gpu', process)
    mock_logger.error.assert_called_with(
        f"Lỗi khi áp dụng điều chỉnh từ MonitorThread cho tiến trình {process.name} (PID: {process.pid}): Cloak Strategy Error"
    )

@patch('mining_environment.scripts.resource_manager.SharedResourceManager.apply_cloak_strategy')
@patch('mining_environment.scripts.resource_manager.ResourceManager.execute_adjustments')
def test_apply_recommended_action(mock_execute_adjustments, mock_apply_cloak, resource_manager, mock_logger):
    """Kiểm thử phương thức apply_recommended_action."""
    action = [4, 1024, 60.0, 70.0, 40.0, 30.0]
    process = MagicMock()
    process.pid = 606
    process.name = "ai_process"
    
    resource_manager.apply_recommended_action(action, process)
    
    # Kiểm tra các yêu cầu điều chỉnh được đặt vào hàng đợi
    expected_calls = [
        call((3, {
            'function': 'adjust_cpu_threads',
            'args': (606, 4, "ai_process")
        })),
        call((3, {
            'function': 'adjust_ram_allocation',
            'args': (606, 1024, "ai_process")
        })),
        call((3, {
            'function': 'adjust_gpu_usage',
            'args': (process, [60.0, 70.0, 40.0])
        })),
        call((3, {
            'function': 'adjust_disk_io_limit',
            'args': (process, 40.0)
        })),
        call((3, {
            'function': 'adjust_network_bandwidth',
            'args': (process, 30.0)
        })),
    ]
    resource_manager.resource_adjustment_queue.put.assert_has_calls(expected_calls, any_order=True)
    
    mock_apply_cloak.assert_called_once_with('cache', process)
    mock_logger.info.assert_called_with(
        f"Áp dụng thành công các điều chỉnh tài nguyên dựa trên AI cho tiến trình {process.name} (PID: {process.pid})."
    )

@patch('mining_environment.scripts.resource_manager.SharedResourceManager.apply_cloak_strategy', side_effect=Exception("AI Adjustment Error"))
@patch('mining_environment.scripts.resource_manager.ResourceManager.execute_adjustments')
def test_apply_recommended_action_exception(mock_execute_adjustments, mock_apply_cloak, resource_manager, mock_logger):
    """Kiểm thử phương thức apply_recommended_action khi có ngoại lệ."""
    action = [4, 1024, 60.0, 70.0, 40.0, 30.0]
    process = MagicMock()
    process.pid = 606
    process.name = "ai_process_exception"
    
    resource_manager.apply_recommended_action(action, process)
    
    # Kiểm tra các yêu cầu điều chỉnh được đặt vào hàng đợi
    expected_calls = [
        call((3, {
            'function': 'adjust_cpu_threads',
            'args': (606, 4, "ai_process_exception")
        })),
        call((3, {
            'function': 'adjust_ram_allocation',
            'args': (606, 1024, "ai_process_exception")
        })),
        call((3, {
            'function': 'adjust_gpu_usage',
            'args': (process, [60.0, 70.0, 40.0])
        })),
        call((3, {
            'function': 'adjust_disk_io_limit',
            'args': (process, 40.0)
        })),
        call((3, {
            'function': 'adjust_network_bandwidth',
            'args': (process, 30.0)
        })),
    ]
    resource_manager.resource_adjustment_queue.put.assert_has_calls(expected_calls, any_order=True)
    
    mock_apply_cloak.assert_called_once_with('cache', process)
    mock_logger.error.assert_called_with(
        f"Lỗi khi áp dụng các điều chỉnh tài nguyên dựa trên AI cho tiến trình {process.name} (PID: {process.pid}): AI Adjustment Error"
    )

@patch('mining_environment.scripts.resource_manager.shutdown_power_management')
def test_shutdown_power_management(mock_shutdown, resource_manager, mock_logger):
    """Kiểm thử phương thức shutdown_power_management."""
    resource_manager.shutdown_power_management()
    mock_shutdown.assert_called_once()
    mock_logger.info.assert_called_with("Đóng các dịch vụ quản lý công suất thành công.")

@patch('mining_environment.scripts.resource_manager.AzureMonitorClient.discover_resources', side_effect=[
    [{'id': 'vm1', 'name': 'VM1'}, {'id': 'vm2', 'name': 'VM2'}],
    [{'id': 'nw1', 'name': 'NetworkWatcher1'}],
    [{'id': 'nsg1', 'name': 'NSG1'}, {'id': 'nsg2', 'name': 'NSG2'}]
])
@patch('mining_environment.scripts.resource_manager.AzureTrafficAnalyticsClient.get_traffic_workspace_ids', return_value=['ta1', 'ta2'])
@patch('mining_environment.scripts.resource_manager.AzureMLClient.discover_ml_clusters', return_value=['ml1', 'ml2', 'ml3'])
def test_discover_azure_resources(mock_discover_ml_clusters, mock_get_traffic_workspace_ids, mock_discover_resources, resource_manager, mock_logger):
    """Kiểm thử phương thức discover_azure_resources."""
    resource_manager.discover_azure_resources()
    
    # Kiểm tra gọi phương thức discover_resources cho từng loại tài nguyên
    assert resource_manager.vms == [{'id': 'vm1', 'name': 'VM1'}, {'id': 'vm2', 'name': 'VM2'}]
    assert resource_manager.network_watchers == [{'id': 'nw1', 'name': 'NetworkWatcher1'}]
    assert resource_manager.nsgs == [{'id': 'nsg1', 'name': 'NSG1'}, {'id': 'nsg2', 'name': 'NSG2'}]
    assert resource_manager.traffic_analytics_workspaces == ['ta1', 'ta2']
    assert resource_manager.ml_clusters == ['ml1', 'ml2', 'ml3']
    
    # Kiểm tra logger.info được gọi đúng số lần
    assert mock_logger.info.call_count == 5
    mock_logger.info.assert_any_call("Khám phá 2 Máy ảo.")
    mock_logger.info.assert_any_call("Khám phá 1 Network Watchers.")
    mock_logger.info.assert_any_call("Khám phá 2 Network Security Groups.")
    mock_logger.info.assert_any_call("Khám phá 2 Traffic Analytics Workspaces.")
    mock_logger.info.assert_any_call("Khám phá 3 Azure ML Clusters.")

@patch('mining_environment.scripts.resource_manager.Thread.start')
def test_initialize_threads_and_start_threads(mock_thread_start, resource_manager):
    """Kiểm thử phương thức initialize_threads và start_threads."""
    # Kiểm tra initialize_threads đã khởi tạo các luồng
    assert resource_manager.monitor_thread.name == "MonitorThread"
    assert resource_manager.optimization_thread.name == "OptimizationThread"
    assert resource_manager.cloaking_thread.name == "CloakingThread"
    assert resource_manager.resource_adjustment_thread.name == "ResourceAdjustmentThread"
    
    # Kiểm tra start_threads đã gọi start trên từng luồng
    resource_manager.start_threads()
    assert mock_thread_start.call_count == 4
    mock_thread_start.assert_has_calls([
        call(),
        call(),
        call(),
        call()
    ])

@patch('mining_environment.scripts.resource_manager.ResourceManager.monitor_and_adjust')
@patch('mining_environment.scripts.resource_manager.ResourceManager.optimize_resources')
@patch('mining_environment.scripts.resource_manager.ResourceManager.process_cloaking_requests')
@patch('mining_environment.scripts.resource_manager.ResourceManager.resource_adjustment_handler')
def test_initialize_threads(resource_manager, mock_resource_adjustment_handler, mock_process_cloaking_requests, mock_optimize_resources, mock_monitor_and_adjust):
    """Kiểm thử khởi tạo các luồng trong initialize_threads."""
    resource_manager.initialize_threads()
    
    assert resource_manager.monitor_thread.target == resource_manager.monitor_and_adjust
    assert resource_manager.optimization_thread.target == resource_manager.optimize_resources
    assert resource_manager.cloaking_thread.target == resource_manager.process_cloaking_requests
    assert resource_manager.resource_adjustment_thread.target == resource_manager.resource_adjustment_handler

@patch('mining_environment.scripts.resource_manager.ResourceManager.monitor_and_adjust')
@patch('mining_environment.scripts.resource_manager.ResourceManager.optimize_resources')
@patch('mining_environment.scripts.resource_manager.ResourceManager.process_cloaking_requests')
@patch('mining_environment.scripts.resource_manager.ResourceManager.resource_adjustment_handler')
def test_threads_execution(resource_manager, mock_resource_adjustment_handler, mock_process_cloaking_requests, mock_optimize_resources, mock_monitor_and_adjust):
    """Kiểm thử việc các luồng thực thi đúng phương thức."""
    resource_manager.start_threads()
    
    mock_monitor_and_adjust.assert_called_once()
    mock_optimize_resources.assert_called_once()
    mock_process_cloaking_requests.assert_called_once()
    mock_resource_adjustment_handler.assert_called_once()

@patch('mining_environment.scripts.resource_manager.ResourceManager.monitor_and_adjust')
@patch('mining_environment.scripts.resource_manager.ResourceManager.optimize_resources')
@patch('mining_environment.scripts.resource_manager.ResourceManager.process_cloaking_requests')
@patch('mining_environment.scripts.resource_manager.ResourceManager.resource_adjustment_handler')
def test_join_threads(resource_manager, mock_resource_adjustment_handler, mock_process_cloaking_requests, mock_optimize_resources, mock_monitor_and_adjust):
    """Kiểm thử phương thức join_threads."""
    resource_manager.join_threads()
    
    mock_monitor_and_adjust.assert_not_called()
    mock_optimize_resources.assert_not_called()
    mock_process_cloaking_requests.assert_not_called()
    mock_resource_adjustment_handler.assert_not_called()

@patch('mining_environment.scripts.resource_manager.ResourceManager.collect_metrics')
@patch('mining_environment.scripts.resource_manager.ResourceManager.prepare_input_features')
@patch('mining_environment.scripts.resource_manager.torch.tensor')
@patch('mining_environment.scripts.resource_manager.ResourceManager.resource_optimization_model')
def test_optimize_resources(mock_model, mock_tensor, mock_prepare_features, mock_collect_metrics, resource_manager, mock_logger):
    """Kiểm thử phương thức optimize_resources."""
    mock_model_instance = MagicMock()
    mock_model.return_value = mock_model_instance
    mock_predict = MagicMock()
    mock_predict.squeeze.return_value = MagicMock(cpu=lambda: MagicMock(numpy=lambda: [1, 2, 3]))
    mock_model_instance.__call__.return_value = mock_predict
    
    process = MagicMock()
    process.pid = 1010
    process.name = "optimize_process"
    resource_manager.mining_processes = [process]
    
    mock_collect_metrics.return_value = {
        'cpu_usage_percent': 50,
        'memory_usage_mb': 1024,
        'gpu_usage_percent': 60,
        'disk_io_mbps': 30.0,
        'network_bandwidth_mbps': 100,
        'cache_limit_percent': 50
    }
    mock_prepare_features.return_value = [50, 1024, 60, 30.0, 100, 50]
    mock_tensor_instance = MagicMock()
    mock_tensor.return_value = mock_tensor_instance
    mock_tensor_instance.to.return_value = mock_tensor_instance
    mock_tensor_instance.unsqueeze.return_value = mock_tensor_instance
    mock_predict.squeeze.return_value.cpu.return_value.numpy.return_value = [1, 2, 3]
    
    with patch.object(resource_manager.resource_adjustment_queue, 'put') as mock_queue_put:
        resource_manager.optimize_resources()
    
        mock_collect_metrics.assert_called_once_with(process)
        mock_prepare_features.assert_called_once_with(mock_collect_metrics.return_value)
        mock_tensor.assert_called_once_with([50, 1024, 60, 30.0, 100, 50], dtype=torch.float32)
        mock_tensor_instance.to.assert_called_once_with(resource_manager.resource_optimization_device)
        mock_tensor_instance.unsqueeze.assert_called_once_with(0)
        mock_model_instance.__call__.assert_called_once_with(mock_tensor_instance)
        mock_predict.squeeze.assert_called_once_with(0)
        mock_predict.squeeze.return_value.cpu.return_value.numpy.assert_called_once()
        
        # Kiểm tra yêu cầu điều chỉnh được đặt vào hàng đợi
        adjustment_task = {
            'type': 'optimization',
            'process': process,
            'action': [1, 2, 3]
        }
        mock_queue_put.assert_called_once_with((2, adjustment_task))
        mock_logger.debug.assert_called_with(f"Mô hình AI đề xuất hành động cho tiến trình {process.name} (PID: {process.pid}): [1, 2, 3]")
    
@patch('mining_environment.scripts.resource_manager.ResourceManager.execute_adjustment_task')
def test_resource_adjustment_handler(mock_execute_adjustment_task, resource_manager, mock_logger):
    """Kiểm thử phương thức resource_adjustment_handler."""
    adjustment_task = {
        'type': 'optimization',
        'process': MagicMock(),
        'action': [1, 2, 3]
    }
    
    with patch.object(resource_manager.resource_adjustment_queue, 'get', return_value=(2, adjustment_task)):
        with patch.object(resource_manager.resource_adjustment_queue, 'task_done') as mock_task_done:
            with patch.object(resource_manager.stop_event, 'is_set', return_value=False):
                with patch('time.sleep', return_value=None):
                    # Chạy một lần để xử lý nhiệm vụ
                    resource_manager.resource_adjustment_handler()
                    mock_execute_adjustment_task.assert_called_once_with(adjustment_task)
                    mock_task_done.assert_called_once()

@patch('mining_environment.scripts.resource_manager.ResourceManager.execute_adjustment_task')
def test_resource_adjustment_handler_empty_queue(mock_execute_adjustment_task, resource_manager, mock_logger):
    """Kiểm thử phương thức resource_adjustment_handler khi hàng đợi trống."""
    with patch.object(resource_manager.resource_adjustment_queue, 'get', side_effect=Empty):
        with patch.object(resource_manager.resource_adjustment_queue, 'task_done') as mock_task_done:
            with patch.object(resource_manager.stop_event, 'is_set', return_value=False):
                with patch('time.sleep', return_value=None):
                    # Chạy một lần khi hàng đợi trống
                    resource_manager.resource_adjustment_handler()
                    mock_execute_adjustment_task.assert_not_called()
                    mock_task_done.assert_not_called()

@patch('mining_environment.scripts.resource_manager.ResourceManager.shared_resource_manager.apply_cloak_strategy')
def test_execute_adjustment_task_cloaking(mock_apply_cloak, resource_manager, mock_logger):
    """Kiểm thử phương thức execute_adjustment_task với nhiệm vụ 'cloaking'."""
    process = MagicMock()
    process.name = "cloaking_process"
    process.pid = 707
    
    adjustment_task = {
        'type': 'cloaking',
        'process': process,
        'strategies': ['cpu', 'gpu']
    }
    
    resource_manager.execute_adjustment_task(adjustment_task)
    
    mock_apply_cloak.assert_any_call('cpu', process)
    mock_apply_cloak.assert_any_call('gpu', process)
    mock_logger.info.assert_called_with(f"Hoàn thành cloaking cho tiến trình {process.name} (PID: {process.pid}).")

@patch('mining_environment.scripts.resource_manager.ResourceManager.shared_resource_manager.apply_cloak_strategy', side_effect=Exception("Cloaking Error"))
def test_execute_adjustment_task_cloaking_exception(mock_apply_cloak, resource_manager, mock_logger):
    """Kiểm thử phương thức execute_adjustment_task với nhiệm vụ 'cloaking' khi có ngoại lệ."""
    process = MagicMock()
    process.name = "cloaking_process_exception"
    process.pid = 708
    
    adjustment_task = {
        'type': 'cloaking',
        'process': process,
        'strategies': ['cpu', 'gpu']
    }
    
    resource_manager.execute_adjustment_task(adjustment_task)
    
    mock_apply_cloak.assert_any_call('cpu', process)
    mock_apply_cloak.assert_any_call('gpu', process)
    mock_logger.error.assert_called_with(
        f"Lỗi khi áp dụng chiến lược cloaking cpu cho tiến trình {process.name} (PID: {process.pid}): Cloaking Error"
    )

@patch('mining_environment.scripts.resource_manager.ResourceManager.shared_resource_manager.apply_recommended_action')
def test_execute_adjustment_task_optimization(mock_apply_recommended_action, resource_manager, mock_logger):
    """Kiểm thử phương thức execute_adjustment_task với nhiệm vụ 'optimization'."""
    process = MagicMock()
    process.name = "optimization_process"
    process.pid = 809
    
    adjustment_task = {
        'type': 'optimization',
        'process': process,
        'action': [4, 2048, 70.0, 80.0, 50.0, 60.0]
    }
    
    resource_manager.execute_adjustment_task(adjustment_task)
    
    mock_apply_recommended_action.assert_called_once_with([4, 2048, 70.0, 80.0, 50.0, 60.0], process)
    mock_logger.info.assert_called_with(f"Áp dụng thành công các điều chỉnh tài nguyên dựa trên AI cho tiến trình {process.name} (PID: {process.pid}).")

@patch('mining_environment.scripts.resource_manager.ResourceManager.shared_resource_manager.apply_recommended_action', side_effect=Exception("Optimization Error"))
def test_execute_adjustment_task_optimization_exception(mock_apply_recommended_action, resource_manager, mock_logger):
    """Kiểm thử phương thức execute_adjustment_task với nhiệm vụ 'optimization' khi có ngoại lệ."""
    process = MagicMock()
    process.name = "optimization_process_exception"
    process.pid = 810
    
    adjustment_task = {
        'type': 'optimization',
        'process': process,
        'action': [4, 2048, 70.0, 80.0, 50.0, 60.0]
    }
    
    resource_manager.execute_adjustment_task(adjustment_task)
    
    mock_apply_recommended_action.assert_called_once_with([4, 2048, 70.0, 80.0, 50.0, 60.0], process)
    mock_logger.error.assert_called_with(
        f"Lỗi khi áp dụng các điều chỉnh tài nguyên dựa trên AI cho tiến trình {process.name} (PID: {process.pid}): Optimization Error"
    )

@patch('mining_environment.scripts.resource_manager.ResourceManager.shared_resource_manager.restore_resources')
def test_execute_adjustment_task_restore(mock_restore_resources, resource_manager, mock_logger):
    """Kiểm thử phương thức execute_adjustment_task với nhiệm vụ 'restore'."""
    process = MagicMock()
    process.name = "restore_process"
    process.pid = 911
    
    adjustment_task = {
        'type': 'restore',
        'process': process
    }
    
    resource_manager.execute_adjustment_task(adjustment_task)
    
    mock_restore_resources.assert_called_once_with(process)
    mock_logger.info.assert_called_with(f"Đã khôi phục tài nguyên cho tiến trình {process.name} (PID: {process.pid}).")

@patch('mining_environment.scripts.resource_manager.ResourceManager.shared_resource_manager.restore_resources', side_effect=Exception("Restore Error"))
def test_execute_adjustment_task_restore_exception(mock_restore_resources, resource_manager, mock_logger):
    """Kiểm thử phương thức execute_adjustment_task với nhiệm vụ 'restore' khi có ngoại lệ."""
    process = MagicMock()
    process.name = "restore_process_exception"
    process.pid = 912
    
    adjustment_task = {
        'type': 'restore',
        'process': process
    }
    
    resource_manager.execute_adjustment_task(adjustment_task)
    
    mock_restore_resources.assert_called_once_with(process)
    mock_logger.error.assert_called_with(
        f"Lỗi khi khôi phục tài nguyên cho tiến trình {process.name} (PID: {process.pid}): Restore Error"
    )

@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_cpu_threads')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_ram_allocation')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_gpu_usage')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_disk_io_limit')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_network_bandwidth')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.apply_cloak_strategy')
def test_apply_recommended_action(mock_apply_cloak_strategy, mock_adjust_network_bw, mock_adjust_disk_io, mock_adjust_gpu_usage, mock_adjust_ram_allocation, mock_adjust_cpu_threads, resource_manager, mock_logger):
    """Kiểm thử phương thức apply_recommended_action."""
    action = [4, 2048, 60.0, 70.0, 40.0, 50.0]
    process = MagicMock()
    process.pid = 1011
    process.name = "ai_process"
    
    resource_manager.apply_recommended_action(action, process)
    
    # Kiểm tra các yêu cầu điều chỉnh được đặt vào hàng đợi
    expected_calls = [
        call((3, {
            'function': 'adjust_cpu_threads',
            'args': (1011, 4, "ai_process")
        })),
        call((3, {
            'function': 'adjust_ram_allocation',
            'args': (1011, 2048, "ai_process")
        })),
        call((3, {
            'function': 'adjust_gpu_usage',
            'args': (process, [60.0, 70.0, 40.0])
        })),
        call((3, {
            'function': 'adjust_disk_io_limit',
            'args': (process, 40.0)
        })),
        call((3, {
            'function': 'adjust_network_bandwidth',
            'args': (process, 50.0)
        })),
    ]
    resource_manager.resource_adjustment_queue.put.assert_has_calls(expected_calls, any_order=True)
    
    # Kiểm tra áp dụng cloaking cache
    mock_apply_cloak_strategy.assert_called_once_with('cache', process)
    
    # Kiểm tra logger
    mock_logger.info.assert_called_with(
        f"Áp dụng thành công các điều chỉnh tài nguyên dựa trên AI cho tiến trình {process.name} (PID: {process.pid})."
    )

@patch('mining_environment.scripts.resource_manager.SharedResourceManager.apply_cloak_strategy', side_effect=Exception("AI Adjustment Error"))
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_cpu_threads')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_ram_allocation')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_gpu_usage')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_disk_io_limit')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_network_bandwidth')
def test_apply_recommended_action_exception(mock_adjust_network_bw, mock_adjust_disk_io, mock_adjust_gpu_usage, mock_adjust_ram_allocation, mock_adjust_cpu_threads, mock_apply_cloak_strategy, resource_manager, mock_logger):
    """Kiểm thử phương thức apply_recommended_action khi có ngoại lệ."""
    action = [4, 2048, 60.0, 70.0, 40.0, 50.0]
    process = MagicMock()
    process.pid = 1012
    process.name = "ai_process_exception"
    
    resource_manager.apply_recommended_action(action, process)
    
    # Kiểm tra các yêu cầu điều chỉnh được đặt vào hàng đợi
    expected_calls = [
        call((3, {
            'function': 'adjust_cpu_threads',
            'args': (1012, 4, "ai_process_exception")
        })),
        call((3, {
            'function': 'adjust_ram_allocation',
            'args': (1012, 2048, "ai_process_exception")
        })),
        call((3, {
            'function': 'adjust_gpu_usage',
            'args': (process, [60.0, 70.0, 40.0])
        })),
        call((3, {
            'function': 'adjust_disk_io_limit',
            'args': (process, 40.0)
        })),
        call((3, {
            'function': 'adjust_network_bandwidth',
            'args': (process, 50.0)
        })),
    ]
    resource_manager.resource_adjustment_queue.put.assert_has_calls(expected_calls, any_order=True)
    
    # Kiểm tra áp dụng cloaking cache và xử lý ngoại lệ
    mock_apply_cloak_strategy.assert_called_once_with('cache', process)
    mock_logger.error.assert_called_with(
        f"Lỗi khi áp dụng các điều chỉnh tài nguyên dựa trên AI cho tiến trình {process.name} (PID: {process.pid}): AI Adjustment Error"
    )

@patch('mining_environment.scripts.resource_manager.SharedResourceManager.restore_resources')
def test_restore_resources_success(mock_restore_resources, resource_manager, mock_logger):
    """Kiểm thử phương thức restore_resources trong trường hợp thành công."""
    process = MagicMock()
    process.pid = 1111
    process.name = "restore_process"
    
    # Giả lập original_resource_limits
    resource_manager.shared_resource_manager.original_resource_limits = {
        process.pid: {
            'cpu_freq': 3000,
            'cpu_threads': 4,
            'ram_allocation_mb': 2048,
            'gpu_power_limit': 250,
            'ionice_class': 2,
            'network_bandwidth_limit_mbps': 100.0
        }
    }
    
    resource_manager.shared_resource_manager.restore_resources = MagicMock()
    
    resource_manager.shared_resource_manager.restore_resources.return_value = None
    
    resource_manager.shared_resource_manager.restore_resources = mock_restore_resources
    
    resource_manager.shared_resource_manager.restore_resources.return_value = None
    
    resource_manager.shared_resource_manager.restore_resources = mock_restore_resources
    
    resource_manager.restore_resources(process)
    
    mock_restore_resources.assert_called_once_with(process)
    mock_logger.info.assert_called_with(f"Đã khôi phục tài nguyên cho tiến trình {process.name} (PID: {process.pid}).")

@patch('mining_environment.scripts.resource_manager.SharedResourceManager.restore_resources', side_effect=Exception("Restore Error"))
def test_restore_resources_exception(mock_restore_resources, resource_manager, mock_logger):
    """Kiểm thử phương thức restore_resources khi có ngoại lệ."""
    process = MagicMock()
    process.pid = 1112
    process.name = "restore_process_exception"
    
    # Giả lập original_resource_limits
    resource_manager.shared_resource_manager.original_resource_limits = {
        process.pid: {
            'cpu_freq': 3000,
            'cpu_threads': 4,
            'ram_allocation_mb': 2048,
            'gpu_power_limit': 250,
            'ionice_class': 2,
            'network_bandwidth_limit_mbps': 100.0
        }
    }
    
    resource_manager.restore_resources(process)
    
    mock_restore_resources.assert_called_once_with(process)
    mock_logger.error.assert_called_with(
        f"Lỗi khi khôi phục tài nguyên cho tiến trình {process.name} (PID: {process.pid}): Restore Error"
    )

@patch('mining_environment.scripts.resource_manager.SharedResourceManager.get_current_cpu_frequency', return_value=3000)
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.get_current_gpu_power_limit', return_value=250)
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.get_current_network_bandwidth_limit', return_value=100.0)
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.get_current_ionice_class', return_value=2)
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_cpu_frequency')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_cpu_threads')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_ram_allocation')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_gpu_power_limit')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_disk_io_priority')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_network_bandwidth')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.logger')
def test_restore_resources_full(mock_logger, mock_adjust_network_bw, mock_adjust_disk_io, mock_adjust_gpu_power, 
                                mock_adjust_ram, mock_adjust_cpu_threads, mock_adjust_cpu_freq, 
                                mock_get_ionice, mock_get_network_bw, mock_get_gpu_power, mock_get_cpu_freq, 
                                mock_restore_resources, resource_manager):
    """Kiểm thử phương thức restore_resources với toàn bộ các giới hạn tài nguyên."""
    process = MagicMock()
    process.pid = 1213
    process.name = "restore_full_process"
    
    # Giả lập original_resource_limits
    resource_manager.shared_resource_manager.original_resource_limits = {
        process.pid: {
            'cpu_freq': 3000,
            'cpu_threads': 4,
            'ram_allocation_mb': 2048,
            'gpu_power_limit': 250,
            'ionice_class': 2,
            'network_bandwidth_limit_mbps': 100.0
        }
    }
    
    resource_manager.shared_resource_manager.restore_resources = MagicMock()
    
    resource_manager.restore_resources(process)
    
    # Kiểm tra gọi các phương thức điều chỉnh
    mock_adjust_cpu_freq.assert_called_once_with(process.pid, 3000, process.name)
    mock_adjust_cpu_threads.assert_called_once_with(process.pid, 4, process.name)
    mock_adjust_ram.assert_called_once_with(process.pid, 2048, process.name)
    mock_adjust_gpu_power.assert_called_once_with(process.pid, 250, process.name)
    mock_adjust_disk_io.assert_called_once_with(process.pid, 2, process.name)
    mock_adjust_network_bw.assert_called_once_with(process, 100.0)
    
    # Kiểm tra log
    mock_logger.info.assert_any_call(f"Đã khôi phục tần số CPU về 3000MHz cho tiến trình {process.name} (PID: {process.pid}).")
    mock_logger.info.assert_any_call(f"Đã khôi phục số luồng CPU về 4 cho tiến trình {process.name} (PID: {process.pid}).")
    mock_logger.info.assert_any_call(f"Đã khôi phục giới hạn RAM về 2048MB cho tiến trình {process.name} (PID: {process.pid}).")
    mock_logger.info.assert_any_call(f"Đã khôi phục giới hạn công suất GPU về 250W cho tiến trình {process.name} (PID: {process.pid}).")
    mock_logger.info.assert_any_call(f"Đã khôi phục lớp ionice về 2 cho tiến trình {process.name} (PID: {process.pid}).")
    mock_logger.info.assert_any_call(f"Đã khôi phục giới hạn băng thông mạng về 100.0 Mbps cho tiến trình {process.name} (PID: {process.pid}).")
    mock_logger.info.assert_any_call(f"Đã khôi phục tất cả tài nguyên cho tiến trình {process.name} (PID: {process.pid}).")
    
    # Kiểm tra original_resource_limits đã được xóa
    assert process.pid not in resource_manager.shared_resource_manager.original_resource_limits

@patch('mining_environment.scripts.resource_manager.ResourceManager.SharedResourceManager.apply_cloak_strategy')
def test_execute_adjustments(mock_apply_cloak, resource_manager, mock_logger):
    """Kiểm thử phương thức execute_adjustments."""
    adjustments = {
        'cpu_freq': 2500,
        'gpu_power_limit': 200,
        'network_bandwidth_limit_mbps': 80.0,
        'ionice_class': 2,
        'drop_caches': True,
        'unknown_adjust': 999
    }
    process = MagicMock()
    process.pid = 1314
    process.name = "execute_adjust_process"
    
    resource_manager.execute_adjustments(adjustments, process)
    
    # Kiểm tra các gọi hàm điều chỉnh
    mock_apply_cloak.assert_any_call('cpu_freq', process)  # Chưa rõ cách mapping, cần xác nhận
    mock_apply_cloak.assert_any_call('gpu_power_limit', process)
    mock_apply_cloak.assert_any_call('network_bandwidth_limit_mbps', process)
    mock_apply_cloak.assert_any_call('ionice_class', process)
    mock_apply_cloak.assert_any_call('drop_caches', process)
    
    # Kiểm tra log warning cho unknown_adjust
    mock_logger.warning.assert_called_with("Không nhận dạng được điều chỉnh: unknown_adjust")

@patch('mining_environment.scripts.resource_manager.ResourceManager.SharedResourceManager.apply_cloak_strategy', side_effect=Exception("Adjustment Error"))
def test_execute_adjustments_exception(mock_apply_cloak, resource_manager, mock_logger):
    """Kiểm thử phương thức execute_adjustments khi có ngoại lệ."""
    adjustments = {
        'cpu_freq': 2500
    }
    process = MagicMock()
    process.pid = 1315
    process.name = "execute_adjust_exception_process"
    
    resource_manager.execute_adjustments(adjustments, process)
    
    mock_apply_cloak.assert_called_once_with('cpu_freq', process)
    mock_logger.error.assert_called_with(
        f"Lỗi khi thực hiện các điều chỉnh cloaking cho tiến trình {process.name} (PID: {process.pid}): Adjustment Error"
    )

@patch('mining_environment.scripts.resource_manager.SharedResourceManager.restore_resources')
def test_restore_resources_method(mock_restore_resources, resource_manager, mock_logger):
    """Kiểm thử phương thức restore_resources."""
    process = MagicMock()
    process.pid = 1415
    process.name = "restore_method_process"
    
    # Giả lập original_resource_limits
    resource_manager.shared_resource_manager.original_resource_limits = {
        process.pid: {
            'cpu_freq': 3000,
            'cpu_threads': 4,
            'ram_allocation_mb': 2048,
            'gpu_power_limit': 250,
            'ionice_class': 2,
            'network_bandwidth_limit_mbps': 100.0
        }
    }
    
    resource_manager.shared_resource_manager.restore_resources = mock_restore_resources
    
    resource_manager.restore_resources(process)
    
    mock_restore_resources.assert_called_once_with(process)
    mock_logger.info.assert_called_with(f"Đã khôi phục tài nguyên cho tiến trình {process.name} (PID: {process.pid}).")

@patch('mining_environment.scripts.resource_manager.SharedResourceManager.apply_cloak_strategy')
def test_execute_adjustment_task_unknown_type(mock_apply_cloak, resource_manager, mock_logger):
    """Kiểm thử phương thức execute_adjustment_task với loại nhiệm vụ không xác định."""
    adjustment_task = {
        'type': 'unknown_type',
        'process': MagicMock(),
        'action': None
    }
    
    resource_manager.execute_adjustment_task(adjustment_task)
    
    mock_apply_cloak.assert_not_called()
    mock_logger.warning.assert_called_with("Loại nhiệm vụ không xác định: unknown_type")

@patch('mining_environment.scripts.resource_manager.SharedResourceManager.apply_cloak_strategy')
def test_execute_adjustment_task_function_task(mock_apply_cloak, resource_manager, mock_logger):
    """Kiểm thử phương thức execute_adjustment_task với nhiệm vụ hàm."""
    adjustment_task = {
        'function': 'adjust_cpu_threads',
        'args': (1616, 4, "function_process")
    }
    
    resource_manager.execute_adjustment_task(adjustment_task)
    
    resource_manager.shared_resource_manager.adjust_cpu_threads.assert_called_once_with(1616, 4, "function_process")
    mock_logger.info.assert_not_called()

@patch('mining_environment.scripts.resource_manager.SharedResourceManager.adjust_cpu_threads', side_effect=Exception("Function Task Error"))
def test_execute_adjustment_task_function_task_exception(mock_adjust_cpu_threads, resource_manager, mock_logger):
    """Kiểm thử phương thức execute_adjustment_task với nhiệm vụ hàm khi có ngoại lệ."""
    adjustment_task = {
        'function': 'adjust_cpu_threads',
        'args': (1616, 4, "function_process_exception")
    }
    
    resource_manager.execute_adjustment_task(adjustment_task)
    
    resource_manager.shared_resource_manager.adjust_cpu_threads.assert_called_once_with(1616, 4, "function_process_exception")
    mock_logger.error.assert_called_with("Không tìm thấy hàm điều chỉnh tài nguyên: adjust_cpu_threads")  # Nếu exception ném ra trong adjust_cpu_threads, nó sẽ được log ở SharedResourceManager

# ----------------------------
# Kiểm thử các phương thức hỗ trợ
# ----------------------------

@patch('mining_environment.scripts.resource_manager.ResourceManager.should_collect_azure_monitor_data', return_value=True)
@patch('mining_environment.scripts.resource_manager.ResourceManager.collect_azure_monitor_data')
def test_monitor_and_adjust(mock_collect_azure, mock_should_collect, resource_manager, mock_logger):
    """Kiểm thử phương thức monitor_and_adjust."""
    process = MagicMock()
    process.update_resource_usage = MagicMock()
    resource_manager.mining_processes = [process]
    
    with patch.object(resource_manager, 'allocate_resources_with_priority') as mock_allocate:
        with patch.object(resource_manager, 'check_temperature_and_enqueue') as mock_check_temp:
            with patch.object(resource_manager, 'check_power_and_enqueue') as mock_check_power:
                with patch.object(resource_manager, 'sleep', return_value=None):
                    # Giả lập không có ngoại lệ
                    resource_manager.monitor_and_adjust()
                    
                    mock_allocate.assert_called_once()
                    mock_check_temp.assert_called_once_with(process, 75, 85)
                    mock_check_power.assert_called_once_with(process, 150, 300)
                    mock_collect_azure.assert_called_once()

@patch('mining_environment.scripts.resource_manager.ResourceManager.monitor_and_adjust')
@patch('mining_environment.scripts.resource_manager.ResourceManager.optimize_resources')
@patch('mining_environment.scripts.resource_manager.ResourceManager.process_cloaking_requests')
@patch('mining_environment.scripts.resource_manager.ResourceManager.resource_adjustment_handler')
def test_monitor_and_adjust_exception(mock_resource_adjustment_handler, mock_process_cloaking_requests, mock_optimize_resources, mock_monitor_and_adjust, resource_manager, mock_logger):
    """Kiểm thử phương thức monitor_and_adjust khi có ngoại lệ."""
    with patch.object(resource_manager, 'discover_mining_processes', side_effect=Exception("Monitor Error")):
        with patch.object(resource_manager, 'sleep', return_value=None):
            resource_manager.monitor_and_adjust()
            mock_logger.error.assert_called_with("Lỗi trong quá trình theo dõi và điều chỉnh: Monitor Error")

@patch('mining_environment.scripts.resource_manager.ResourceManager.optimize_resources')
def test_optimize_resources_thread(mock_optimize_resources, resource_manager, mock_logger):
    """Kiểm thử luồng optimize_resources."""
    with patch.object(resource_manager, 'stop_event', new=MagicMock(is_set=MagicMock(return_value=True))):
        with patch.object(resource_manager, 'sleep', return_value=None):
            resource_manager.optimize_resources()
            mock_logger.error.assert_not_called()  # Không có ngoại lệ

@patch('mining_environment.scripts.resource_manager.ResourceManager.monitor_and_adjust')
@patch('mining_environment.scripts.resource_manager.ResourceManager.optimize_resources')
@patch('mining_environment.scripts.resource_manager.ResourceManager.process_cloaking_requests')
@patch('mining_environment.scripts.resource_manager.ResourceManager.resource_adjustment_handler')
def test_process_cloaking_requests_thread(mock_resource_adjustment_handler, mock_process_cloaking_requests, mock_optimize_resources, mock_monitor_and_adjust, resource_manager, mock_logger):
    """Kiểm thử luồng process_cloaking_requests."""
    with patch.object(resource_manager.cloaking_request_queue, 'get', return_value=MagicMock()) as mock_queue_get:
        with patch.object(resource_manager.resource_adjustment_queue, 'put') as mock_queue_put:
            with patch.object(resource_manager.cloaking_request_queue, 'task_done') as mock_task_done:
                with patch.object(resource_manager.stop_event, 'is_set', return_value=False):
                    with patch('time.sleep', return_value=None):
                        # Chạy một lần để xử lý nhiệm vụ
                        resource_manager.process_cloaking_requests()
                        mock_queue_put.assert_called_once()
                        mock_task_done.assert_called_once()

@patch('mining_environment.scripts.resource_manager.ResourceManager.resource_adjustment_handler')
def test_resource_adjustment_handler_thread(mock_resource_adjustment_handler, resource_manager, mock_logger):
    """Kiểm thử luồng resource_adjustment_handler."""
    with patch.object(resource_manager.resource_adjustment_queue, 'get', return_value=(1, MagicMock())) as mock_queue_get:
        with patch.object(resource_manager.resource_adjustment_queue, 'task_done') as mock_task_done:
            with patch.object(resource_manager.stop_event, 'is_set', return_value=False):
                with patch('time.sleep', return_value=None):
                    resource_manager.resource_adjustment_handler()
                    mock_resource_adjustment_handler.assert_called_once()
                    mock_task_done.assert_called_once()

@patch('mining_environment.scripts.resource_manager.ResourceManager.SharedResourceManager.apply_cloak_strategy')
@patch('mining_environment.scripts.resource_manager.ResourceManager.execute_recommended_action')
def test_execute_adjustment_task_no_type(mock_execute_recommended_action, mock_apply_cloak, resource_manager, mock_logger):
    """Kiểm thử execute_adjustment_task với nhiệm vụ hàm."""
    adjustment_task = {
        'function': 'adjust_cpu_threads',
        'args': (1616, 4, "function_process")
    }
    
    resource_manager.execute_adjustment_task(adjustment_task)
    
    resource_manager.shared_resource_manager.adjust_cpu_threads.assert_called_once_with(1616, 4, "function_process")
    mock_logger.error.assert_not_called()

@patch('mining_environment.scripts.resource_manager.ResourceManager.SharedResourceManager.apply_cloak_strategy')
def test_execute_adjustment_task_unknown_function(mock_apply_cloak, resource_manager, mock_logger):
    """Kiểm thử execute_adjustment_task với chức năng không tồn tại."""
    adjustment_task = {
        'function': 'unknown_function',
        'args': ()
    }
    
    resource_manager.execute_adjustment_task(adjustment_task)
    
    mock_apply_cloak.assert_not_called()
    mock_logger.error.assert_called_with("Không tìm thấy hàm điều chỉnh tài nguyên: unknown_function")

@patch('mining_environment.scripts.resource_manager.ResourceManager.SharedResourceManager.apply_cloak_strategy')
def test_execute_adjustment_task_with_type_unknown(mock_apply_cloak, resource_manager, mock_logger):
    """Kiểm thử execute_adjustment_task với loại nhiệm vụ không xác định."""
    adjustment_task = {
        'type': 'unknown_type',
        'process': MagicMock(),
        'action': None
    }
    
    resource_manager.execute_adjustment_task(adjustment_task)
    
    mock_apply_cloak.assert_not_called()
    mock_logger.warning.assert_called_with("Loại nhiệm vụ không xác định: unknown_type")

@patch('mining_environment.scripts.resource_manager.SharedResourceManager.apply_cloak_strategy')
@patch('mining_environment.scripts.resource_manager.ResourceManager.apply_recommended_action')
def test_execute_adjustment_task_with_type_optimization(mock_apply_recommended_action, mock_apply_cloak, resource_manager, mock_logger):
    """Kiểm thử execute_adjustment_task với nhiệm vụ 'optimization'."""
    process = MagicMock()
    process.name = "optimization_process"
    process.pid = 818
    
    adjustment_task = {
        'type': 'optimization',
        'process': process,
        'action': [1, 2, 3]
    }
    
    resource_manager.execute_adjustment_task(adjustment_task)
    
    mock_apply_recommended_action.assert_called_once_with([1, 2, 3], process)
    mock_apply_cloak.assert_not_called()
    mock_logger.info.assert_called_with(f"Áp dụng thành công các điều chỉnh tài nguyên dựa trên AI cho tiến trình {process.name} (PID: {process.pid}).")

@patch('mining_environment.scripts.resource_manager.SharedResourceManager.apply_cloak_strategy')
@patch('mining_environment.scripts.resource_manager.ResourceManager.apply_monitoring_adjustments')
def test_execute_adjustment_task_with_type_monitoring(mock_apply_monitoring_adjustments, mock_apply_cloak, resource_manager, mock_logger):
    """Kiểm thử execute_adjustment_task với nhiệm vụ 'monitoring'."""
    process = MagicMock()
    process.name = "monitoring_process"
    process.pid = 919
    
    adjustments = {
        'cpu_cloak': True,
        'gpu_cloak': True
    }
    
    adjustment_task = {
        'type': 'monitoring',
        'process': process,
        'adjustments': adjustments
    }
    
    resource_manager.execute_adjustment_task(adjustment_task)
    
    mock_apply_monitoring_adjustments.assert_called_once_with(adjustments, process)
    mock_apply_cloak.assert_not_called()
    mock_logger.info.assert_called_with(f"Áp dụng điều chỉnh từ MonitorThread cho tiến trình {process.name} (PID: {process.pid}).")

@patch('mining_environment.scripts.resource_manager.SharedResourceManager.restore_resources')
def test_execute_adjustment_task_with_type_restore(mock_restore_resources, resource_manager, mock_logger):
    """Kiểm thử execute_adjustment_task với nhiệm vụ 'restore'."""
    process = MagicMock()
    process.name = "restore_task_process"
    process.pid = 920
    
    adjustment_task = {
        'type': 'restore',
        'process': process
    }
    
    resource_manager.execute_adjustment_task(adjustment_task)
    
    mock_restore_resources.assert_called_once_with(process)
    mock_logger.info.assert_called_with(f"Đã khôi phục tài nguyên cho tiến trình {process.name} (PID: {process.pid}).")

@patch('mining_environment.scripts.resource_manager.ResourceManager.apply_recommended_action')
@patch('mining_environment.scripts.resource_manager.SharedResourceManager.apply_cloak_strategy')
def test_apply_recommended_action_multiple_calls(mock_apply_cloak, mock_apply_recommended_action, resource_manager, mock_logger):
    """Kiểm thử phương thức apply_recommended_action với nhiều hành động."""
    action = [2, 1024, 55.0, 65.0, 35.0, 45.0]
    process = MagicMock()
    process.pid = 929
    process.name = "multi_action_process"
    
    resource_manager.apply_recommended_action(action, process)
    
    # Kiểm tra các yêu cầu điều chỉnh được đặt vào hàng đợi
    expected_calls = [
        call((3, {
            'function': 'adjust_cpu_threads',
            'args': (929, 2, "multi_action_process")
        })),
        call((3, {
            'function': 'adjust_ram_allocation',
            'args': (929, 1024, "multi_action_process")
        })),
        call((3, {
            'function': 'adjust_gpu_usage',
            'args': (process, [55.0, 65.0, 35.0])
        })),
        call((3, {
            'function': 'adjust_disk_io_limit',
            'args': (process, 35.0)
        })),
        call((3, {
            'function': 'adjust_network_bandwidth',
            'args': (process, 45.0)
        })),
    ]
    resource_manager.resource_adjustment_queue.put.assert_has_calls(expected_calls, any_order=True)
    
    # Kiểm tra áp dụng cloaking cache
    mock_apply_cloak.assert_called_once_with('cache', process)
    
    # Kiểm tra logger
    mock_logger.info.assert_called_with(
        f"Áp dụng thành công các điều chỉnh tài nguyên dựa trên AI cho tiến trình {process.name} (PID: {process.pid})."
    )

@patch('mining_environment.scripts.resource_manager.ResourceManager.execute_adjustment_task')
def test_resource_adjustment_handler_with_task(mock_execute_adjustment_task, resource_manager, mock_logger):
    """Kiểm thử phương thức resource_adjustment_handler với nhiệm vụ cụ thể."""
    process = MagicMock()
    process.name = "specific_task_process"
    process.pid = 930
    
    adjustment_task = {
        'type': 'monitoring',
        'process': process,
        'adjustments': {
            'cpu_cloak': True
        }
    }
    
    with patch.object(resource_manager.resource_adjustment_queue, 'get', return_value=(2, adjustment_task)):
        with patch.object(resource_manager.resource_adjustment_queue, 'task_done') as mock_task_done:
            with patch.object(resource_manager.stop_event, 'is_set', return_value=False):
                with patch('time.sleep', return_value=None):
                    resource_manager.resource_adjustment_handler()
                    mock_execute_adjustment_task.assert_called_once_with(adjustment_task)
                    mock_task_done.assert_called_once()

@patch('mining_environment.scripts.resource_manager.ResourceManager.execute_adjustment_task')
def test_resource_adjustment_handler_with_empty_queue(mock_execute_adjustment_task, resource_manager, mock_logger):
    """Kiểm thử phương thức resource_adjustment_handler khi hàng đợi trống."""
    with patch.object(resource_manager.resource_adjustment_queue, 'get', side_effect=Empty):
        with patch.object(resource_manager.resource_adjustment_queue, 'task_done') as mock_task_done:
            with patch.object(resource_manager.stop_event, 'is_set', return_value=False):
                with patch('time.sleep', return_value=None):
                    resource_manager.resource_adjustment_handler()
                    mock_execute_adjustment_task.assert_not_called()
                    mock_task_done.assert_not_called()

@patch('mining_environment.scripts.resource_manager.ResourceManager.execute_adjustment_task', side_effect=Exception("Adjustment Task Error"))
def test_execute_adjustment_task_error(mock_execute_adjustment_task, resource_manager, mock_logger):
    """Kiểm thử phương thức execute_adjustment_task khi có ngoại lệ."""
    adjustment_task = {
        'type': 'optimization',
        'process': MagicMock(),
        'action': [1, 2, 3]
    }
    
    resource_manager.execute_adjustment_task(adjustment_task)
    
    mock_execute_adjustment_task.assert_called_once_with(adjustment_task)
    # Nếu exception được ném ra bên trong execute_adjustment_task, nó sẽ được log trong resource_adjustment_handler

# ----------------------------
# Kiểm thử các luồng
# ----------------------------

@patch('mining_environment.scripts.resource_manager.ResourceManager.monitor_and_adjust')
@patch('mining_environment.scripts.resource_manager.ResourceManager.optimize_resources')
@patch('mining_environment.scripts.resource_manager.ResourceManager.process_cloaking_requests')
@patch('mining_environment.scripts.resource_manager.ResourceManager.resource_adjustment_handler')
def test_initialize_threads(resource_manager, mock_resource_adjustment_handler, mock_process_cloaking_requests, mock_optimize_resources, mock_monitor_and_adjust):
    """Kiểm thử phương thức initialize_threads."""
    resource_manager.initialize_threads()
    assert resource_manager.monitor_thread.name == "MonitorThread"
    assert resource_manager.optimization_thread.name == "OptimizationThread"
    assert resource_manager.cloaking_thread.name == "CloakingThread"
    assert resource_manager.resource_adjustment_thread.name == "ResourceAdjustmentThread"

@patch('mining_environment.scripts.resource_manager.ResourceManager.monitor_and_adjust')
@patch('mining_environment.scripts.resource_manager.ResourceManager.optimize_resources')
@patch('mining_environment.scripts.resource_manager.ResourceManager.process_cloaking_requests')
@patch('mining_environment.scripts.resource_manager.ResourceManager.resource_adjustment_handler')
def test_start_threads(mock_resource_adjustment_handler, mock_process_cloaking_requests, mock_optimize_resources, mock_monitor_and_adjust, resource_manager):
    """Kiểm thử phương thức start_threads."""
    resource_manager.start_threads()
    mock_monitor_and_adjust.assert_called_once()
    mock_optimize_resources.assert_called_once()
    mock_process_cloaking_requests.assert_called_once()
    mock_resource_adjustment_handler.assert_called_once()

@patch('mining_environment.scripts.resource_manager.ResourceManager.monitor_and_adjust')
@patch('mining_environment.scripts.resource_manager.ResourceManager.optimize_resources')
@patch('mining_environment.scripts.resource_manager.ResourceManager.process_cloaking_requests')
@patch('mining_environment.scripts.resource_manager.ResourceManager.resource_adjustment_handler')
def test_join_threads(mock_resource_adjustment_handler, mock_process_cloaking_requests, mock_optimize_resources, mock_monitor_and_adjust, resource_manager):
    """Kiểm thử phương thức join_threads."""
    resource_manager.join_threads()
    mock_monitor_and_adjust.assert_called_once()
    mock_optimize_resources.assert_called_once()
    mock_process_cloaking_requests.assert_called_once()
    mock_resource_adjustment_handler.assert_called_once()

# ----------------------------
# Kiểm thử Singleton Pattern
# ----------------------------

def test_singleton_pattern(resource_manager):
    """Kiểm thử rằng ResourceManager là Singleton."""
    another_instance = ResourceManager(resource_manager.config, resource_manager.model_path, resource_manager.logger)
    assert resource_manager is another_instance

# ----------------------------
# Kiểm thử các phương thức collect_metrics và prepare_input_features
# ----------------------------

@patch('mining_environment.scripts.resource_manager.psutil.Process')
@patch('mining_environment.scripts.resource_manager.temperature_monitor.get_current_gpu_usage', return_value=70)
@patch('mining_environment.scripts.resource_manager.temperature_monitor.get_current_disk_io_limit', return_value=50.0)
def test_collect_metrics(mock_get_disk_io, mock_get_gpu_usage, mock_psutil_process, resource_manager, mock_logger):
    """Kiểm thử phương thức collect_metrics."""
    mock_process = MagicMock()
    mock_psutil_process.return_value.cpu_percent.return_value = 50
    mock_psutil_process.return_value.memory_info.return_value.rss = 104857600  # 100 MB
    
    metrics = resource_manager.collect_metrics(mock_process)
    
    mock_psutil_process.assert_called_once_with(mock_process.pid)
    mock_psutil_process.return_value.cpu_percent.assert_called_once_with(interval=1)
    mock_psutil_process.return_value.memory_info.assert_called_once()
    mock_get_gpu_usage.assert_called_once_with(mock_process.pid)
    assert metrics == {
        'cpu_usage_percent': 50,
        'memory_usage_mb': 100.0,
        'gpu_usage_percent': 70,
        'disk_io_mbps': 50.0,
        'network_bandwidth_mbps': 100,
        'cache_limit_percent': 50
    }

def test_prepare_input_features(resource_manager):
    """Kiểm thử phương thức prepare_input_features."""
    metrics = {
        'cpu_usage_percent': 50,
        'memory_usage_mb': 1024,
        'gpu_usage_percent': 60,
        'disk_io_mbps': 30.0,
        'network_bandwidth_mbps': 100,
        'cache_limit_percent': 50
    }
    input_features = resource_manager.prepare_input_features(metrics)
    assert input_features == [50, 1024, 60, 30.0, 100, 50]

# ----------------------------
# Kiểm thử load_model
# ----------------------------

@patch('mining_environment.scripts.resource_manager.torch.load', return_value=MagicMock())
@patch('mining_environment.scripts.resource_manager.torch.device', return_value=torch.device("cpu"))
def test_load_model(mock_device, mock_torch_load, resource_manager, mock_logger):
    """Kiểm thử phương thức load_model thành công."""
    model_mock = MagicMock()
    model_mock.eval = MagicMock()
    mock_torch_load.return_value = model_mock
    
    model, device = resource_manager.load_model(resource_manager.model_path)
    
    mock_torch_load.assert_called_once_with(resource_manager.model_path)
    mock_device.assert_called_once_with("cpu")
    model_mock.to.assert_called_once_with(torch.device("cpu"))
    model_mock.eval.assert_called_once()
    mock_logger.info.assert_called_with(f"Tải mô hình tối ưu hóa tài nguyên từ {resource_manager.model_path} vào cpu.")
    assert model == model_mock
    assert device == torch.device("cpu")

@patch('mining_environment.scripts.resource_manager.torch.load', side_effect=Exception("Model Load Error"))
def test_load_model_exception(mock_torch_load, resource_manager, mock_logger):
    """Kiểm thử phương thức load_model khi có ngoại lệ."""
    with pytest.raises(Exception) as excinfo:
        resource_manager.load_model(resource_manager.model_path)
    assert "Model Load Error" in str(excinfo.value)
    mock_torch_load.assert_called_once_with(resource_manager.model_path)
    mock_logger.error.assert_called_with(f"Không thể tải mô hình AI từ {resource_manager.model_path}: Model Load Error")

# ----------------------------
# Kiểm thử execute_adjustment_task helper methods
# ----------------------------

@patch('mining_environment.scripts.resource_manager.ResourceManager.apply_recommended_action')
@patch('mining_environment.scripts.resource_manager.ResourceManager.SharedResourceManager.apply_cloak_strategy')
def test_execute_adjustment_task_optimization_action(mock_apply_cloak, mock_apply_recommended_action, resource_manager, mock_logger):
    """Kiểm thử execute_adjustment_task với nhiệm vụ 'optimization'."""
    process = MagicMock()
    process.name = "optimization_task_process"
    process.pid = 929
    
    adjustment_task = {
        'type': 'optimization',
        'process': process,
        'action': [2, 2048, 60.0, 70.0, 40.0, 50.0]
    }
    
    resource_manager.execute_adjustment_task(adjustment_task)
    
    mock_apply_recommended_action.assert_called_once_with([2, 2048, 60.0, 70.0, 40.0, 50.0], process)
    mock_apply_cloak.assert_not_called()

@patch('mining_environment.scripts.resource_manager.ResourceManager.SharedResourceManager.restore_resources')
def test_execute_adjustment_task_restore_action(mock_restore_resources, resource_manager, mock_logger):
    """Kiểm thử execute_adjustment_task với nhiệm vụ 'restore'."""
    process = MagicMock()
    process.name = "restore_task_process"
    process.pid = 930
    
    adjustment_task = {
        'type': 'restore',
        'process': process
    }
    
    resource_manager.execute_adjustment_task(adjustment_task)
    
    mock_restore_resources.assert_called_once_with(process)
    mock_logger.info.assert_called_with(f"Đã khôi phục tài nguyên cho tiến trình {process.name} (PID: {process.pid}).")

# ----------------------------
# Kiểm thử execute_recommended_action và các queue interactions
# ----------------------------

@patch('mining_environment.scripts.resource_manager.ResourceManager.execute_recommended_action')
def test_apply_recommended_action_and_queue(mock_execute_recommended_action, resource_manager, mock_logger):
    """Kiểm thử việc áp dụng các hành động được mô hình AI đề xuất và tương tác với hàng đợi."""
    action = [4, 2048, 60.0, 70.0, 40.0, 50.0]
    process = MagicMock()
    process.pid = 1013
    process.name = "ai_process_queue"
    
    with patch.object(resource_manager.resource_adjustment_queue, 'put') as mock_queue_put:
        resource_manager.apply_recommended_action(action, process)
        
        expected_calls = [
            call((3, {
                'function': 'adjust_cpu_threads',
                'args': (1013, 4, "ai_process_queue")
            })),
            call((3, {
                'function': 'adjust_ram_allocation',
                'args': (1013, 2048, "ai_process_queue")
            })),
            call((3, {
                'function': 'adjust_gpu_usage',
                'args': (process, [60.0, 70.0, 40.0])
            })),
            call((3, {
                'function': 'adjust_disk_io_limit',
                'args': (process, 40.0)
            })),
            call((3, {
                'function': 'adjust_network_bandwidth',
                'args': (process, 50.0)
            })),
        ]
        mock_queue_put.assert_has_calls(expected_calls, any_order=True)
        
        resource_manager.shared_resource_manager.apply_cloak_strategy.assert_called_once_with('cache', process)
        mock_logger.info.assert_called_with(
            f"Áp dụng thành công các điều chỉnh tài nguyên dựa trên AI cho tiến trình {process.name} (PID: {process.pid})."
        )

# ----------------------------
# Kiểm thử các phương thức tích hợp với SharedResourceManager
# ----------------------------

@patch('mining_environment.scripts.resource_manager.ResourceManager.SharedResourceManager.restore_resources')
def test_restore_resources_integration(mock_restore_resources, resource_manager, mock_logger):
    """Kiểm thử phương thức restore_resources tích hợp với SharedResourceManager."""
    process = MagicMock()
    process.pid = 1113
    process.name = "restore_integration_process"
    
    # Giả lập original_resource_limits
    resource_manager.shared_resource_manager.original_resource_limits = {
        process.pid: {
            'cpu_freq': 3000,
            'cpu_threads': 4,
            'ram_allocation_mb': 2048,
            'gpu_power_limit': 250,
            'ionice_class': 2,
            'network_bandwidth_limit_mbps': 100.0
        }
    }
    
    resource_manager.restore_resources(process)
    
    mock_restore_resources.assert_called_once_with(process)
    mock_logger.info.assert_called_with(f"Đã khôi phục tài nguyên cho tiến trình {process.name} (PID: {process.pid}).")

@patch('mining_environment.scripts.resource_manager.ResourceManager.SharedResourceManager.apply_cloak_strategy')
def test_apply_cloak_strategy_integration(mock_apply_cloak, resource_manager, mock_logger):
    """Kiểm thử phương thức apply_cloak_strategy tích hợp với CloakStrategyFactory và execute_adjustments."""
    strategy_name = "test_strategy_integration"
    process = MagicMock()
    process.pid = 1216
    process.name = "cloak_integration_process"
    
    # Giả lập chiến lược cloaking
    mock_strategy = MagicMock()
    mock_strategy.apply.return_value = {
        'cpu_freq': 2500,
        'gpu_power_limit': 200,
        'network_bandwidth_limit_mbps': 80.0,
        'ionice_class': 2
    }
    
    with patch('mining_environment.scripts.resource_manager.CloakStrategyFactory.create_strategy', return_value=mock_strategy):
        with patch.object(resource_manager, 'execute_adjustments') as mock_execute_adjustments:
            resource_manager.apply_cloak_strategy(strategy_name, process)
            
            mock_apply_cloak.assert_called_once_with(strategy_name, process)
            mock_strategy.apply.assert_called_once_with(process)
            mock_logger.info.assert_called_with(
                f"Áp dụng điều chỉnh {strategy_name} cho tiến trình {process.name} (PID: {process.pid}): {{'cpu_freq': 2500, 'gpu_power_limit': 200, 'network_bandwidth_limit_mbps': 80.0, 'ionice_class': 2}}"
            )
            mock_execute_adjustments.assert_called_once_with(mock_strategy.apply.return_value, process)
            assert resource_manager.shared_resource_manager.original_resource_limits[process.pid] == {
                'cpu_freq': 3000,  # Giả lập get_current_cpu_frequency trả về 3000
                'gpu_power_limit': 250,  # Giả lập get_current_gpu_power_limit trả về 250
                'network_bandwidth_limit_mbps': 100.0,  # Giả lập get_current_network_bandwidth_limit trả về 100.0
                'ionice_class': 1  # Giả lập get_current_ionice_class trả về 1
            }

# ----------------------------
# Kiểm thử xử lý ngoại lệ trong các luồng
# ----------------------------

@patch('mining_environment.scripts.resource_manager.ResourceManager.monitor_and_adjust', side_effect=Exception("Monitor Thread Error"))
def test_monitor_and_adjust_thread_exception(mock_monitor_and_adjust, resource_manager, mock_logger):
    """Kiểm thử luồng monitor_and_adjust khi có ngoại lệ."""
    with patch.object(resource_manager, 'sleep', return_value=None):
        resource_manager.monitor_and_adjust()
        mock_logger.error.assert_called_with("Lỗi trong quá trình theo dõi và điều chỉnh: Monitor Thread Error")

@patch('mining_environment.scripts.resource_manager.ResourceManager.optimize_resources', side_effect=Exception("Optimization Thread Error"))
def test_optimize_resources_thread_exception(mock_optimize_resources, resource_manager, mock_logger):
    """Kiểm thử luồng optimize_resources khi có ngoại lệ."""
    with patch.object(resource_manager, 'sleep', return_value=None):
        resource_manager.optimize_resources()
        mock_logger.error.assert_called_with("Lỗi trong quá trình tối ưu hóa tài nguyên: Optimization Thread Error")

@patch('mining_environment.scripts.resource_manager.ResourceManager.process_cloaking_requests', side_effect=Exception("Cloaking Thread Error"))
def test_process_cloaking_requests_thread_exception(mock_process_cloaking_requests, resource_manager, mock_logger):
    """Kiểm thử luồng process_cloaking_requests khi có ngoại lệ."""
    with patch.object(resource_manager, 'sleep', return_value=None):
        resource_manager.process_cloaking_requests()
        mock_logger.error.assert_called_with("Lỗi trong quá trình xử lý yêu cầu cloaking: Cloaking Thread Error")

@patch('mining_environment.scripts.resource_manager.ResourceManager.resource_adjustment_handler', side_effect=Exception("Resource Adjustment Thread Error"))
def test_resource_adjustment_handler_thread_exception(mock_resource_adjustment_handler, resource_manager, mock_logger):
    """Kiểm thử luồng resource_adjustment_handler khi có ngoại lệ."""
    with patch.object(resource_manager, 'sleep', return_value=None):
        resource_manager.resource_adjustment_handler()
        mock_logger.error.assert_called_with("Lỗi trong quá trình xử lý điều chỉnh tài nguyên: Resource Adjustment Thread Error")

# ----------------------------
# Kiểm thử load_model fail
# ----------------------------

@patch('mining_environment.scripts.resource_manager.ResourceManager.load_model', side_effect=Exception("Load Model Failed"))
def test_load_model_fail(mock_load_model, resource_manager, mock_logger):
    """Kiểm thử khi load_model thất bại trong khởi tạo ResourceManager."""
    with pytest.raises(Exception) as excinfo:
        ResourceManager(resource_manager.config, resource_manager.model_path, resource_manager.logger)
    assert "Load Model Failed" in str(excinfo.value)
    mock_load_model.assert_called_with(resource_manager.model_path)
    mock_logger.error.assert_called_with(f"Không thể tải mô hình AI từ {resource_manager.model_path}: Load Model Failed")

# ----------------------------
# Kiểm thử destroy singleton instance
# ----------------------------

def test_resource_manager_singleton(resource_manager):
    """Kiểm thử rằng ResourceManager là Singleton."""
    another_instance = ResourceManager(resource_manager.config, resource_manager.model_path, resource_manager.logger)
    assert resource_manager is another_instance

# ----------------------------
# Kiểm thử monitor_and_adjust method
# ----------------------------

@patch('mining_environment.scripts.resource_manager.ResourceManager.should_collect_azure_monitor_data', return_value=False)
@patch('mining_environment.scripts.resource_manager.ResourceManager.check_power_and_enqueue')
@patch('mining_environment.scripts.resource_manager.ResourceManager.check_temperature_and_enqueue')
@patch('mining_environment.scripts.resource_manager.ResourceManager.allocate_resources_with_priority')
@patch('mining_environment.scripts.resource_manager.ResourceManager.discover_mining_processes')
def test_monitor_and_adjust_method(mock_discover, mock_allocate, mock_check_temp, mock_check_power, mock_should_collect, resource_manager, mock_logger):
    """Kiểm thử phương thức monitor_and_adjust khi không cần thu thập dữ liệu Azure."""
    process = MagicMock()
    process.update_resource_usage = MagicMock()
    resource_manager.mining_processes = [process]
    
    with patch.object(resource_manager, 'sleep', return_value=None):
        with patch.object(resource_manager.stop_event, 'is_set', return_value=True):
            resource_manager.monitor_and_adjust()
    
    mock_discover.assert_called_once()
    mock_allocate.assert_called_once()
    mock_check_temp.assert_called_once_with(process, 75, 85)
    mock_check_power.assert_called_once_with(process, 150, 300)
    mock_should_collect.assert_called_once()
    mock_logger.error.assert_not_called()

@patch('mining_environment.scripts.resource_manager.ResourceManager.should_collect_azure_monitor_data', return_value=True)
@patch('mining_environment.scripts.resource_manager.ResourceManager.collect_azure_monitor_data')
@patch('mining_environment.scripts.resource_manager.ResourceManager.check_power_and_enqueue')
@patch('mining_environment.scripts.resource_manager.ResourceManager.check_temperature_and_enqueue')
@patch('mining_environment.scripts.resource_manager.ResourceManager.allocate_resources_with_priority')
@patch('mining_environment.scripts.resource_manager.ResourceManager.discover_mining_processes')
def test_monitor_and_adjust_with_azure(mock_discover, mock_allocate, mock_check_temp, mock_check_power, mock_collect_azure, mock_should_collect, resource_manager, mock_logger):
    """Kiểm thử phương thức monitor_and_adjust khi cần thu thập dữ liệu Azure."""
    process = MagicMock()
    process.update_resource_usage = MagicMock()
    resource_manager.mining_processes = [process]
    
    with patch.object(resource_manager, 'sleep', return_value=None):
        with patch.object(resource_manager.stop_event, 'is_set', return_value=True):
            resource_manager.monitor_and_adjust()
    
    mock_discover.assert_called_once()
    mock_allocate.assert_called_once()
    mock_check_temp.assert_called_once_with(process, 75, 85)
    mock_check_power.assert_called_once_with(process, 150, 300)
    mock_should_collect.assert_called_once()
    mock_collect_azure.assert_called_once()
    mock_logger.error.assert_not_called()

# ----------------------------
# Kiểm thử execute_recommended_action method
# ----------------------------

@patch('mining_environment.scripts.resource_manager.ResourceManager.resource_adjustment_queue.put')
def test_apply_recommended_action_full(mock_put, resource_manager, mock_logger):
    """Kiểm thử phương thức apply_recommended_action với đầy đủ các hành động."""
    action = [4, 2048, 70.0, 80.0, 60.0, 70.0]
    process = MagicMock()
    process.pid = 1217
    process.name = "full_action_process"
    
    resource_manager.apply_recommended_action(action, process)
    
    expected_calls = [
        call((3, {
            'function': 'adjust_cpu_threads',
            'args': (1217, 4, "full_action_process")
        })),
        call((3, {
            'function': 'adjust_ram_allocation',
            'args': (1217, 2048, "full_action_process")
        })),
        call((3, {
            'function': 'adjust_gpu_usage',
            'args': (process, [70.0, 80.0, 60.0])
        })),
        call((3, {
            'function': 'adjust_disk_io_limit',
            'args': (process, 60.0)
        })),
        call((3, {
            'function': 'adjust_network_bandwidth',
            'args': (process, 70.0)
        })),
    ]
    mock_put.assert_has_calls(expected_calls, any_order=True)
    
    resource_manager.shared_resource_manager.apply_cloak_strategy.assert_called_once_with('cache', process)
    mock_logger.info.assert_called_with(
        f"Áp dụng thành công các điều chỉnh tài nguyên dựa trên AI cho tiến trình {process.name} (PID: {process.pid})."
    )

# ----------------------------
# Kiểm thử các phương thức của ResourceManager liên quan đến AI model
# ----------------------------

@patch('mining_environment.scripts.resource_manager.ResourceManager.resource_optimization_model')
@patch('mining_environment.scripts.resource_manager.torch.tensor')
@patch('mining_environment.scripts.resource_manager.ResourceManager.prepare_input_features')
@patch('mining_environment.scripts.resource_manager.ResourceManager.collect_metrics')
def test_optimize_resources_ai_interaction(mock_collect_metrics, mock_prepare_features, mock_tensor, mock_model, resource_manager, mock_logger):
    """Kiểm thử tương tác với mô hình AI trong optimize_resources."""
    process = MagicMock()
    process.pid = 1318
    process.name = "ai_interaction_process"
    resource_manager.mining_processes = [process]
    
    mock_collect_metrics.return_value = {
        'cpu_usage_percent': 60,
        'memory_usage_mb': 1500,
        'gpu_usage_percent': 70,
        'disk_io_mbps': 40.0,
        'network_bandwidth_mbps': 100,
        'cache_limit_percent': 50
    }
    mock_prepare_features.return_value = [60, 1500, 70, 40.0, 100, 50]
    
    mock_tensor_instance = MagicMock()
    mock_tensor.return_value = mock_tensor_instance
    mock_tensor_instance.to.return_value = mock_tensor_instance
    mock_tensor_instance.unsqueeze.return_value = mock_tensor_instance
    
    mock_prediction = MagicMock()
    mock_prediction.squeeze.return_value = MagicMock(cpu=lambda: MagicMock(numpy=lambda: [10, 20, 30]))
    mock_model.return_value.__call__.return_value = mock_prediction
    
    with patch.object(resource_manager.resource_adjustment_queue, 'put') as mock_queue_put:
        resource_manager.optimize_resources()
    
        mock_collect_metrics.assert_called_once_with(process)
        mock_prepare_features.assert_called_once_with(mock_collect_metrics.return_value)
        mock_tensor.assert_called_once_with([60, 1500, 70, 40.0, 100, 50], dtype=torch.float32)
        mock_tensor_instance.to.assert_called_once_with(resource_manager.resource_optimization_device)
        mock_tensor_instance.unsqueeze.assert_called_once_with(0)
        mock_model.return_value.__call__.assert_called_once_with(mock_tensor_instance)
        mock_prediction.squeeze.assert_called_once_with(0)
        mock_prediction.squeeze.return_value.cpu.return_value.numpy.assert_called_once()
        
        adjustment_task = {
            'type': 'optimization',
            'process': process,
            'action': [10, 20, 30]
        }
        mock_queue_put.assert_called_once_with((2, adjustment_task))
        mock_logger.debug.assert_called_with(f"Mô hình AI đề xuất hành động cho tiến trình {process.name} (PID: {process.pid}): [10, 20, 30]")
