import os
import queue
import sounddevice as sd
import sherpa_onnx
import time

# ================= 1. 初始化听觉皮层 =================
print("正在加载ASR模型")
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
model_dir = os.path.join(base_dir, "models", "asr")

try:
    recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
        tokens=os.path.join(model_dir, "tokens.txt"),
        encoder=os.path.join(model_dir, "encoder-epoch-99-avg-1.onnx"),
        decoder=os.path.join(model_dir, "decoder-epoch-99-avg-1.onnx"),
        joiner=os.path.join(model_dir, "joiner-epoch-99-avg-1.onnx"),
        num_threads=2,
        sample_rate=16000,
        feature_dim=80,
        rule1_min_trailing_silence=1.2,
        rule2_min_trailing_silence=0.8,
        rule3_min_utterance_length=20.0,
        provider="cpu"
    )
    print("✅ 加载完毕")

except Exception as e:
    print(f"加载失败！请检查 models 目录\n报错详情: {e}")
    exit(1)

# ================= 2. 建立声卡回传队列 =================
audio_queue = queue.Queue()
sample_rate = 16000


def audio_callback(indata, frames, time_info, status):
    if status:
        print(f"⚠️ 声卡状态: {status}")
    audio_queue.put(indata[:, 0].copy())


# ================= 3. 开启真·流式监听测试 =================
print("\n🟢 麦克风已开启！请对着麦克风说话 (按 Ctrl+C 退出)...\n")

try:
    stream = recognizer.create_stream()
    last_text = ""

    with sd.InputStream(channels=1, dtype="float32", samplerate=sample_rate, callback=audio_callback):
        while True:
            chunk = audio_queue.get()

            stream.accept_waveform(sample_rate, chunk)

            while recognizer.is_ready(stream):
                recognizer.decode_stream(stream)

            current_text = recognizer.get_result(stream)

            if current_text and current_text != last_text:
                print(f"\r正在听: {current_text}", end="", flush=True)
                last_text = current_text

            # VAD 断句检测
            if recognizer.is_endpoint(stream):
                final_text = recognizer.get_result(stream)
                if not final_text or len(final_text.strip()) == 0:
                    recognizer.reset(stream)
                    continue

                print("\n识别完成！最终结果:", final_text)
                print("-" * 40)

                recognizer.reset(stream)
                last_text = ""

except KeyboardInterrupt:
    print("\n测试结束。")
except Exception as e:
    print(f"\n运行异常: {e}")