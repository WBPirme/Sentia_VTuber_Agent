import os
import time
import subprocess
import socket
import platform
import urllib.request
import urllib.error


class LlamaEngineController:
    def __init__(self, base_dir, port=8099, model_name="Sentia-Q4_K_M.gguf"):
        self.base_dir = base_dir
        self.engine_root = os.path.join(base_dir, "engine")
        self.model_path = os.path.join(base_dir, "models", model_name)
        self.port = port
        self.process = None

    def _sniff_hardware(self):
        if platform.system() != "Windows": return "llama.cpp-cpu"
        try:
            output = subprocess.check_output("wmic path win32_VideoController get name", shell=True).decode().upper()
            if "NVIDIA" in output: return "llama.cpp-cuda12"
            if "AMD" in output or "RADEON" in output: return "llama.cpp-hip"
            if "INTEL" in output: return "llama.cpp-vulkan"
        except:
            pass
        return "llama.cpp-cpu"

    def is_port_in_use(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('localhost', self.port)) == 0

    def wait_for_server_ready(self, timeout=60):
        print(f" 正在等待模型载入显存 (端口 {self.port})...")
        start_time = time.time()
        url = f"http://localhost:{self.port}/health"
        while time.time() - start_time < timeout:
            try:
                if urllib.request.urlopen(url, timeout=1).getcode() == 200:
                    print(f" 模型已就绪！(耗时: {time.time() - start_time:.1f}秒)")
                    return True
            except:
                time.sleep(0.5)
        print(" 警告：模型启动超时！")
        return False

    def start(self):
        if self.is_port_in_use():
            print(f" 模型已在运行。")
            self.wait_for_server_ready()
            return

        engine_folder = self._sniff_hardware()
        target_engine_dir = os.path.join(self.engine_root, engine_folder)
        exe_path = os.path.join(target_engine_dir, "llama-server.exe")

        print(f" 正在加载 {engine_folder} ...")
        layers = "99" if engine_folder != "llama.cpp-cpu" else "0"

        cmd = [
            exe_path, "-m", self.model_path, "-ngl", layers,
            "--port", str(self.port), "--chat-template", "chatml"
        ]

        env = os.environ.copy()
        env["PATH"] = target_engine_dir + os.pathsep + env.get("PATH", "")

        self.process = subprocess.Popen(
            cmd, cwd=target_engine_dir, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        self.wait_for_server_ready()

    def stop(self):
        if self.process:
            self.process.terminate()
            print("  llama.cpp 已退出。")