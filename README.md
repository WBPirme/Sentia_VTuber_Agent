# 本项目是一个基于大模型本地部署的桌面级虚拟生命全自动交互系统（说人话就是AI虚拟主播）。

## 部署步骤
1. 克隆代码并安装依赖：`pip install -r requirements.txt`
2. 引擎准备：在根目录新建 `engine` 文件夹，下载 llama.cpp 的 Windows HIP 版并放入，同时放入你的 AMD 驱动 dll。（如果是N卡就下 cuda12 版（ cuda13 版也能用，但要到 `models/llm_controller.py`中把 cuda12 改成 cuda13 ）。 I卡下 vulkan 版。 没显卡就下 cpu 版,虽然不知道没显卡来干什么，但下 cpu 版也能运行）
3. 模型准备：在根目录新建 `models` 文件夹。
   - LLM 模型：[下载 Sentia-Q4_K_M.gguf或Sentia-9B-FP16.gguf (https://huggingface.co/BucketP/Sentia-Qwen3.5-9B-GGUF) ]，放入` models `目录。
   - TTS模型，ASR模型和记忆数据库：[下载 G_28300.onnx ， tokens.txt ，asr.rar ，memory_db,rar ，memory_embedding.rar (https://github.com/WBPirme/Sentia/releases/tag/v1.0.0) ]，放入` models `目录，rar 压缩包需解压放入。、
   - VTuber模型(可选): [下载 sxl.rar (https://github.com/WBPirme/Sentia/releases/tag/VTuber_model) ]，具体使用方法查看VTuber Studio文档这里不做说明
4. 启动 steam 下载 Vtuber Studio,下载完成后浏览本地文件并复制 `VTube Studio.exe` 所在文件夹路径，例如`E:\SteamLibrary\steamapps\common\VTube Studio`，打开`main.py`替换`VTS_EXE_PATH`后引号中的内容
5. 运行 `main.py` 启动系统。
