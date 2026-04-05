import json
import os
import platform
import socket
import subprocess
import time
import urllib.error
import urllib.request


class LlamaEngineController:
    def __init__(self, base_dir, port=8099, model_name="Sentia-Q4_K_M.gguf"):
        self.base_dir = base_dir
        self.engine_root = os.path.join(base_dir, "engine")
        # ⚠️ 这里用传进来的名字！
        self.model_path = os.path.join(base_dir, "models", model_name)
        self.port = port
        self.process = None

    def _sniff_hardware(self):
        if platform.system() != "Windows":
            print("非 Windows 系统，使用 CPU ")
            return "llama.cpp-cpu"

        try:
            output = subprocess.check_output(
                "wmic path win32_VideoController get name",
                shell=True,
            ).decode(errors="ignore").upper()

            if "NVIDIA" in output:
                print("侦测到 NVIDIA 即将挂载 CUDA 12 ")
                return "llama.cpp-cuda12"

            if "AMD" in output :
                print("侦测到 AMD 即将挂载 HIP ")
                return "llama.cpp-hip"

            if "INTEL" in output:
                print("侦测到 Intel 挂载 Vulkan ")
                return "llama.cpp-vulkan"

        except Exception as exc:
            print(f"硬件检测异常 ({exc})。")

        print("未侦测到兼容显卡，使用 CPU ")
        return "llama.cpp-cpu"

    def is_port_in_use(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            return sock.connect_ex(("localhost", self.port)) == 0

    def _request(self, path, timeout=1):
        url = f"http://localhost:{self.port}{path}"
        return urllib.request.urlopen(url, timeout=timeout)

    def _is_expected_server(self):
        try:
            with self._request("/health") as response:
                if response.getcode() != 200:
                    return False

            with self._request("/v1/models") as response:
                if response.getcode() != 200:
                    return False
                payload = json.loads(response.read().decode("utf-8"))

            model_ids = {
                item.get("id", "")
                for item in payload.get("data", [])
                if isinstance(item, dict)
            }
            return bool(model_ids)
        except (urllib.error.URLError, socket.timeout, ConnectionResetError, json.JSONDecodeError):
            return False

    def wait_for_server_ready(self, timeout=60):
        print(f"等待 llama.cpp 完成加载 (端口 {self.port})...")
        start_time = time.time()

        while time.time() - start_time < timeout:
            if self._is_expected_server():
                print(" llama.cpp 已就绪 (耗时: {:.1f}秒)".format(time.time() - start_time))
                return True
            time.sleep(0.5)

        print(" llama.cpp 启动超时")
        return False

    def start(self):
        if self.is_port_in_use():
            print(f"端口 {self.port} 已被占用，正在确认是否为 llama.cpp ")
            if self.wait_for_server_ready():
                return
            raise RuntimeError(f"端口 {self.port} 已被其他进程占用，或现有服务未就绪")

        engine_folder = self._sniff_hardware()
        target_engine_dir = os.path.join(self.engine_root, engine_folder)
        exe_path = os.path.join(target_engine_dir, "llama-server.exe")

        if not os.path.exists(exe_path):
            raise FileNotFoundError(f"未找到引擎文件: {exe_path}")
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"未找到模型文件: {self.model_path}")

        print(f"加载 {engine_folder} ")

        layers = "99" if engine_folder != "llama.cpp-cpu" else "0"
        cmd = [
            exe_path,
            "-m", self.model_path,
            "-ngl", layers,
            "--port", str(self.port),
            "--chat-template", "chatml",
        ]

        env = os.environ.copy()
        env["PATH"] = target_engine_dir + os.pathsep + env.get("PATH", "")

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.process = subprocess.Popen(
            cmd,
            cwd=target_engine_dir,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )

        if not self.wait_for_server_ready():
            self.stop()
            raise RuntimeError("超时，启动失败")

    def stop(self):
        if not self.process:
            return

        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)

        self.process = None
        print(" llama.cpp 已退出")
